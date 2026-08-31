"""Regras de domínio sem dependência de UI, áudio, rede ou filesystem."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .models import GroupRange, NormalizationResult, WordsLoadResult


def parse_words_payload(items: Any) -> WordsLoadResult:
    """Converte o payload JSON atual/legado para palavras e grupos."""
    if not isinstance(items, list):
        raise ValueError("O arquivo words.json deve conter uma lista.")

    words: list[dict[str, Any]] = []
    groups: list[GroupRange] = []
    group_start = 0
    current_displayed = False
    current_human = ""
    current_speaker = None
    has_open_group = False
    needs_save = False

    def close_group() -> None:
        nonlocal group_start
        if has_open_group and len(words) > group_start:
            groups.append(GroupRange(
                group_start,
                len(words),
                current_displayed,
                current_human,
            ))

    for item in items:
        if isinstance(item, dict) and "displayed" in item and "word" not in item:
            close_group()
            group_start = len(words)
            current_displayed = bool(item.get("displayed", False))
            current_human = str(item.get("human-transcription", ""))
            current_speaker = None
            has_open_group = True
            continue

        if isinstance(item, dict) and "linebreak" in item:
            close_group()
            group_start = len(words)
            current_displayed = False
            current_human = ""
            current_speaker = None
            has_open_group = True
            needs_save = True
            continue

        if not (isinstance(item, dict) and {"word", "start", "end", "speaker"} <= item.keys()):
            continue

        if not has_open_group:
            has_open_group = True
            group_start = len(words)
            current_displayed = False
            current_human = ""
            needs_save = True

        if current_speaker is not None and item["speaker"] != current_speaker:
            close_group()
            group_start = len(words)
            current_human = ""

        word = dict(item)
        if "discovered" not in word:
            word["discovered"] = False
            needs_save = True
        words.append(word)
        current_speaker = item["speaker"]

    close_group()
    return WordsLoadResult(tuple(words), tuple(groups), needs_save)


def serialize_words(words: Iterable[dict[str, Any]], groups: Iterable[GroupRange]) -> list[dict[str, Any]]:
    words_list = list(words)
    output: list[dict[str, Any]] = []
    for group in groups:
        output.append({
            "displayed": bool(group.displayed),
            "human-transcription": str(group.human_transcription or ""),
        })
        output.extend(dict(word) for word in words_list[group.start_index:group.end_index])
    return output


def validate_groups(words: list[dict[str, Any]], groups: list[GroupRange]) -> None:
    expected_start = 0
    for group_index, group in enumerate(groups):
        if group.start_index != expected_start:
            raise ValueError(f"Grupo {group_index} não é contíguo ao grupo anterior.")
        if group.end_index <= group.start_index:
            raise ValueError(f"Grupo {group_index} está vazio.")
        if group.end_index > len(words):
            raise ValueError(f"Grupo {group_index} ultrapassa a lista de palavras.")
        speakers = {
            words[index]["speaker"]
            for index in range(group.start_index, group.end_index)
        }
        if len(speakers) != 1:
            raise ValueError(f"Grupo {group_index} contém mais de um speaker.")
        if not isinstance(group.human_transcription, str):
            raise ValueError(f"Grupo {group_index} possui human_transcription inválida.")
        expected_start = group.end_index

    if expected_start != len(words):
        raise ValueError("Os grupos não cobrem todas as palavras.")


def normalized_groups(
    words: list[dict[str, Any]],
    groups: list[GroupRange],
    audio_length: float,
    runtime_clips: dict[int, tuple[float, float]] | None = None,
) -> NormalizationResult:
    """Retorna uma versão normalizada sem alterar as coleções de entrada."""
    normalized_words = [dict(word) for word in words]
    normalized_group_ranges = [
        GroupRange(group.start_index, group.end_index, group.displayed, group.human_transcription)
        for group in groups
    ]
    previous_end = 0.0
    for group in normalized_group_ranges:
        if group.start_index >= group.end_index:
            continue
        first_word = normalized_words[group.start_index]
        last_word = normalized_words[group.end_index - 1]
        first_word["start"] = clamp_time(first_word["start"], audio_length)
        last_word["end"] = clamp_time(last_word["end"], audio_length)
        if first_word["start"] < previous_end:
            first_word["start"] = previous_end
        if first_word["start"] > first_word["end"]:
            first_word["start"] = first_word["end"]
        if last_word["end"] < last_word["start"]:
            last_word["end"] = last_word["start"]
        previous_end = last_word["end"]

    valid_clips: dict[int, tuple[float, float]] = {}
    for group_index, clip in (runtime_clips or {}).items():
        if not (0 <= group_index < len(normalized_group_ranges)):
            continue
        group = normalized_group_ranges[group_index]
        if group.start_index >= group.end_index:
            continue
        group_start = float(normalized_words[group.start_index]["start"])
        group_end = float(normalized_words[group.end_index - 1]["end"])
        if group_end <= group_start:
            continue
        clip_start = max(group_start, min(float(clip[0]), group_end))
        clip_end = max(clip_start, min(float(clip[1]), group_end))
        if clip_end > clip_start:
            valid_clips[group_index] = (clip_start, clip_end)
    return NormalizationResult(tuple(normalized_words), tuple(normalized_group_ranges), valid_clips)


def normalize_groups_in_place(
    words: list[dict[str, Any]],
    groups: list[GroupRange],
    audio_length: float,
    runtime_clips: dict[int, tuple[float, float]] | None = None,
) -> dict[int, tuple[float, float]]:
    """Compatibilidade para a UI legada que ainda mantém estado mutável."""
    result = normalized_groups(words, groups, audio_length, runtime_clips)
    words[:] = result.words
    groups[:] = result.groups
    return result.runtime_clips


def clamp_time(value: float, audio_length: float) -> float:
    return max(0.0, min(float(value), float(audio_length)))


def group_data(words: list[dict[str, Any]], group: GroupRange) -> tuple[str, float, float, str]:
    first_word = words[group.start_index]
    last_word = words[group.end_index - 1]
    text = ""
    if group.displayed:
        text = " ".join(
            words[index]["word"] for index in range(group.start_index, group.end_index)
        ).strip()
    return first_word["speaker"], first_word["start"], last_word["end"], text


def find_group_index(groups: list[GroupRange], word_index: int) -> int | None:
    for group_index, group in enumerate(groups):
        if group.start_index <= word_index < group.end_index:
            return group_index
    return None


def split_rewrite_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text.strip()) if paragraph.strip()]


def format_audio_time(value: float) -> str:
    value = max(0.0, float(value))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    seconds = value % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"
    return f"{minutes:02d}:{seconds:05.2f}"
