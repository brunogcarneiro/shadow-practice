import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_configuration_loads_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("OPENAI_API_KEY=test-from-dotenv\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("shadow_practice.config.load_dotenv") as load,
            ):
                get_settings()
            load.assert_called_once_with(override=False)

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

    def test_processing_output_updates_structured_progress(self):
        frame = ShadowPracticeFrame.__new__(ShadowPracticeFrame)
        recording = Path("synthetic.wav")
        frame.processing_logs = {recording: []}
        frame.processing_progress = {}
        frame.processing_gauges = {}
        frame.processing_labels = {}
        frame.processing_detail_frames = {}
        frame._handle_processing_output(
            recording,
            json.dumps(
                {
                    "timestamp": "2026-09-04T10:00:00-03:00",
                    "percent": 42,
                    "stage": "transcription",
                    "data": {"processed_seconds": 60, "total_seconds": 120},
                    "description": "Transcrevendo áudio…",
                }
            ),
        )
        self.assertEqual(frame.processing_progress[recording], (42, "Transcrevendo áudio…"))
        self.assertEqual(frame.processing_logs[recording][0]["stage"], "transcription")

    def test_interrupt_terminates_the_subprocess(self):
        frame = ShadowPracticeFrame.__new__(ShadowPracticeFrame)
        recording = Path("synthetic.wav")
        process = Mock()
        process.poll.return_value = None
        frame.processing_recordings = {recording}
        frame.processing_cancelled = set()
        frame.processing_jobs = {recording: process}
        frame.processing_logs = {recording: []}
        frame.processing_progress = {}
        frame.processing_gauges = {}
        frame.processing_labels = {}
        frame.processing_detail_frames = {}
        frame.interrupt_processing(recording)
        process.terminate.assert_called_once_with()
        self.assertIn(recording, frame.processing_cancelled)

    def test_json_schemas_are_valid_json_objects(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("words.schema.json", "speaks.schema.json"):
            payload = json.loads((root / "docs" / "schema" / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
