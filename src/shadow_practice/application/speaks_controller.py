"""Application operations for derived meeting speeches."""

from __future__ import annotations

from typing import Any

from ..domain.models import GroupRange
from ..domain.speaks import build_speaks_from_groups
from ..domain.transcript import split_rewrite_paragraphs
from ..infrastructure.persistence import load_json, save_speaks


class SpeaksController:
    def __init__(self, speaks_file: str):
        self.speaks_file = speaks_file
        self.speaks: list[dict[str, Any]] = []

    def load_or_initialize(self, words: list[dict[str, Any]], groups: list[GroupRange]) -> list[dict[str, Any]]:
        try:
            payload = load_json(self.speaks_file)
        except FileNotFoundError:
            self.speaks = build_speaks_from_groups(words, groups)
            self.save()
            return self.speaks
        self.speaks = [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
        return self.speaks

    def save(self) -> None:
        save_speaks(self.speaks_file, self.speaks)

    def apply_rewrite(self, speak_index: int, rewritten_text: str) -> list[str]:
        paragraphs = split_rewrite_paragraphs(rewritten_text)
        self.speaks[speak_index]["rewrited"] = paragraphs
        self.save()
        return paragraphs
