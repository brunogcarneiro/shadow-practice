"""OpenAI whisper-1 transcription adapter with word timestamps."""

from __future__ import annotations

import io
import json
import random
import time
from collections.abc import Callable
from pathlib import Path

import requests
from pydub import AudioSegment

from ..config import get_settings
from .speaker_diarization import assign_speakers, validate_speaker_diarization

ProgressCallback = Callable[[int, str, dict], None]
CHUNK_MS = 5 * 60 * 1000
MAX_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


def checkpoint_path(audio_path: Path, output_path: Path | None = None) -> Path:
    if output_path is not None:
        return output_path.parent / ".openai-transcription.checkpoint.json"
    return audio_path.with_suffix(".openai-transcription.checkpoint.json")


def _audio_identity(audio_path: Path) -> dict:
    stat = audio_path.stat()
    return {
        "audio_size": stat.st_size,
        "audio_mtime_ns": stat.st_mtime_ns,
        "chunk_ms": CHUNK_MS,
        "model": "whisper-1",
    }


def _load_checkpoint(
    audio_path: Path, chunk_count: int, output_path: Path | None = None
) -> tuple[int, list[dict]]:
    path = checkpoint_path(audio_path, output_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        completed = int(payload["completed_chunks"])
        words = payload["words"]
        if (
            payload.get("audio") != _audio_identity(audio_path)
            or not 0 <= completed <= chunk_count
            or not isinstance(words, list)
        ):
            return 0, []
        return completed, words
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 0, []


def _save_checkpoint(
    audio_path: Path,
    completed_chunks: int,
    words: list[dict],
    output_path: Path | None = None,
) -> None:
    path = checkpoint_path(audio_path, output_path)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "audio": _audio_identity(audio_path),
        "completed_chunks": completed_chunks,
        "words": words,
    }
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def remove_checkpoint(audio_path: Path, output_path: Path | None = None) -> None:
    path = checkpoint_path(audio_path, output_path)
    if path.exists():
        path.unlink()


def _retry_delay(attempt: int, response: requests.Response | None = None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(60.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.25)


def _transcribe_chunk(
    *,
    encoded: bytes,
    chunk_index: int,
    chunk_count: int,
    url: str,
    api_key: str,
    report: ProgressCallback,
) -> dict:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        report(
            10 + round(45 * chunk_index / chunk_count),
            f"Enviando bloco {chunk_index + 1}/{chunk_count} ao whisper-1 "
            f"(tentativa {attempt}/{MAX_ATTEMPTS})…",
            {
                "completed_chunks": chunk_index,
                "total_chunks": chunk_count,
                "attempt": attempt,
                "max_attempts": MAX_ATTEMPTS,
            },
        )
        response = None
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={
                    "file": (
                        f"chunk-{chunk_index + 1}.flac",
                        io.BytesIO(encoded),
                        "audio/flac",
                    )
                },
                data=[
                    ("model", "whisper-1"),
                    ("language", "en"),
                    ("response_format", "verbose_json"),
                    ("timestamp_granularities[]", "word"),
                ],
                timeout=600,
            )
            if response.ok:
                return response.json()
            if response.status_code not in RETRYABLE_STATUS_CODES:
                raise RuntimeError(f"OpenAI whisper-1 failed: {_openai_error(response)}")
            error = f"HTTP {response.status_code}: {_openai_error(response)}"
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            error = str(exc)

        if attempt == MAX_ATTEMPTS:
            raise RuntimeError(f"OpenAI whisper-1 failed after {MAX_ATTEMPTS} attempts: {error}")
        delay = _retry_delay(attempt, response)
        report(
            10 + round(45 * chunk_index / chunk_count),
            f"Falha transitória no bloco {chunk_index + 1}/{chunk_count}; "
            f"nova tentativa em {delay:.1f}s.",
            {
                "completed_chunks": chunk_index,
                "total_chunks": chunk_count,
                "attempt": attempt,
                "retry_in_seconds": round(delay, 2),
                "error": error,
            },
        )
        time.sleep(delay)

    raise AssertionError("unreachable")


def _openai_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("error", {}).get("message") or payload)
    except (ValueError, AttributeError):
        return response.text.strip() or f"HTTP {response.status_code}"


def transcribe_recording_openai(
    audio_path: str | Path,
    progress_callback: ProgressCallback | None = None,
    output_path: str | Path | None = None,
) -> Path:
    report = progress_callback or (lambda _percent, _message, _data: None)
    audio_path = Path(audio_path)
    checkpoint_output_path = Path(output_path) if output_path is not None else None
    output_path = checkpoint_output_path or audio_path.with_suffix(".words.json")
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for whisper-1 transcription.")
    validate_speaker_diarization()

    report(5, "Preparando áudio para whisper-1…", {"model": "whisper-1"})
    audio = AudioSegment.from_file(audio_path).set_channels(1).set_frame_rate(16_000)
    chunk_count = max(1, (len(audio) + CHUNK_MS - 1) // CHUNK_MS)
    completed_chunks, words = _load_checkpoint(
        audio_path, chunk_count, checkpoint_output_path
    )
    if completed_chunks:
        report(
            10 + round(45 * completed_chunks / chunk_count),
            f"Retomando após {completed_chunks}/{chunk_count} bloco(s) concluído(s)…",
            {
                "completed_chunks": completed_chunks,
                "total_chunks": chunk_count,
                "resumed": True,
            },
        )

    for chunk_index in range(completed_chunks, chunk_count):
        start_ms = chunk_index * CHUNK_MS
        chunk = audio[start_ms : start_ms + CHUNK_MS]
        encoded = io.BytesIO()
        chunk.export(encoded, format="flac")
        payload = _transcribe_chunk(
            encoded=encoded.getvalue(),
            chunk_index=chunk_index,
            chunk_count=chunk_count,
            url=settings.openai_transcriptions_url,
            api_key=settings.openai_api_key,
            report=report,
        )
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
        _save_checkpoint(audio_path, chunk_index + 1, words, checkpoint_output_path)
        report(
            10 + round(45 * (chunk_index + 1) / chunk_count),
            f"Bloco {chunk_index + 1}/{chunk_count} transcrito e salvo.",
            {
                "completed_chunks": chunk_index + 1,
                "total_chunks": chunk_count,
                "checkpoint_saved": True,
            },
        )

    if not words:
        raise RuntimeError("OpenAI whisper-1 returned no timestamped words.")
    report(58, "Transcrição whisper-1 concluída…", {"words": len(words)})
    words = assign_speakers(audio_path, words, report)
    output_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    report(90, "Transcrição concluída…", {"words": len(words), "model": "whisper-1"})
    return output_path
