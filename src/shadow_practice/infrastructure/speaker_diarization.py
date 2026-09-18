"""Shared local speaker diarization for timestamped transcription words."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..config import get_settings

ProgressCallback = Callable[[int, str, dict], None]


def validate_speaker_diarization() -> None:
    if not get_settings().huggingface_token:
        raise RuntimeError("HUGGINGFACE_TOKEN is required for speaker diarization.")


def assign_speakers(
    audio_path: Path,
    words: list[dict],
    progress_callback: ProgressCallback,
) -> list[dict]:
    import torch
    from pyannote.audio import Pipeline

    settings = get_settings()
    validate_speaker_diarization()
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    progress_callback(60, "Carregando diarização…", {"pipeline": "speaker-diarization-3.0"})
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.0", token=settings.huggingface_token
    )
    pipeline.to(device)
    progress_callback(68, "Identificando falantes…", {"audio": audio_path.name})

    class DiarizationProgress:
        step_percent = {
            "segmentation": 73,
            "speaker_counting": 77,
            "embeddings": 84,
            "discrete_diarization": 88,
        }

        def __call__(self, step_name, _artifact, file=None, total=None, completed=None):
            progress_callback(
                self.step_percent.get(step_name, 68),
                "Identificando falantes…",
                {
                    "diarization_step": step_name,
                    "completed": int(completed) if completed is not None else None,
                    "total": int(total) if total is not None else None,
                },
            )

    diarization = pipeline(str(audio_path), hook=DiarizationProgress())
    segments = [
        {"speaker": speaker, "start": turn.start, "end": turn.end}
        for turn, _, speaker in diarization.speaker_diarization.itertracks(yield_label=True)
    ]

    progress_callback(88, "Associando palavras e falantes…", {"words": len(words)})
    assigned = []
    for word in words:
        speaker = None
        max_overlap = 0.0
        for segment in segments:
            overlap = min(word["end"], segment["end"]) - max(
                word["start"], segment["start"]
            )
            if overlap > max_overlap:
                max_overlap = overlap
                speaker = segment["speaker"]
        if speaker:
            assigned.append({**word, "speaker": speaker})
    return assigned
