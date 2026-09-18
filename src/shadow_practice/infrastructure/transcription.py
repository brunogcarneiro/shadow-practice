"""Transcrição e diarização de uma gravação selecionada."""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from pathlib import Path

from .speaker_diarization import assign_speakers, validate_speaker_diarization

ProgressCallback = Callable[[int, str, dict], None]


def transcribe_recording(
    audio_path: str | Path,
    model_name: str = "large",
    progress_callback: ProgressCallback | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Gera o arquivo bruto ``.words.json`` para uma gravação WAV."""
    report = progress_callback or (lambda _percent, _message, _data: None)
    import whisper

    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Gravação não encontrada: {audio_path}")
    validate_speaker_diarization()

    report(5, "Carregando Whisper…", {"model": model_name})
    model = whisper.load_model(model_name)
    report(15, "Transcrevendo áudio…", {"device": str(model.device)})
    transcribe_module = importlib.import_module("whisper.transcribe")
    original_tqdm = transcribe_module.tqdm.tqdm

    class ReportingTqdm(original_tqdm):
        def update(self, amount=1):
            result = super().update(amount)
            if self.total:
                completed = min(self.n, self.total)
                percent = 15 + round(44 * completed / self.total)
                report(
                    percent,
                    "Transcrevendo áudio…",
                    {
                        "processed_seconds": round(completed / 100, 1),
                        "total_seconds": round(self.total / 100, 1),
                        "processed_frames": completed,
                        "total_frames": self.total,
                    },
                )
            return result

    transcribe_module.tqdm.tqdm = ReportingTqdm
    try:
        result = model.transcribe(str(audio_path), language="en", word_timestamps=True)
    finally:
        transcribe_module.tqdm.tqdm = original_tqdm

    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            words.append(
                {
                    "word": word["word"].strip(),
                    "start": word["start"],
                    "end": word["end"],
                }
            )

    words = assign_speakers(audio_path, words, report)

    output_path = (
        Path(output_path) if output_path is not None else audio_path.with_suffix(".words.json")
    )
    with output_path.open("w", encoding="utf-8") as output:
        json.dump(words, output, ensure_ascii=False, indent=2)
    report(90, "Transcrição concluída…", {"words": len(words)})
    return output_path
