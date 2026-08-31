"""Derivação pura de falas a partir dos grupos do transcript."""

from typing import Any

from .models import GroupRange


def build_speaks_from_groups(words: list[dict[str, Any]], groups: list[GroupRange]) -> list[dict[str, Any]]:
    speaks: list[dict[str, Any]] = []
    for group in groups:
        if group.end_index <= group.start_index:
            continue
        first_word = words[group.start_index]
        last_word = words[group.end_index - 1]
        speaker = str(first_word["speaker"])
        human = str(group.human_transcription or "").strip()

        if speaks and speaks[-1]["speaker"] == speaker:
            speak = speaks[-1]
            speak["end"] = last_word["end"]
            if human:
                previous = str(speak.get("human-transcription", "")).strip()
                speak["human-transcription"] = " ".join(value for value in (previous, human) if value)
            continue

        speaks.append({
            "speaker": speaker,
            "start": first_word["start"],
            "end": last_word["end"],
            "human-transcription": human,
            "rewrited": [],
        })
    return speaks
