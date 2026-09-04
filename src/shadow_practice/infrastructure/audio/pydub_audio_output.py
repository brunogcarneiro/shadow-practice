"""Adaptador impuro para reprodução de segmentos de áudio."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class AudioPlaybackService:
    """Executa segmentos sem expor pydub/simpleaudio à camada de UI."""

    def __init__(self, audio_segment: Any, play_buffer: Callable[..., Any]):
        self.audio_segment = audio_segment
        self.play_buffer = play_buffer
        self.play_obj = None

    def stop(self) -> None:
        if self.play_obj is not None and self.play_obj.is_playing():
            self.play_obj.stop()
        self.play_obj = None

    def play(self, start_time: float, end_time: float | None = None):
        self.stop()
        start_ms = max(0, int(float(start_time) * 1000))
        end_ms = None if end_time is None else max(start_ms, int(float(end_time) * 1000))
        if end_ms is not None and end_ms <= start_ms:
            raise ValueError("Cannot play an empty audio range.")
        segment = self.audio_segment[start_ms:end_ms]
        if not segment.raw_data:
            raise ValueError("Cannot play an empty audio buffer.")
        self.play_obj = self.play_buffer(
            segment.raw_data,
            segment.channels,
            segment.sample_width,
            segment.frame_rate,
        )
        return self.play_obj

    def is_playing(self) -> bool:
        return self.play_obj is not None and self.play_obj.is_playing()
