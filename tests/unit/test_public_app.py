import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shadow_practice.config import get_settings
from shadow_practice.presentation.wx.launcher import ShadowPracticeFrame, is_processed_recording


class PublicAppTests(unittest.TestCase):
    def test_configuration_comes_from_environment(self):
        with patch.dict(
            os.environ,
            {
                "SHADOW_PRACTICE_RECORDINGS_DIR": "/tmp/shadow-test",
                "SHADOW_PRACTICE_AUDIO_DEVICE": "Test Device",
                "SHADOW_PRACTICE_DEBUG": "true",
            },
        ):
            settings = get_settings()
        self.assertEqual(settings.recordings_dir, Path("/tmp/shadow-test"))
        self.assertEqual(settings.audio_device, "Test Device")
        self.assertTrue(settings.debug)

    def test_processed_recording_requires_a_valid_group_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            words = audio.with_suffix(".words.json")
            audio.touch()
            words.write_text('[{"word": "hello"}]', encoding="utf-8")
            self.assertFalse(is_processed_recording(audio))
            words.write_text('[{"displayed": false}]', encoding="utf-8")
            self.assertTrue(is_processed_recording(audio))
            words.write_text("not json", encoding="utf-8")
            self.assertFalse(is_processed_recording(audio))

    def test_processing_worker_reports_success_without_real_models(self):
        frame = ShadowPracticeFrame.__new__(ShadowPracticeFrame)
        recording = Path("synthetic.wav")
        with (
            patch(
                "shadow_practice.presentation.wx.launcher.transcribe_recording",
                return_value=Path("synthetic.words.json"),
            ),
            patch("shadow_practice.presentation.wx.launcher.group_words_file") as group,
            patch("shadow_practice.presentation.wx.launcher.wx.CallAfter") as call_after,
        ):
            frame._process_recording_worker(recording)
        group.assert_called_once_with(Path("synthetic.words.json"))
        call_after.assert_called_once_with(frame._finish_processing, recording, None)

    def test_json_schemas_are_valid_json_objects(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("words.schema.json", "speaks.schema.json"):
            payload = json.loads((root / "docs" / "schema" / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
