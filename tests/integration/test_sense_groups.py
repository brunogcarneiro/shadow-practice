import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shadow_practice.application.sense_groups import group_words_file


class SenseGroupsTests(unittest.TestCase):
    def test_grouping_writes_current_group_markers(self):
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
            {"word": "there", "start": 0.5, "end": 1.0, "speaker": "SPEAKER_00"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            words_path = Path(directory) / "sample.words.json"
            words_path.write_text(json.dumps(words), encoding="utf-8")

            with patch(
                "shadow_practice.application.sense_groups.group_chunk",
                side_effect=lambda chunk: [chunk],
            ):
                group_words_file(words_path)

            output = json.loads(words_path.read_text(encoding="utf-8"))

        self.assertEqual(output[0], {"displayed": False, "human-transcription": ""})
        self.assertNotIn("linebreak", output[0])
        self.assertFalse(output[1]["discovered"])


if __name__ == "__main__":
    unittest.main()
