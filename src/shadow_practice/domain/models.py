"""Data structures shared by pure transcript rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GroupRange:
    """Runtime representation of one persisted transcript group."""

    start_index: int
    end_index: int
    displayed: bool = False
    human_transcription: str = ""


@dataclass
class WordsLoadResult:
    words: tuple[dict[str, Any], ...]
    groups: tuple[GroupRange, ...]
    needs_save: bool


@dataclass(frozen=True)
class NormalizationResult:
    words: tuple[dict[str, Any], ...]
    groups: tuple[GroupRange, ...]
    runtime_clips: dict[int, tuple[float, float]]
