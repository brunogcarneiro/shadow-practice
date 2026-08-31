import json
import tempfile
import unittest
from pathlib import Path

from shadow_practice.application import TranscriptController


class TranscriptControllerTests(unittest.TestCase):
    def test_load_normalize_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.words.json"
            path.write_text(json.dumps([
                {"displayed": False, "human-transcription": ""},
                {"word": "a", "start": -1, "end": 2, "speaker": "A"},
            ]), encoding="utf-8")
            session = TranscriptController(str(path))
            result = session.load()
            self.assertFalse(session.words[0]["discovered"])
            self.assertTrue(result.needs_save)
            session.normalize(10)
            session.save()
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload[1]["start"], 0.0)
            self.assertFalse(payload[1]["discovered"])


if __name__ == "__main__":
    unittest.main()
