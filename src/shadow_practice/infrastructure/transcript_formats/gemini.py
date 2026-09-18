"""Parser for timestamped Gemini and Google Meet exports."""

import re

from .models import ParsedTranscript, TranscriptBlock, TranscriptTurn

TIMESTAMP = re.compile(r"(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2})")
SPEAKER_LINE = re.compile(r"^(?P<speaker>[^:\n]{1,120}):\s*(?P<text>.+)$")


def _seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse(text: str) -> ParsedTranscript:
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
        blocks.append(TranscriptBlock(_seconds(match.group("time")), speaker, content, turns))
    return ParsedTranscript("gemini", tuple(block for block in blocks if block.text))
