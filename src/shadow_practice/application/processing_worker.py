"""Isolated recording processor that emits JSON events on stdout."""

from __future__ import annotations

import argparse
import json
import numbers
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

import soundfile as sf

from ..infrastructure.forced_alignment import align_transcript_file
from ..infrastructure.openai_transcription import (
    remove_checkpoint,
    transcribe_recording_openai,
)
from ..infrastructure.transcription import transcribe_recording
from .processing_runs import create_run_directory, run_words_path
from .sense_groups import group_words_file


def _json_default(value):
    """Normalize scalar values emitted by scientific Python libraries."""
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is not value:
            return scalar
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def emit(percent: int, stage: str, data: dict, description: str) -> None:
    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "percent": max(0, min(100, int(percent))),
        "stage": stage,
        "data": data,
        "description": description,
    }
    print(json.dumps(event, ensure_ascii=False, default=_json_default), flush=True)


class StageTracker:
    def __init__(self):
        self.current: str | None = None
        self.started = time.perf_counter()
        self.durations: dict[str, float] = {}

    def switch(self, stage: str) -> None:
        now = time.perf_counter()
        if self.current is not None:
            self.durations[self.current] = self.durations.get(self.current, 0.0) + (
                now - self.started
            )
        self.current = stage
        self.started = now

    def finish(self) -> None:
        if self.current is not None:
            self.switch("finished")
            self.current = None


def _model_details(transcript_path: Path | None, transcription_model: str) -> tuple[str, str, bool]:
    if transcript_path is not None:
        return "qwen3-forced-aligner-0.6b", "local", False
    if transcription_model == "whisper-1":
        return "whisper-1", "openai", True
    return "whisper-large", "local", False


def _write_metadata(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    temporary.replace(path)


def process(
    audio_path: Path,
    transcript_path: Path | None = None,
    transcription_model: str = "local",
    run_dir: Path | None = None,
) -> Path:
    started_at = datetime.now().astimezone()
    model, provider, uses_api = _model_details(transcript_path, transcription_model)
    run_dir = run_dir or create_run_directory(audio_path, model, started_at)
    run_dir.mkdir(parents=True, exist_ok=True)
    words_output = run_words_path(run_dir)
    metadata_path = run_dir / "metadata.json"
    audio_info = sf.info(audio_path)
    audio_duration = float(audio_info.duration)
    price_per_minute = float(os.getenv("OPENAI_WHISPER_1_USD_PER_MINUTE", "0.006"))
    metadata = {
        "schema_version": 1,
        "id": run_dir.name,
        "audio": {
            "name": audio_path.name,
            "size_bytes": audio_path.stat().st_size,
            "duration_seconds": round(audio_duration, 3),
        },
        "model": model,
        "provider": provider,
        "uses_api": uses_api,
        "mode": "forced-alignment" if transcript_path is not None else "transcription",
        "source_transcript": transcript_path.name if transcript_path is not None else None,
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": None,
        "status": "running",
        "total_duration_seconds": None,
        "stages": {},
        "artifacts": {"words": words_output.name, "speaks": "result.speaks.json"},
    }
    _write_metadata(metadata_path, metadata)
    tracker = StageTracker()
    tracker.switch("preparation")
    emit(
        1,
        "preparation",
        {
            "audio": audio_path.name,
            "transcription_model": transcription_model,
            "processing_id": run_dir.name,
            "model": model,
        },
        "Processamento iniciado.",
    )

    def transcription_progress(percent: int, message: str, data: dict | None = None) -> None:
        event_data = data or {}
        stage = (
            "diarization"
            if "diariza" in message.casefold() or "falantes" in message.casefold()
            else "transcription"
        )
        if tracker.current != stage:
            tracker.switch(stage)
        emit(percent, stage, event_data, message)

    if transcript_path is None:
        tracker.switch("transcription")
        if transcription_model == "whisper-1":
            words_path = transcribe_recording_openai(
                audio_path,
                progress_callback=transcription_progress,
                output_path=words_output,
            )
        else:
            words_path = transcribe_recording(
                audio_path,
                progress_callback=transcription_progress,
                output_path=words_output,
            )
    else:
        tracker.switch("forced-alignment")
        emit(
            5,
            "forced-alignment",
            {"transcript": transcript_path.name},
            "Carregando transcrição fornecida…",
        )

        def alignment_progress(completed: int, total: int, data: dict) -> None:
            phase = data.get("phase")
            if phase == "model-loading":
                description = "Carregando o modelo de alinhamento forçado…"
            elif phase == "model-loaded":
                description = "Modelo carregado; iniciando o alinhamento ao áudio."
            elif phase == "timeline-normalized":
                offset = float(data.get("timeline_offset_seconds", 0))
                skipped = int(data.get("skipped_out_of_range_blocks", 0))
                description = (
                    f"Linha do tempo ajustada em {offset:.1f}s; "
                    f"{skipped} bloco(s) fora da gravação ignorado(s)."
                )
            else:
                description = f"Bloco {completed} de {total} alinhado ao áudio."
            emit(
                10 + round(79 * completed / max(1, total)),
                "forced-alignment",
                {"completed_blocks": completed, "total_blocks": total, **data},
                description,
            )

        words_path = align_transcript_file(
            audio_path,
            transcript_path,
            progress_callback=alignment_progress,
            output_path=words_output,
        )
    tracker.switch("sense-groups")
    emit(90, "sense-groups", {"file": words_path.name}, "Preparando sense groups.")

    def grouping_progress(completed: int, total: int) -> None:
        percent = 90 + round(9 * completed / max(1, total))
        emit(
            percent,
            "sense-groups",
            {"completed_chunks": completed, "total_chunks": total},
            f"Trecho {completed} de {total} dos sense groups concluído.",
        )

    group_words_file(words_path, progress_callback=grouping_progress)
    if transcript_path is None and transcription_model == "whisper-1":
        remove_checkpoint(audio_path, words_output)
    tracker.finish()
    completed_at = datetime.now().astimezone()
    stages = {}
    for stage, duration in tracker.durations.items():
        if stage == "finished":
            continue
        stage_metadata = {
            "duration_seconds": round(duration, 3),
            "cost": None,
        }
        if uses_api and stage == "transcription":
            stage_metadata["cost"] = {
                "amount": round(audio_duration / 60 * price_per_minute, 6),
                "currency": "USD",
                "estimated": True,
                "rate": price_per_minute,
                "rate_unit": "audio_minute",
            }
        stages[stage] = stage_metadata
    metadata.update(
        {
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "status": "completed",
            "total_duration_seconds": round((completed_at - started_at).total_seconds(), 3),
            "stages": stages,
        }
    )
    _write_metadata(metadata_path, metadata)
    emit(
        100,
        "complete",
        {"file": words_path.name, "processing_id": run_dir.name, "metadata": metadata},
        "Processamento concluído.",
    )
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--transcription-model", choices=("local", "whisper-1"), default="local")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    try:
        process(
            args.audio_path.resolve(),
            args.transcript.resolve() if args.transcript is not None else None,
            args.transcription_model,
            args.run_dir.resolve() if args.run_dir is not None else None,
        )
    except Exception as error:
        if args.run_dir is not None:
            metadata_path = args.run_dir.resolve() / "metadata.json"
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata.update(
                    {
                        "status": "failed",
                        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "error": str(error),
                    }
                )
                _write_metadata(metadata_path, metadata)
            except (OSError, ValueError, TypeError):
                pass
        emit(
            0,
            "error",
            {"type": type(error).__name__, "traceback": traceback.format_exc()},
            str(error),
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
