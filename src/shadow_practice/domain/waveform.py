"""Cálculos puros usados pelo desenho e interação do waveform."""

from __future__ import annotations


def sample_peaks(samples, channels: int, sample_width: int, bar_count: int) -> list[float]:
    if not samples or bar_count <= 0:
        return [0.0] * max(0, bar_count)
    channels = max(1, channels)
    frames = len(samples) // channels
    if frames <= 0:
        return [0.0] * bar_count
    frames_per_bar = max(1, (frames + bar_count - 1) // bar_count)
    max_possible = float(1 << (8 * sample_width - 1))
    bars: list[float] = []
    for bar_index in range(bar_count):
        start_frame = bar_index * frames_per_bar
        if start_frame >= frames:
            bars.append(0.0)
            continue
        end_frame = min(frames, start_frame + frames_per_bar)
        peak = 0
        for frame_index in range(start_frame, end_frame):
            offset = frame_index * channels
            for channel_index in range(channels):
                peak = max(peak, abs(samples[offset + channel_index]))
        bars.append(min(1.0, peak / max_possible))
    return bars


def time_from_x(x: float, segment_start: float, segment_end: float, width: int) -> float:
    if width <= 1 or segment_end <= segment_start:
        return segment_start
    progress = max(0.0, min(1.0, float(x) / float(width - 1)))
    return segment_start + (segment_end - segment_start) * progress


def x_from_time(value: float, segment_start: float, segment_end: float, width: int) -> int:
    if width <= 1 or segment_end <= segment_start:
        return 0
    progress = (float(value) - segment_start) / (segment_end - segment_start)
    return max(0, min(width - 1, int(max(0.0, min(1.0, progress)) * (width - 1))))
