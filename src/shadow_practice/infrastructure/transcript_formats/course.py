"""Parser for AI-course transcripts split into timestamped lecture blocks."""

import re

from .models import ParsedTranscript, TranscriptBlock, TranscriptTurn

BLOCK_TIMESTAMP = re.compile(r"^\[(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2})\]\s*$")
COURSE_SPEAKER = "COURSE_INSTRUCTOR"


def matches(text: str) -> bool:
    return any(BLOCK_TIMESTAMP.fullmatch(line.strip()) for line in text.splitlines())


def _seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse(text: str) -> ParsedTranscript:
    blocks: list[TranscriptBlock] = []
    start: float | None = None
    lines: list[str] = []

    def close_block() -> None:
        if start is None:
            return
        content = " ".join(lines).strip()
        if content:
            turn = TranscriptTurn(COURSE_SPEAKER, content)
            blocks.append(TranscriptBlock(start, COURSE_SPEAKER, content, (turn,)))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        timestamp = BLOCK_TIMESTAMP.fullmatch(line)
        if timestamp:
            close_block()
            start = _seconds(timestamp.group("time"))
            lines = []
        elif line and start is not None:
            lines.append(line)
    close_block()
    return ParsedTranscript("ai-course", tuple(blocks))
