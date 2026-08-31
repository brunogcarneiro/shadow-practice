"""Application service for playback state transitions."""

from __future__ import annotations

from ..domain.playback import PlaybackState, advance, resolve_seek


class PlaybackController:
    def __init__(self, audio_length: float):
        self.audio_length = max(0.0, float(audio_length))
        self.state = PlaybackState()

    def start(self, start: float, end: float | None = None, loop_range=None) -> PlaybackState:
        start = max(0.0, min(float(start), self.audio_length))
        end = self.audio_length if end is None else max(start, min(float(end), self.audio_length))
        self.state = PlaybackState(start, True, end, loop_range)
        return self.state

    def pause(self) -> PlaybackState:
        self.state = PlaybackState(self.state.current_time, False, None, None)
        return self.state

    def seek_relative(self, seconds: float) -> PlaybackState:
        target = resolve_seek(self.state.current_time, seconds, self.audio_length, self.state.end_time)
        self.state = PlaybackState(target, self.state.is_playing, self.state.end_time, self.state.loop_range)
        return self.state

    def advance_to(self, current_time: float) -> PlaybackState:
        self.state = advance(self.state, current_time, self.audio_length)
        return self.state
