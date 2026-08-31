"""Protocols that isolate application logic from external technologies."""

from __future__ import annotations

from typing import Any, Protocol


class JsonStore(Protocol):
    def load(self, path: str) -> Any: ...

    def save(self, path: str, payload: Any) -> None: ...


class AudioOutput(Protocol):
    def stop(self) -> None: ...

    def play(self, start_time: float, end_time: float | None = None) -> Any: ...

    def is_playing(self) -> bool: ...


class SpeechRewriter(Protocol):
    def rewrite_meeting_speech(self, original_text: str) -> str: ...


class SpeechSynthesizer(Protocol):
    def synthesize_speech(self, text: str) -> bytes: ...
