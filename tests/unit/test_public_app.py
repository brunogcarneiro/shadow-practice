import io
import json
import logging
import os
import runpy
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from shadow_practice.application.processing_worker import emit
from shadow_practice.config import get_settings
from shadow_practice.infrastructure.application_logging import configure_application_logging
from shadow_practice.infrastructure.forced_alignment import (
    _repair_alignment_times,
    _safe_alignment_times,
    align_transcript_file,
    infer_timeline_offset,
    parse_timestamped_transcript,
)
from shadow_practice.infrastructure.openai_transcription import (
    transcribe_recording_openai,
)
from shadow_practice.infrastructure.transcript_formats import parse_imported_transcript
from shadow_practice.presentation.wx.launcher import (
    ShadowPracticeFrame,
    audio_file_details,
    delete_recording_data,
    is_processed_recording,
    list_audio_recordings,
    processing_artifacts,
)


class PublicAppTests(unittest.TestCase):
    def test_openai_whisper_transcription_keeps_word_timestamps(self):
        class FakeAudio:
            def set_channels(self, _channels):
                return self

            def set_frame_rate(self, _rate):
                return self

            def __len__(self):
                return 1_000

            def __getitem__(self, _key):
                return self

            def export(self, target, format):
                self.export_format = format
                target.write(b"flac")

        response = Mock(ok=True)
        response.json.return_value = {
            "words": [{"word": " hello", "start": 0.2, "end": 0.7}]
        }
        settings = types.SimpleNamespace(
            openai_api_key="test-key",
            openai_transcriptions_url="https://openai.test/transcriptions",
        )

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            audio.touch()
            with (
                patch(
                    "shadow_practice.infrastructure.openai_transcription.get_settings",
                    return_value=settings,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.AudioSegment.from_file",
                    return_value=FakeAudio(),
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.requests.post",
                    return_value=response,
                ) as post,
                patch(
                    "shadow_practice.infrastructure.openai_transcription.assign_speakers",
                    side_effect=lambda _path, words, _report: [
                        {**word, "speaker": "SPEAKER_00"} for word in words
                    ],
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.validate_speaker_diarization"
                ),
            ):
                output = transcribe_recording_openai(audio)

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                [
                    {
                        "word": "hello",
                        "start": 0.2,
                        "end": 0.7,
                        "speaker": "SPEAKER_00",
                    }
                ],
            )
            request = post.call_args.kwargs
            self.assertIn(("timestamp_granularities[]", "word"), request["data"])
            self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")

    def test_openai_whisper_retries_tls_failure(self):
        class FakeAudio:
            def set_channels(self, _channels):
                return self

            def set_frame_rate(self, _rate):
                return self

            def __len__(self):
                return 1_000

            def __getitem__(self, _key):
                return self

            def export(self, target, format):
                target.write(b"flac")

        response = Mock(ok=True)
        response.json.return_value = {
            "words": [{"word": "hello", "start": 0.2, "end": 0.7}]
        }
        settings = types.SimpleNamespace(
            openai_api_key="test-key",
            openai_transcriptions_url="https://openai.test/transcriptions",
        )
        events = []

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            audio.touch()
            with (
                patch(
                    "shadow_practice.infrastructure.openai_transcription.get_settings",
                    return_value=settings,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.AudioSegment.from_file",
                    return_value=FakeAudio(),
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.requests.post",
                    side_effect=[requests.exceptions.SSLError("temporary TLS error"), response],
                ) as post,
                patch("shadow_practice.infrastructure.openai_transcription.time.sleep") as sleep,
                patch(
                    "shadow_practice.infrastructure.openai_transcription.assign_speakers",
                    side_effect=lambda _path, words, _report: words,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.validate_speaker_diarization"
                ),
            ):
                transcribe_recording_openai(
                    audio,
                    progress_callback=lambda percent, message, data: events.append(
                        (percent, message, data)
                    ),
                )

            self.assertEqual(post.call_count, 2)
            sleep.assert_called_once()
            self.assertTrue(any("nova tentativa" in event[1] for event in events))
            self.assertTrue(any(event[2].get("attempt") == 2 for event in events))

    def test_openai_whisper_resumes_from_completed_chunk_checkpoint(self):
        class FakeAudio:
            def set_channels(self, _channels):
                return self

            def set_frame_rate(self, _rate):
                return self

            def __len__(self):
                return 600_000

            def __getitem__(self, _key):
                return self

            def export(self, target, format):
                target.write(b"flac")

        first = Mock(ok=True)
        first.json.return_value = {
            "words": [{"word": "first", "start": 0.0, "end": 0.5}]
        }
        second = Mock(ok=True)
        second.json.return_value = {
            "words": [{"word": "second", "start": 0.0, "end": 0.5}]
        }
        settings = types.SimpleNamespace(
            openai_api_key="test-key",
            openai_transcriptions_url="https://openai.test/transcriptions",
        )

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            audio.touch()
            common_patches = (
                patch(
                    "shadow_practice.infrastructure.openai_transcription.get_settings",
                    return_value=settings,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.AudioSegment.from_file",
                    return_value=FakeAudio(),
                ),
                patch("shadow_practice.infrastructure.openai_transcription.time.sleep"),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.assign_speakers",
                    side_effect=lambda _path, words, _report: words,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.validate_speaker_diarization"
                ),
            )
            with common_patches[0], common_patches[1], common_patches[2], common_patches[3], common_patches[4]:
                with patch(
                    "shadow_practice.infrastructure.openai_transcription.requests.post",
                    side_effect=[
                        first,
                        requests.exceptions.SSLError("TLS 1"),
                        requests.exceptions.SSLError("TLS 2"),
                        requests.exceptions.SSLError("TLS 3"),
                        requests.exceptions.SSLError("TLS 4"),
                    ],
                ):
                    with self.assertRaisesRegex(RuntimeError, "after 4 attempts"):
                        transcribe_recording_openai(audio)

            events = []
            with (
                patch(
                    "shadow_practice.infrastructure.openai_transcription.get_settings",
                    return_value=settings,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.AudioSegment.from_file",
                    return_value=FakeAudio(),
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.requests.post",
                    return_value=second,
                ) as resumed_post,
                patch(
                    "shadow_practice.infrastructure.openai_transcription.assign_speakers",
                    side_effect=lambda _path, words, _report: words,
                ),
                patch(
                    "shadow_practice.infrastructure.openai_transcription.validate_speaker_diarization"
                ),
            ):
                output = transcribe_recording_openai(
                    audio,
                    progress_callback=lambda percent, message, data: events.append(
                        (percent, message, data)
                    ),
                )

            self.assertEqual(resumed_post.call_count, 1)
            words = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([word["word"] for word in words], ["first", "second"])
            self.assertEqual(words[1]["start"], 300.0)
            self.assertTrue(any(event[2].get("resumed") for event in events))

    def test_processing_events_serialize_numpy_scalars(self):
        import numpy as np

        output = io.StringIO()
        with patch("sys.stdout", output):
            emit(73, "transcription", {"completed": np.int64(4)}, "Working")

        event = json.loads(output.getvalue())
        self.assertEqual(event["percent"], 73)
        self.assertEqual(event["data"]["completed"], 4)

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
            checkpoint = audio.with_suffix(".openai-transcription.checkpoint.json")
            unrelated = audio.with_suffix(".txt")
            for path in (audio, words, speaks, checkpoint, unrelated):
                path.touch()
            words.write_text('[{"displayed": false}]', encoding="utf-8")

            self.assertTrue(is_processed_recording(audio))
            self.assertEqual(processing_artifacts(audio), [words, speaks, checkpoint])
            self.assertEqual(delete_recording_data(audio), [words, speaks, checkpoint])
            self.assertFalse(is_processed_recording(audio))
            self.assertTrue(audio.exists())
            self.assertTrue(unrelated.exists())

            words.touch()
            self.assertEqual(delete_recording_data(audio, include_audio=True), [words, audio])
            self.assertFalse(audio.exists())
            self.assertTrue(unrelated.exists())

    def test_audio_recordings_are_listed_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            recordings = Path(directory)
            lower = recordings / "older.wav"
            upper = recordings / "newer.WAV"
            ignored = recordings / "notes.txt"
            for path in (lower, upper, ignored):
                path.touch()

            self.assertEqual(list_audio_recordings(recordings), [lower, upper])

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

    def test_ai_course_transcript_uses_isolated_course_parser(self):
        parsed = parse_imported_transcript(
            "[00:00]\nIntroduction to AI.\n\nMore context.\n"
            "[03:00]\nSymbolic reasoning begins here.\n"
            "[06:00]\nMachine learning follows."
        )

        self.assertEqual(parsed.format_name, "ai-course")
        self.assertEqual([block.start for block in parsed.blocks], [0, 180, 360])
        self.assertEqual(parsed.blocks[0].text, "Introduction to AI. More context.")
        self.assertEqual(
            {block.speaker for block in parsed.blocks}, {"COURSE_INSTRUCTOR"}
        )

    def test_meeting_and_recording_filenames_produce_timeline_offset(self):
        offset = infer_timeline_offset(
            Path("2026-09-03_12-02-23.wav"),
            Path("OHS - 2026_09_03 17_00 CEST - Notes by Gemini.txt"),
            local_utc_offset=timezone(timedelta(hours=-3)).utcoffset(None),
        )
        self.assertEqual(offset, 143)

    def test_invalid_forced_alignment_times_are_distributed_across_block(self):
        items = [
            types.SimpleNamespace(text="Hello", start_time=0.0, end_time=0.0),
            types.SimpleNamespace(text="everyone", start_time=0.0, end_time=0.0),
        ]

        times = _safe_alignment_times(items, 3.0)

        self.assertEqual(times[0][0], 0.0)
        self.assertEqual(times[-1][1], 3.0)
        self.assertGreater(times[0][1], times[0][0])
        self.assertGreater(times[1][0], times[0][0])

    def test_forced_alignment_repairs_only_invalid_words_between_model_anchors(self):
        items = [
            types.SimpleNamespace(text="First", start_time=0.2, end_time=0.7),
            types.SimpleNamespace(text="bad", start_time=0.0, end_time=0.0),
            types.SimpleNamespace(text="timing", start_time=0.0, end_time=0.0),
            types.SimpleNamespace(text="Last", start_time=2.5, end_time=2.9),
        ]

        times, methods = _repair_alignment_times(items, 3.0)

        self.assertEqual(times[0], (0.2, 0.7))
        self.assertEqual(times[3], (2.5, 2.9))
        self.assertEqual(methods, ["model", "interpolated", "interpolated", "model"])
        self.assertEqual(times[1][0], 0.7)
        self.assertEqual(times[2][1], 2.5)
        self.assertGreater(times[1][1], times[1][0])
        self.assertGreater(times[2][1], times[2][0])

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
                [
                    {
                        "word": "Hello",
                        "start": 0.2,
                        "end": 0.7,
                        "speaker": "Bruno",
                        "alignment": {"method": "model", "confidence": "high"},
                    }
                ],
            )
            aligner.align.assert_called_once()


if __name__ == "__main__":
    unittest.main()
