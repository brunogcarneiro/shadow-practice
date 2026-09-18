"""Persistent one-to-many processing runs associated with an audio recording."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ProcessingRun:
    run_id: str
    model: str
    started_at: str
    status: str
    words_path: Path
    metadata_path: Path | None

    @property
    def label(self) -> str:
        try:
            moment = datetime.fromisoformat(self.started_at).astimezone()
            timestamp = moment.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = self.started_at
        return f"{self.model} — {timestamp}"


def processing_root(audio_path: Path) -> Path:
    return audio_path.parent / f"{audio_path.stem}.processings"


def create_run_directory(audio_path: Path, model: str, started_at: datetime | None = None) -> Path:
    started_at = started_at or datetime.now().astimezone()
    safe_model = re.sub(r"[^a-z0-9._-]+", "-", model.casefold()).strip("-")
    timestamp = started_at.strftime("%Y%m%dT%H%M%S-%f")
    root = processing_root(audio_path)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"{safe_model}_{timestamp}"
    run_dir.mkdir()
    return run_dir


def run_words_path(run_dir: Path) -> Path:
    return run_dir / "result.words.json"


def _is_grouped_words(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, list) and any(
        isinstance(item, dict) and ("displayed" in item or "linebreak" in item) for item in payload
    )


def list_processing_runs(audio_path: Path) -> list[ProcessingRun]:
    runs: list[ProcessingRun] = []
    root = processing_root(audio_path)
    if root.is_dir():
        for run_dir in root.iterdir():
            metadata_path = run_dir / "metadata.json"
            words_path = run_words_path(run_dir)
            if (
                not run_dir.is_dir()
                or not metadata_path.is_file()
                or not _is_grouped_words(words_path)
            ):
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("status") != "completed":
                continue
            runs.append(
                ProcessingRun(
                    run_id=str(metadata.get("id") or run_dir.name),
                    model=str(metadata.get("model") or "unknown"),
                    started_at=str(metadata.get("started_at") or "unknown"),
                    status="completed",
                    words_path=words_path,
                    metadata_path=metadata_path,
                )
            )

    legacy_words = audio_path.with_suffix(".words.json")
    if _is_grouped_words(legacy_words):
        modified = (
            datetime.fromtimestamp(legacy_words.stat().st_mtime)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        runs.append(
            ProcessingRun(
                run_id="legacy",
                model="legacy",
                started_at=modified,
                status="completed",
                words_path=legacy_words,
                metadata_path=None,
            )
        )
    return sorted(runs, key=lambda run: run.started_at, reverse=True)
