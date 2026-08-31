"""UI-independent mutable state for one open player window."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.playback import PlaybackState


@dataclass
class ApplicationState:
    selected_group_index: int | None = None
    selected_word_index: int | None = None
    selected_speak_index: int | None = None
    playback: PlaybackState = field(default_factory=PlaybackState)
    runtime_group_clips: dict[int, tuple[float, float]] = field(default_factory=dict)
