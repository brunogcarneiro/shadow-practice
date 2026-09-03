"""Transcrição e diarização de uma gravação selecionada."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from ..config import get_settings

ProgressCallback = Callable[[int, str], None]


def transcribe_recording(
    audio_path: str | Path,
    model_name: str = "large",
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Gera o arquivo bruto ``.words.json`` para uma gravação WAV."""
    report = progress_callback or (lambda _percent, _message: None)
    import torch
    import whisper
    from pyannote.audio import Pipeline

    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Gravação não encontrada: {audio_path}")

    report(5, "Carregando o Whisper…")
    settings = get_settings()
    if not settings.huggingface_token:
        raise RuntimeError("HUGGINGFACE_TOKEN is required for speaker diarization.")
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = whisper.load_model(model_name)
    report(15, "Transcrevendo o áudio…")
    result = model.transcribe(str(audio_path), language="en", word_timestamps=True)

    report(60, "Carregando a diarização…")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.0", token=settings.huggingface_token
    )
    pipeline.to(device)
    report(68, "Identificando os falantes…")
    diarization = pipeline(str(audio_path))
    speaker_segments = [
        {"speaker": speaker, "start": turn.start, "end": turn.end}
        for turn, _, speaker in diarization.speaker_diarization.itertracks(yield_label=True)
    ]

    def best_speaker_for(start: float, end: float) -> str | None:
        best_speaker = None
        max_overlap = 0.0
        for segment in speaker_segments:
            overlap = min(end, segment["end"]) - max(start, segment["start"])
            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = segment["speaker"]
        return best_speaker

    report(88, "Associando palavras e falantes…")
    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            speaker = best_speaker_for(word["start"], word["end"])
            if speaker:
                words.append({
                    "word": word["word"].strip(),
                    "start": word["start"],
                    "end": word["end"],
                    "speaker": speaker,
                })

    output_path = audio_path.with_suffix(".words.json")
    with output_path.open("w", encoding="utf-8") as output:
        json.dump(words, output, ensure_ascii=False, indent=2)
    report(90, "Transcrição concluída…")
    return output_path
