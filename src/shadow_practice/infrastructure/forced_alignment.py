"""Align an existing timestamped meeting transcript to its recording."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProgressCallback = Callable[[int, int, dict], None]
TIMESTAMP = re.compile(r"(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2})")
SPEAKER_LINE = re.compile(r"^(?P<speaker>[^:\n]{1,120}):\s*(?P<text>.+)$")


@dataclass(frozen=True)
class TranscriptTurn:
    speaker: str
    text: str


@dataclass(frozen=True)
class TranscriptBlock:
    start: float
    speaker: str
    text: str
    turns: tuple[TranscriptTurn, ...] = ()


def _seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_timestamped_transcript(text: str) -> list[TranscriptBlock]:
    """Normalize timestamped Meet/Gemini exports into alignment blocks."""
    blocks: list[TranscriptBlock] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = TIMESTAMP.search(line)
        if not line or match is None:
            if blocks and line:
                previous = blocks[-1]
                speaker_match = SPEAKER_LINE.match(line)
                if speaker_match:
                    speaker = speaker_match.group("speaker").strip()
                    content = speaker_match.group("text").strip()
                    turns = (*previous.turns, TranscriptTurn(speaker, content))
                elif previous.turns:
                    last = previous.turns[-1]
                    content = line
                    turns = (
                        *previous.turns[:-1],
                        TranscriptTurn(last.speaker, f"{last.text} {content}"),
                    )
                else:
                    content = line
                    turns = (TranscriptTurn(previous.speaker, content),)
                blocks[-1] = TranscriptBlock(
                    previous.start,
                    turns[0].speaker,
                    " ".join(part for part in (previous.text, content) if part),
                    turns,
                )
            continue
        before = line[: match.start()].strip(" -\t")
        after = line[match.end() :].strip(" -:\t")
        if before:
            speaker, content = before.rstrip(":-"), after
        elif ":" in after:
            speaker, content = (part.strip() for part in after.split(":", 1))
        else:
            speaker, content = "SPEAKER_00", after
        turns = (TranscriptTurn(speaker, content),) if content else ()
        blocks.append(
            TranscriptBlock(_seconds(match.group("time")), speaker, content, turns)
        )
    return [block for block in blocks if block.text]


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
    blocks = parse_timestamped_transcript(transcript)
    if not blocks:
        if duration > 300:
            raise ValueError(
                "Transcripts for audio longer than five minutes must contain timestamps."
            )
        blocks = [TranscriptBlock(0.0, "SPEAKER_00", " ".join(transcript.split()))]

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
        end = min(duration, max(block.start + 0.1, end))
        if end - block.start > 300:
            raise ValueError(
                f"Transcript block at {block.start:.1f}s exceeds the five-minute limit."
            )
        clip = audio[int(block.start * sample_rate) : int(end * sample_rate)]
        result = aligner.align(
            audio=(clip, sample_rate), text=block.text, language="English"
        )[0]
        for item_index, item in enumerate(result):
            words.append(
                {
                    "word": item.text,
                    "start": round(block.start + item.start_time, 3),
                    "end": round(block.start + item.end_time, 3),
                    "speaker": _speaker_for_item(item_index, len(result), block),
                }
            )
        report(
            index + 1,
            total,
            {"speaker": block.speaker, "start": block.start, "end": end},
        )

    output_path = audio_path.with_suffix(".words.json")
    output_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
