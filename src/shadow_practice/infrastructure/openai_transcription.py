"""OpenAI whisper-1 transcription adapter with word timestamps."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import requests
from pydub import AudioSegment

from ..config import get_settings
from .speaker_diarization import assign_speakers, validate_speaker_diarization

ProgressCallback = Callable[[int, str, dict], None]
CHUNK_MS = 5 * 60 * 1000


def _openai_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("error", {}).get("message") or payload)
    except (ValueError, AttributeError):
        return response.text.strip() or f"HTTP {response.status_code}"


def transcribe_recording_openai(
    audio_path: str | Path,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    report = progress_callback or (lambda _percent, _message, _data: None)
    audio_path = Path(audio_path)
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for whisper-1 transcription.")
    validate_speaker_diarization()

    report(5, "Preparando áudio para whisper-1…", {"model": "whisper-1"})
    audio = AudioSegment.from_file(audio_path).set_channels(1).set_frame_rate(16_000)
    chunk_count = max(1, (len(audio) + CHUNK_MS - 1) // CHUNK_MS)
    words: list[dict] = []

    for chunk_index in range(chunk_count):
        start_ms = chunk_index * CHUNK_MS
        chunk = audio[start_ms : start_ms + CHUNK_MS]
        encoded = io.BytesIO()
        chunk.export(encoded, format="flac")
        encoded.seek(0)
        report(
            10 + round(45 * chunk_index / chunk_count),
            "Transcrevendo com OpenAI whisper-1…",
            {"completed_chunks": chunk_index, "total_chunks": chunk_count},
        )
        response = requests.post(
            settings.openai_transcriptions_url,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            files={"file": (f"chunk-{chunk_index + 1}.flac", encoded, "audio/flac")},
            data=[
                ("model", "whisper-1"),
                ("language", "en"),
                ("response_format", "verbose_json"),
                ("timestamp_granularities[]", "word"),
            ],
            timeout=600,
        )
        if not response.ok:
            raise RuntimeError(f"OpenAI whisper-1 failed: {_openai_error(response)}")
        payload = response.json()
        offset = start_ms / 1000
        for item in payload.get("words", []):
            text = str(item.get("word", "")).strip()
            if text:
                words.append(
                    {
                        "word": text,
                        "start": round(offset + float(item["start"]), 3),
                        "end": round(offset + float(item["end"]), 3),
                    }
                )

    if not words:
        raise RuntimeError("OpenAI whisper-1 returned no timestamped words.")
    report(58, "Transcrição whisper-1 concluída…", {"words": len(words)})
    words = assign_speakers(audio_path, words, report)
    output_path = audio_path.with_suffix(".words.json")
    output_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    report(90, "Transcrição concluída…", {"words": len(words), "model": "whisper-1"})
    return output_path
