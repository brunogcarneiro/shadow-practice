"""Pure business rules for transcripts, speeches and playback."""

from .models import GroupRange, NormalizationResult, WordsLoadResult
from .transcript import (
    clamp_time,
    find_group_index,
    format_audio_time,
    group_data,
    normalized_groups,
    parse_words_payload,
    serialize_words,
    split_rewrite_paragraphs,
    validate_groups,
)

__all__ = [
    "GroupRange", "NormalizationResult", "WordsLoadResult", "clamp_time",
    "find_group_index", "format_audio_time", "group_data", "normalized_groups",
    "parse_words_payload", "serialize_words", "split_rewrite_paragraphs",
    "validate_groups",
]
