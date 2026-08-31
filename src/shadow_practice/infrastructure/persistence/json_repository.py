"""Adaptadores de persistência JSON com escrita atômica."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from ...domain.models import GroupRange
from ...domain.transcript import serialize_words


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as file_handle:
        return json.load(file_handle)


def save_json_atomic(path: str, payload: Any, prefix: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    file_descriptor, temporary_path = tempfile.mkstemp(prefix=prefix, suffix=".json.tmp", dir=directory)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, indent=2)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise


def save_words(path: str, words: list[dict[str, Any]], groups: list[GroupRange]) -> None:
    save_json_atomic(path, serialize_words(words, groups), ".words-")


def save_speaks(path: str, speaks: list[dict[str, Any]]) -> None:
    save_json_atomic(path, speaks, ".speaks-")
