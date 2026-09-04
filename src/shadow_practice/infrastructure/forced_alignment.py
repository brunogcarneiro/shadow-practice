"""Align an existing timestamped meeting transcript to its recording."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProgressCallback = Callable[[int, int, dict], None]
TIMESTAMP = re.compile(r"(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2})")


@dataclass(frozen=True)
class TranscriptBlock:
    start: float
    speaker: str
    text: str


def _seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_timestamped_transcript(text: str) -> list[TranscriptBlock]:
    """Parse common Meet exports such as ``Speaker 00:01:02 text``."""
    blocks: list[TranscriptBlock] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = TIMESTAMP.search(line)
        if not line or match is None:
            if blocks and line:
                previous = blocks[-1]
                blocks[-1] = TranscriptBlock(
                    previous.start,
                    previous.speaker,
                    " ".join(part for part in (previous.text, line) if part),
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
        blocks.append(TranscriptBlock(_seconds(match.group("time")), speaker, content))
    return [block for block in blocks if block.text]


def align_transcript_file(
    audio_path: Path,
    transcript_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Create a raw ``.words.json`` from an existing transcript and audio."""
    import soundfile as sf
    import torch

    try:
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
        for item in result:
            words.append(
                {
                    "word": item.text,
                    "start": round(block.start + item.start_time, 3),
                    "end": round(block.start + item.end_time, 3),
                    "speaker": block.speaker,
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
