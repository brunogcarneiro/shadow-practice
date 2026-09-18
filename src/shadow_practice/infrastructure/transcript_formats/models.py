"""Shared normalized representation for imported transcripts."""

from dataclasses import dataclass


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


@dataclass(frozen=True)
class ParsedTranscript:
    format_name: str
    blocks: tuple[TranscriptBlock, ...]
