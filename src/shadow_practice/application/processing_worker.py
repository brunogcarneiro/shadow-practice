"""Isolated recording processor that emits JSON events on stdout."""

from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime
from pathlib import Path

from ..infrastructure.forced_alignment import align_transcript_file
from ..infrastructure.transcription import transcribe_recording
from .sense_groups import group_words_file


def emit(percent: int, stage: str, data: dict, description: str) -> None:
    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "percent": max(0, min(100, int(percent))),
        "stage": stage,
        "data": data,
        "description": description,
    }
    print(json.dumps(event, ensure_ascii=False), flush=True)


def process(audio_path: Path, transcript_path: Path | None = None) -> None:
    emit(1, "preparation", {"audio": audio_path.name}, "Processamento iniciado.")

    def transcription_progress(percent: int, message: str, data: dict | None = None) -> None:
        emit(percent, "transcription", data or {}, message)

    if transcript_path is None:
        words_path = transcribe_recording(audio_path, progress_callback=transcription_progress)
    else:
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
            audio_path, transcript_path, progress_callback=alignment_progress
        )
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
    emit(100, "complete", {"file": words_path.name}, "Processamento concluído.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path", type=Path)
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args()
    try:
        process(
            args.audio_path.resolve(),
            args.transcript.resolve() if args.transcript is not None else None,
        )
    except Exception as error:
        emit(
            0,
            "error",
            {"type": type(error).__name__, "traceback": traceback.format_exc()},
            str(error),
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
