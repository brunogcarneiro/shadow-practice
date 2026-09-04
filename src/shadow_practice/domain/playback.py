"""Estado puro de reprodução e resolução de comandos de áudio."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybackState:
    current_time: float = 0.0
    is_playing: bool = False
    end_time: float | None = None
    loop_range: tuple[float, float] | None = None


def advance(state: PlaybackState, elapsed_time: float, audio_length: float) -> PlaybackState:
    current = max(0.0, min(float(elapsed_time), float(audio_length)))
    end = state.end_time if state.end_time is not None else audio_length
    if current < end:
        return PlaybackState(current, state.is_playing, state.end_time, state.loop_range)
    if state.loop_range is not None and state.loop_range[1] > state.loop_range[0]:
        return PlaybackState(state.loop_range[0], True, state.end_time, state.loop_range)
    return PlaybackState(min(end, audio_length), False, None, None)


def resolve_seek(current_time: float, delta: float, audio_length: float, end_time: float | None = None) -> float:
    target = max(0.0, min(float(current_time) + float(delta), float(audio_length)))
    if end_time is not None:
        target = min(target, float(end_time))
    return target


def ensure_playable_range(
    start_time: float,
    end_time: float,
    audio_length: float,
    minimum_duration: float = 1.0,
) -> tuple[float, float]:
    """Return a non-empty range, expanding point timestamps when necessary."""
    length = max(0.0, float(audio_length))
    start = max(0.0, min(float(start_time), length))
    end = max(0.0, min(float(end_time), length))
    if end > start or length <= 0:
        return start, end

    window = min(max(0.001, float(minimum_duration)), length)
    expanded_start = max(0.0, min(start - window / 2, length - window))
    return expanded_start, expanded_start + window
