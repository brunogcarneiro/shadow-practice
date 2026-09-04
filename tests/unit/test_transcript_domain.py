import tempfile
import unittest
from pathlib import Path

from shadow_practice.domain import (
    GroupRange,
    group_data,
    normalized_groups,
    parse_words_payload,
    serialize_words,
    split_rewrite_paragraphs,
    validate_groups,
)
from shadow_practice.domain.playback import (
    PlaybackState,
    advance,
    ensure_playable_range,
    resolve_seek,
)
from shadow_practice.domain.speaks import build_speaks_from_groups
from shadow_practice.domain.waveform import sample_peaks, time_from_x, x_from_time
from shadow_practice.infrastructure.persistence import load_json, save_json_atomic


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.payload = [
            {"displayed": True, "human-transcription": "hello world"},
            {"word": "Hello,", "start": 1.0, "end": 2.0, "speaker": "A"},
            {"word": "world", "start": 2.1, "end": 3.0, "speaker": "A", "discovered": True},
            {"displayed": False, "human-transcription": "next"},
            {"word": "next", "start": 4.0, "end": 5.0, "speaker": "B", "custom": "kept"},
        ]

    def test_parse_initializes_discovered_and_serializes_markers(self):
        result = parse_words_payload(self.payload)
        self.assertEqual(len(result.words), 3)
        self.assertEqual(len(result.groups), 2)
        self.assertFalse(result.words[0]["discovered"])
        self.assertTrue(result.needs_save)
        serialized = serialize_words(list(result.words), list(result.groups))
        self.assertEqual(serialized[0], {"displayed": True, "human-transcription": "hello world"})
        self.assertNotIn("linebreak", str(serialized))
        self.assertEqual(serialized[-1]["custom"], "kept")

    def test_legacy_linebreak_is_migrated(self):
        result = parse_words_payload([
            {"word": "a", "start": 0, "end": 1, "speaker": "A"},
            {"linebreak": None},
            {"word": "b", "start": 1, "end": 2, "speaker": "A"},
        ])
        self.assertEqual(len(result.groups), 2)
        self.assertTrue(result.needs_save)

    def test_validation_and_normalization(self):
        words = [
            {"word": "a", "start": -1, "end": 2, "speaker": "A"},
            {"word": "b", "start": 1, "end": 99, "speaker": "A"},
        ]
        groups = [GroupRange(0, 2)]
        result = normalized_groups(words, groups, 10.0)
        self.assertEqual(words[0]["start"], -1)
        self.assertEqual(result.words[0]["start"], 0.0)
        self.assertEqual(result.words[1]["end"], 10.0)
        validate_groups(list(result.words), list(result.groups))
        self.assertEqual(group_data(list(result.words), result.groups[0])[0], "A")

    def test_speaks_merge_only_adjacent_same_speaker(self):
        words = [
            {"word": "a", "start": 1, "end": 2, "speaker": "A"},
            {"word": "b", "start": 3, "end": 4, "speaker": "A"},
            {"word": "c", "start": 5, "end": 6, "speaker": "B"},
            {"word": "d", "start": 7, "end": 8, "speaker": "A"},
        ]
        groups = [GroupRange(0, 2, human_transcription="a b"), GroupRange(2, 3, human_transcription="c"), GroupRange(3, 4, human_transcription="d")]
        speaks = build_speaks_from_groups(words, groups)
        self.assertEqual([(item["speaker"], item["human-transcription"]) for item in speaks], [("A", "a b"), ("B", "c"), ("A", "d")])

    def test_waveform_and_playback_are_pure_calculations(self):
        self.assertEqual(sample_peaks([0, 10, -20, 0], 1, 2, 2), [10 / 32768, 20 / 32768])
        self.assertEqual(time_from_x(5, 0, 10, 11), 5.0)
        self.assertEqual(x_from_time(5, 0, 10, 11), 5)
        looping = PlaybackState(0, True, 10, (2, 5))
        self.assertEqual(advance(looping, 11, 20).current_time, 2)
        self.assertEqual(resolve_seek(4, 10, 20, 8), 8)
        self.assertEqual(ensure_playable_range(5, 5, 20), (4.5, 5.5))
        self.assertEqual(ensure_playable_range(20, 20, 20), (19.0, 20.0))
        self.assertEqual(ensure_playable_range(3, 4, 20), (3.0, 4.0))

    def test_atomic_json_repository_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "data.json")
            save_json_atomic(path, {"ok": True}, ".test-")
            self.assertEqual(load_json(path), {"ok": True})

    def test_paragraph_split(self):
        self.assertEqual(split_rewrite_paragraphs(" one\n\n two "), ["one", "two"])


if __name__ == "__main__":
    unittest.main()
