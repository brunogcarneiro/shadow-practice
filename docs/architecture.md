# Architecture

The package follows a dependency-inward layout:

- `domain`: transcript, playback, waveform, and speaking-session rules with no GUI.
- `application`: controllers and sense-group/model task orchestration.
- `infrastructure`: JSON persistence, audio adapters, recording, transcription, and TTS.
- Local Whisper and OpenAI `whisper-1` are separate transcription adapters; both feed
  timestamped words into the shared local speaker-diarization component.
- `infrastructure/transcript_formats`: isolated adapters for Gemini/Google Meet and
  timestamped AI-course transcripts, normalized into shared transcript blocks.
- `presentation/wx`: the launcher, practice window, and wxPython controls.

`shadow_practice.cli:main` is the installed composition entry point. The root launcher
adds `src/` only for source-checkout compatibility and delegates to that same function.
Heavy transcription and TTS dependencies are imported lazily so basic imports and tests
do not initialize models or contact external services.
