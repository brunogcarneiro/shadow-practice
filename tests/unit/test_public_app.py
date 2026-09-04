import json
import logging
import os
import runpy
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from shadow_practice.config import get_settings
from shadow_practice.infrastructure.application_logging import configure_application_logging
from shadow_practice.infrastructure.forced_alignment import (
    align_transcript_file,
    parse_timestamped_transcript,
)
from shadow_practice.presentation.wx.launcher import (
    ShadowPracticeFrame,
    audio_file_details,
    delete_recording_data,
    is_processed_recording,
    processing_artifacts,
)


class PublicAppTests(unittest.TestCase):
    def test_compatibility_launcher_prioritizes_the_src_package(self):
        project_root = Path(__file__).resolve().parents[2]
        source_root = str(project_root / "src")
        previous_path = sys.path.copy()
        try:
            sys.path[:] = [str(project_root), source_root, *previous_path]
            runpy.run_path(str(project_root / "shadow_practice.py"))
            self.assertEqual(sys.path[0], source_root)
        finally:
            sys.path[:] = previous_path

    def test_configuration_comes_from_environment(self):
        with patch.dict(
            os.environ,
            {
                "SHADOW_PRACTICE_RECORDINGS_DIR": "/tmp/shadow-test",
                "SHADOW_PRACTICE_LOG_DIR": "/tmp/shadow-logs",
                "SHADOW_PRACTICE_AUDIO_DEVICE": "Test Device",
                "SHADOW_PRACTICE_DEBUG": "true",
            },
        ):
            settings = get_settings()
        self.assertEqual(settings.recordings_dir, Path("/tmp/shadow-test"))
        self.assertEqual(settings.log_dir, Path("/tmp/shadow-logs"))
        self.assertEqual(settings.audio_device, "Test Device")
        self.assertTrue(settings.debug)

    def test_each_application_run_gets_a_timestamped_log_file(self):
        root_logger = logging.getLogger()
        previous_handlers = set(root_logger.handlers)
        previous_hook = sys.excepthook
        previous_thread_hook = threading.excepthook
        try:
            with tempfile.TemporaryDirectory() as directory:
                log_path = configure_application_logging(
                    Path(directory),
                    started_at=datetime(2026, 9, 4, 12, 30, 45, 123456, tzinfo=timezone.utc),
                )
                logging.getLogger("shadow_practice.test").error("diagnostic test error")
                for handler in root_logger.handlers:
                    handler.flush()
                self.assertEqual(
                    log_path.name, "shadow-practice-20260904-123045-123456.log"
                )
                self.assertIn(
                    "diagnostic test error", log_path.read_text(encoding="utf-8")
                )
        finally:
            for handler in list(root_logger.handlers):
                if handler not in previous_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()
            sys.excepthook = previous_hook
            threading.excepthook = previous_thread_hook

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

    def test_audio_details_include_duration_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            import numpy as np
            import soundfile as sf

            audio = Path(directory) / "sample.wav"
            sf.write(audio, np.zeros(32_000, dtype=np.float32), 16_000)
            duration, size = audio_file_details(audio)
            self.assertEqual(duration, "0:02")
            self.assertTrue(size.endswith(("KiB", "MiB")))

    def test_delete_recording_data_can_preserve_or_remove_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            words = audio.with_suffix(".words.json")
            speaks = audio.with_suffix(".speaks.json")
            unrelated = audio.with_suffix(".txt")
            for path in (audio, words, speaks, unrelated):
                path.touch()
            words.write_text('[{"displayed": false}]', encoding="utf-8")

            self.assertTrue(is_processed_recording(audio))
            self.assertEqual(processing_artifacts(audio), [words, speaks])
            self.assertEqual(delete_recording_data(audio), [words, speaks])
            self.assertFalse(is_processed_recording(audio))
            self.assertTrue(audio.exists())
            self.assertTrue(unrelated.exists())

            words.touch()
            self.assertEqual(delete_recording_data(audio, include_audio=True), [words, audio])
            self.assertFalse(audio.exists())
            self.assertTrue(unrelated.exists())

    def test_processing_output_updates_structured_progress(self):
        frame = ShadowPracticeFrame.__new__(ShadowPracticeFrame)
        recording = Path("synthetic.wav")
        frame.processing_logs = {recording: []}
        frame.processing_errors = {}
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

    def test_processing_error_preserves_the_worker_message(self):
        frame = ShadowPracticeFrame.__new__(ShadowPracticeFrame)
        recording = Path("synthetic.wav")
        frame.processing_logs = {recording: []}
        frame.processing_errors = {}
        frame.processing_progress = {}
        frame.processing_gauges = {}
        frame.processing_labels = {}
        frame.processing_detail_frames = {}
        frame._handle_processing_output(
            recording,
            json.dumps(
                {
                    "stage": "error",
                    "description": "Forced alignment model could not be loaded.",
                    "data": {"type": "RuntimeError"},
                }
            ),
        )
        self.assertEqual(
            frame.processing_errors[recording],
            "Forced alignment model could not be loaded.",
        )

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

    def test_google_meet_transcript_blocks_are_parsed(self):
        blocks = parse_timestamped_transcript(
            "Bruno Carneiro 00:01:02\nHello from the meeting.\n"
            "00:01:10 Ana: This is the next speaker."
        )
        self.assertEqual(
            [(block.start, block.speaker, block.text) for block in blocks],
            [
                (62, "Bruno Carneiro", "Hello from the meeting."),
                (70, "Ana", "This is the next speaker."),
            ],
        )

    def test_gemini_transcript_sections_are_normalized_without_speaker_labels(self):
        blocks = parse_timestamped_transcript(
            "Meeting notes\n00:00:46\n\nJackie Shiu: Hello there.\n"
            "Ahmed ElSallamy: Hi everyone.\n\n00:04:13\nAriel Hellwitz: Welcome back."
        )
        self.assertEqual(
            [(block.start, block.text) for block in blocks],
            [
                (46, "Hello there. Hi everyone."),
                (253, "Welcome back."),
            ],
        )
        self.assertEqual(
            [(turn.speaker, turn.text) for turn in blocks[0].turns],
            [("Jackie Shiu", "Hello there."), ("Ahmed ElSallamy", "Hi everyone.")],
        )

    def test_forced_alignment_writes_compatible_words_file(self):
        aligned_item = types.SimpleNamespace(text="Hello", start_time=0.2, end_time=0.7)
        aligner = Mock()
        aligner.align.return_value = [[aligned_item]]
        aligner_type = Mock()
        aligner_type.from_pretrained.return_value = aligner
        qwen_module = types.SimpleNamespace(Qwen3ForcedAligner=aligner_type)
        torch_module = types.SimpleNamespace(float32="float32")

        with tempfile.TemporaryDirectory() as directory:
            import numpy as np
            import soundfile as sf

            audio = Path(directory) / "meeting.wav"
            transcript = Path(directory) / "meeting.txt"
            sf.write(audio, np.zeros(16_000, dtype=np.float32), 16_000)
            transcript.write_text("Bruno 00:00 Hello", encoding="utf-8")

            with patch.dict(
                "sys.modules", {"qwen_asr": qwen_module, "torch": torch_module}
            ):
                output = align_transcript_file(audio, transcript)

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                [{"word": "Hello", "start": 0.2, "end": 0.7, "speaker": "Bruno"}],
            )
            aligner.align.assert_called_once()


if __name__ == "__main__":
    unittest.main()
