# Shadow Practice

Shadow Practice is a macOS desktop application for recording a meeting, producing a
speaker-aware word-level transcript, dividing speech into repeatable sense groups,
and practicing those groups with synchronized audio.

> **Privacy:** recording laws vary. Obtain informed consent from every participant
> before recording or transcribing a conversation. Recordings and transcripts may
> contain sensitive personal or business information and remain your responsibility.

## Supported platform

The initial supported configuration is Apple Silicon macOS with Python 3.10. The UI
uses wxPython and audio capture uses a three-channel aggregate input. Model execution
is resource intensive; other platforms are currently best-effort.

## Install

Install Python 3.10, FFmpeg, PortAudio, and Ollama (for sense grouping), then:

```bash
git clone https://github.com/brunogcarneiro/shadow-practice.git
cd shadow-practice
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[transcription]'
cp .env.example .env
```

The application loads `.env` automatically; variables already exported by the shell
take precedence. Set `HUGGINGFACE_TOKEN` to a token that can access the gated pyannote
diarization model. See [macOS setup](docs/macos-setup.md).

## Quick start

```bash
shadow-practice
# From a source checkout, this opens the same interface:
python shadow_practice.py
```

Recordings are written to `recordings/` by default. Select a recording, process it,
then open it for practice. Existing `.words.json` and `.speaks.json` files remain
compatible; their formats are described in [schemas](docs/schemas.md).

When processing, choose either full audio transcription or import a text transcript
for forced alignment. Enable the latter with
`python -m pip install -e '.[alignment]'`. Long imported transcripts must contain
timestamps (for example `Speaker Name 00:01:23 spoken text`) so they can be divided
into the aligner's five-minute input windows. Gemini exports with a timestamp on its
own line followed by `Speaker Name: spoken text` lines are normalized automatically;
the selected source file is never modified.

## Optional local Qwen TTS

Qwen TTS must run in a separate Python 3.12 environment because its dependency stack
differs from the Python 3.10 desktop app. See [TTS setup](docs/tts.md), then run
`shadow-practice-tts` from that environment.

## Architecture

Code lives under `src/shadow_practice`: `domain` contains pure rules,
`application` orchestrates use cases, `infrastructure` integrates audio, models, and
JSON storage, and `presentation/wx` contains the GUI. More detail is in
[the architecture guide](docs/architecture.md).

## Limitations and licensing

Transcription, diarization, Ollama, OpenAI rewriting, and Qwen TTS require separate
models or services. Tests never contact them. The MIT license covers this project's
code only; Whisper, pyannote, Qwen, and other model weights retain their own licenses
and usage terms. There is currently no Windows/Linux support guarantee.

See [troubleshooting](docs/troubleshooting.md), [contributing](CONTRIBUTING.md), and
the [security policy](SECURITY.md).
