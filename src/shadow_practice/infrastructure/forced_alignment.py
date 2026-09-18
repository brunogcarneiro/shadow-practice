"""Align an existing timestamped meeting transcript to its recording."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .transcript_formats import TranscriptBlock, parse_imported_transcript

ProgressCallback = Callable[[int, int, dict], None]
AUDIO_START = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})"
)
TRANSCRIPT_START = re.compile(
    r"(?P<year>\d{4})[_-](?P<month>\d{2})[_-](?P<day>\d{2})[ _-]+"
    r"(?P<hour>\d{2})[_-](?P<minute>\d{2})(?:[_-](?P<second>\d{2}))?"
    r"[ _-]*(?P<zone>CEST|CET|UTC|GMT|BRT)\b",
    re.IGNORECASE,
)
TIMEZONE_OFFSETS = {
    "CEST": timedelta(hours=2),
    "CET": timedelta(hours=1),
    "UTC": timedelta(0),
    "GMT": timedelta(0),
    "BRT": timedelta(hours=-3),
}


def parse_timestamped_transcript(text: str) -> list[TranscriptBlock]:
    """Compatibility wrapper for callers expecting normalized blocks only."""
    return list(parse_imported_transcript(text).blocks)


def infer_timeline_offset(
    audio_path: Path,
    transcript_path: Path,
    *,
    local_utc_offset: timedelta | None = None,
) -> float | None:
    """Infer seconds between scheduled meeting time and recording start."""
    audio_match = AUDIO_START.search(audio_path.stem)
    transcript_match = TRANSCRIPT_START.search(transcript_path.stem)
    if audio_match is None or transcript_match is None:
        return None

    if local_utc_offset is None:
        local_utc_offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    audio_values = {key: int(value) for key, value in audio_match.groupdict().items()}
    transcript_values = {
        key: int(value or 0)
        for key, value in transcript_match.groupdict().items()
        if key != "zone"
    }
    audio_started = datetime(**audio_values, tzinfo=timezone(local_utc_offset))
    transcript_started = datetime(
        **transcript_values,
        tzinfo=timezone(TIMEZONE_OFFSETS[transcript_match.group("zone").upper()]),
    )
    return (audio_started - transcript_started).total_seconds()


def _fit_blocks_to_audio_timeline(
    blocks: list[TranscriptBlock], duration: float, offset: float
) -> tuple[list[TranscriptBlock], int]:
    adjusted: list[TranscriptBlock] = []
    skipped = 0
    for block in blocks:
        start = block.start - offset
        if start < 0 or start >= duration:
            skipped += 1
            continue
        adjusted.append(
            TranscriptBlock(start, block.speaker, block.text, block.turns)
        )
    return adjusted, skipped


def _speaker_for_item(index: int, item_count: int, block: TranscriptBlock) -> str:
    """Map sequential aligned units back to their normalized transcript turn."""
    if not block.turns:
        return block.speaker
    unit_counts = [
        max(1, len(re.findall(r"\w+(?:['’]\w+)*", turn.text)))
        for turn in block.turns
    ]
    expected_position = (index + 0.5) * sum(unit_counts) / max(1, item_count)
    boundary = 0
    for turn, unit_count in zip(block.turns, unit_counts):
        boundary += unit_count
        if expected_position < boundary:
            return turn.speaker
    return block.turns[-1].speaker


def _safe_alignment_times(result, duration: float) -> list[tuple[float, float]]:
    """Use model times when valid, or evenly distribute units in the block."""
    if not result:
        return []
    previous_end = 0.0
    valid = True
    for item in result:
        start = float(item.start_time)
        end = float(item.end_time)
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous_end
            or end <= start
            or end > duration + 0.001
        ):
            valid = False
            break
        previous_end = end
    if valid:
        return [(float(item.start_time), float(item.end_time)) for item in result]

    weights = [max(1, len(str(item.text).strip())) for item in result]
    total_weight = sum(weights)
    cursor = 0.0
    times = []
    for weight in weights:
        start = cursor
        cursor += duration * weight / total_weight
        times.append((start, cursor))
    return times


def align_transcript_file(
    audio_path: Path,
    transcript_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Create a raw ``.words.json`` from an existing transcript and audio."""
    import soundfile as sf

    try:
        import torch
        from qwen_asr import Qwen3ForcedAligner
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Forced alignment dependencies are not installed. "
            "Run: python -m pip install -e '.[alignment]'"
        ) from error

    report = progress_callback or (lambda _completed, _total, _data: None)
    transcript = transcript_path.read_text(encoding="utf-8-sig")
    audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    duration = len(audio) / sample_rate
    parsed_transcript = parse_imported_transcript(transcript)
    blocks = list(parsed_transcript.blocks)
    if not blocks:
        if duration > 300:
            raise ValueError(
                "Transcripts for audio longer than five minutes must contain timestamps."
            )
        blocks = [TranscriptBlock(0.0, "SPEAKER_00", " ".join(transcript.split()))]
    else:
        timeline_offset = infer_timeline_offset(audio_path, transcript_path) or 0.0
        blocks, skipped_blocks = _fit_blocks_to_audio_timeline(
            blocks, duration, timeline_offset
        )
        report(
            0,
            len(blocks),
            {
                "phase": "timeline-normalized",
                "timeline_offset_seconds": timeline_offset,
                "skipped_out_of_range_blocks": skipped_blocks,
                "audio_duration_seconds": round(duration, 3),
                "transcript_format": parsed_transcript.format_name,
            },
        )
        if not blocks:
            raise ValueError(
                "No timestamped transcript blocks overlap the recorded audio."
            )

    report(0, len(blocks), {"phase": "model-loading"})
    aligner = Qwen3ForcedAligner.from_pretrained(
        "Qwen/Qwen3-ForcedAligner-0.6B",
        dtype=torch.float32,
        device_map="cpu",
    )
    report(0, len(blocks), {"phase": "model-loaded"})
    words: list[dict] = []
    total = len(blocks)
    for index, block in enumerate(blocks):
        end = blocks[index + 1].start if index + 1 < total else duration
        end = min(duration, end)
        if end <= block.start:
            raise ValueError(
                f"Transcript block at {block.start:.1f}s has no overlapping audio."
            )
        if end - block.start > 300:
            raise ValueError(
                f"Transcript block at {block.start:.1f}s exceeds the five-minute limit."
            )
        clip = audio[int(block.start * sample_rate) : int(end * sample_rate)]
        result = aligner.align(
            audio=(clip, sample_rate), text=block.text, language="English"
        )[0]
        alignment_times = _safe_alignment_times(result, end - block.start)
        used_fallback = any(
            (start, finish) != (float(item.start_time), float(item.end_time))
            for item, (start, finish) in zip(result, alignment_times)
        )
        for item_index, (item, (start_time, end_time)) in enumerate(
            zip(result, alignment_times)
        ):
            words.append(
                {
                    "word": item.text,
                    "start": round(block.start + start_time, 3),
                    "end": round(block.start + end_time, 3),
                    "speaker": _speaker_for_item(item_index, len(result), block),
                }
            )
        report(
            index + 1,
            total,
            {
                "speaker": block.speaker,
                "start": block.start,
                "end": end,
                "fallback_timing": used_fallback,
            },
        )

    output_path = audio_path.with_suffix(".words.json")
    output_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
