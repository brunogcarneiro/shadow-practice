"""Isolated recording processor that emits JSON events on stdout."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

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


def process(audio_path: Path) -> None:
    emit(1, "preparation", {"audio": audio_path.name}, "Processamento iniciado.")

    def transcription_progress(percent: int, message: str, data: dict | None = None) -> None:
        emit(percent, "transcription", data or {}, message)

    words_path = transcribe_recording(audio_path, progress_callback=transcription_progress)
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
    args = parser.parse_args()
    try:
        process(args.audio_path.resolve())
    except Exception as error:
        emit(0, "error", {"type": type(error).__name__}, str(error))
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
