"""Detection and normalization of supported transcript formats."""

from . import course, gemini
from .models import ParsedTranscript, TranscriptBlock, TranscriptTurn


def parse_imported_transcript(text: str) -> ParsedTranscript:
    """Route input to an isolated format adapter."""
    if course.matches(text):
        return course.parse(text)
    return gemini.parse(text)


__all__ = [
    "ParsedTranscript",
    "TranscriptBlock",
    "TranscriptTurn",
    "parse_imported_transcript",
]
