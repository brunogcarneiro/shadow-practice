"""Estado e persistência do transcript, independente de wx."""

from __future__ import annotations

from typing import Any

from ..domain.models import GroupRange, WordsLoadResult
from ..domain.transcript import normalized_groups, parse_words_payload, validate_groups
from ..infrastructure.persistence.json_repository import load_json, save_words


class TranscriptController:
    """Coordena o documento de transcrição e sua persistência."""

    def __init__(self, transcript_file: str):
        self.transcript_file = transcript_file
        self.words: list[dict[str, Any]] = []
        self.groups: list[GroupRange] = []
        self.runtime_group_clips: dict[int, tuple[float, float]] = {}

    def load(self) -> WordsLoadResult:
        result = parse_words_payload(load_json(self.transcript_file))
        self.words = [dict(word) for word in result.words]
        self.groups = list(result.groups)
        self.runtime_group_clips = {}
        return result

    def normalize(self, audio_length: float) -> None:
        result = normalized_groups(
            self.words,
            self.groups,
            audio_length,
            self.runtime_group_clips,
        )
        self.words = [dict(word) for word in result.words]
        self.groups = list(result.groups)
        self.runtime_group_clips = result.runtime_clips

    def save(self) -> None:
        self.validate()
        save_words(self.transcript_file, self.words, self.groups)

    def validate(self) -> None:
        validate_groups(self.words, self.groups)

    def clear_runtime_clips(self) -> None:
        self.runtime_group_clips = {}


# Compatibilidade temporária para integrações que importavam o nome anterior.
TranscriptSession = TranscriptController
