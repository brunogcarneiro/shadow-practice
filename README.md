# Shadow Practice

Shadow Practice is a macOS desktop application for recording meetings, producing a
speaker-aware word-level transcript, dividing speech into repeatable sense groups,
and practicing those groups with synchronized audio.

> **Privacy:** recording laws vary. Obtain informed consent from every participant
> before recording or transcribing a conversation. Recordings, imported transcripts,
> and diagnostic logs may contain sensitive information and remain your responsibility.

## Supported setup

The officially supported configuration is Apple Silicon macOS with Python 3.10. The
application may work elsewhere, but Windows, Linux, Intel Macs, and other Python
versions are currently best-effort.

The main features have different dependencies:

| Feature | Requirement |
| --- | --- |
| Desktop UI and recording | Python 3.10, PortAudio, BlackHole 2ch |
| Normal transcription | `transcription` extra, FFmpeg, Hugging Face token |
| Imported-transcript alignment | `alignment` extra; no diarization token required |
| Sense-group generation | Ollama with `qwen2.5:7b-instruct` recommended |
| Professional rewrite | Optional OpenAI API key |
| Generated speech | Optional separate Qwen TTS service using Python 3.12 |

## 1. Install system prerequisites

Install [Homebrew](https://brew.sh/) first if it is not already available, then run:

```bash
brew install python@3.10 ffmpeg portaudio ollama
brew install --cask blackhole-2ch
```

Restart macOS after installing BlackHole. Start Ollama and download the configured
sense-group model:

```bash
ollama serve
```

Keep that terminal open. In another terminal, run:

```bash
ollama pull qwen2.5:7b-instruct
```

If the Ollama application is already running, only the `ollama pull` command is
needed. Without Ollama, processing still finishes, but each fallback sense group may
be much larger than intended.

## 2. Configure macOS audio

1. Open **Audio MIDI Setup**.
2. Create a **Multi-Output Device** containing your speakers or headphones and
   BlackHole 2ch, then select that device as the macOS audio output.
3. Create an **Aggregate Device** whose first two input channels are BlackHole and
   whose third input channel is your microphone.
4. Rename it `Aggregate Device`, or put its exact name in
   `SHADOW_PRACTICE_AUDIO_DEVICE` in `.env`.
5. Keep the physical microphone selected inside Google Meet, Zoom, or the other
   meeting application. Do not select the aggregate device there, because that can
   send meeting audio back to the participants.
6. Grant microphone access to Terminal or the Python executable under **System
   Settings → Privacy & Security → Microphone**.

Use headphones and make a short, consented test recording before a real meeting.
More detail is available in [the macOS setup guide](docs/macos-setup.md).

## 3. Clone and install the application

```bash
git clone https://github.com/brunogcarneiro/shadow-practice.git
cd shadow-practice
python3.10 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[transcription,alignment]'
cp .env.example .env
```

Using `venv` matches the local commands in this guide. If you prefer `.venv`, activate
that directory instead. Always run the application with this environment activated.

To install only the features you need:

```bash
# Normal Whisper transcription and pyannote diarization only
python -m pip install -e '.[transcription]'

# Imported transcript and forced alignment only
python -m pip install -e '.[alignment]'
```

## 4. Configure Hugging Face access

Normal transcription uses the gated
[`pyannote/speaker-diarization-3.0`](https://huggingface.co/pyannote/speaker-diarization-3.0)
model. Sign in to Hugging Face, accept the model's access conditions, create a read
token, and add it to `.env`:

```env
HUGGINGFACE_TOKEN=your_token_here
```

This token is required for **normal transcription**. It is not needed when importing
an existing transcript for forced alignment. Never commit or paste a real token into
an issue, log, screenshot, or chat.

## 5. Review `.env`

The application loads `.env` automatically. Variables already exported by the shell
take precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SHADOW_PRACTICE_RECORDINGS_DIR` | `recordings` | Private audio and processed data |
| `SHADOW_PRACTICE_LOG_DIR` | `logs` | Timestamped diagnostic logs |
| `SHADOW_PRACTICE_AUDIO_DEVICE` | `Aggregate Device` | Exact aggregate input name |
| `SHADOW_PRACTICE_DEBUG` | `false` | Local debug switch |
| `HUGGINGFACE_TOKEN` | empty | Required by normal speaker diarization |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/generate` | Ollama generation endpoint |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Sense-group model |
| `OPENAI_API_KEY` | empty | Optional professional rewrite feature |
| `OPENAI_RESPONSES_URL` | OpenAI Responses API | Rewrite endpoint |
| `OPENAI_REWRITE_MODEL` | `gpt-5.4-mini` | Rewrite model |
| `QWEN_TTS_SERVICE_URL` | `http://127.0.0.1:8011` | Optional local TTS service |

The additional `QWEN_TTS_MODEL`, `QWEN_TTS_DEVICE`, and `QWEN_TTS_CACHE_DIR`
variables are read by the separate TTS process.

## 6. Verify the installation

With the virtual environment active, check the optional processing imports:

```bash
python -c "import whisper; from pyannote.audio import Pipeline; print('transcription ready')"
python -c "from qwen_asr import Qwen3ForcedAligner; print('alignment ready')"
ollama list
```

The first normal transcription downloads the configured Whisper and pyannote model
weights. The first forced-alignment run downloads
`Qwen/Qwen3-ForcedAligner-0.6B`. These downloads can take time and require internet
access; later runs use the local Hugging Face/model caches.

## 7. Run Shadow Practice

Activate the environment whenever opening a new terminal:

```bash
cd shadow-practice
source venv/bin/activate
shadow-practice
```

From the repository checkout, this compatibility launcher opens the same interface:

```bash
python shadow_practice.py
```

## Recording and processing workflow

1. Click **Start**, then **Pause**, **Resume**, or **Stop** as needed.
2. After stopping, locate the `.wav` in the recording list.
3. Click **Processar** and choose one of the two modes below.
4. Follow progress in the row or click **Detalhes** for structured logs. Use
   **Interromper** to cancel the processing subprocess.
5. Select a completed recording and click **Praticar gravação selecionada**.

### Normal audio transcription

Choose **Transcrever o áudio normalmente**. This runs English Whisper transcription,
word timestamps, pyannote speaker diarization, and sense-group generation. It requires
the `transcription` extra and `HUGGINGFACE_TOKEN`.

### Import a transcript and align it

Choose **Importar transcrição e alinhar ao áudio**, then select a UTF-8 text file. This
skips Whisper and pyannote, aligns the supplied words to the audio with Qwen, and then
generates sense groups.

For audio longer than five minutes, the transcript must contain timestamps so it can
be split into model-sized windows. Supported examples include:

```text
Speaker Name 00:01:23 spoken text
```

and Gemini/Google Meet exports such as:

```text
00:01:23

Speaker Name: spoken text
Another Speaker: another utterance
```

Gemini files are normalized automatically in memory: speaker labels are removed from
the text passed to the aligner and then restored on the aligned words. The imported
source file is never modified.

## Reprocessing or deleting a recording

Each row displays audio duration and size. Click **Excluir…** and choose either:

- Remove only generated `.words.json` and `.speaks.json` artifacts. The `.wav` remains
  and **Processar** becomes available again.
- Remove the generated artifacts and the source `.wav` permanently.

Imported `.txt` files are not deleted. Both choices require confirmation.

## Diagnostic logs

Every application start creates a separate file under `logs/`, for example:

```text
logs/shadow-practice-20260904-170756-847157.log
```

The log captures processing errors, tracebacks, unexpected subprocess output,
recording failures, and uncaught UI/thread exceptions. Override the directory with
`SHADOW_PRACTICE_LOG_DIR`. Logs can contain local filenames and error details; share
them carefully. `logs/`, `recordings/`, `.env`, caches, and model artifacts are
excluded from Git.

## Optional OpenAI rewrite

The **Reescreva** feature sends the selected text to the configured OpenAI Responses
API. Set `OPENAI_API_KEY` in `.env` to enable it. Recording, transcription, alignment,
playback, and manual practice do not require an OpenAI key.

## Optional Qwen TTS

Qwen TTS must run in a separate Python 3.12 environment because its dependency stack
differs from the Python 3.10 desktop application. From the repository root, run:

```bash
brew install python@3.12
python3.12 -m venv qwen-tts-venv
source qwen-tts-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -U qwen-tts
python -m pip install --no-deps -e .
shadow-practice-tts --host 127.0.0.1 --port 8011
```

Keep that terminal open. The first start downloads the configured Qwen TTS weights.
In another terminal, verify the local service:

```bash
curl http://127.0.0.1:8011/health
```

Then start the desktop app from its Python 3.10 `venv`, not from `qwen-tts-venv`.
The service defaults to Apple MPS and the Aiden English voice. Change its model,
device, cache directory, or URL with the `QWEN_TTS_*` variables in `.env`. See the
[Qwen TTS setup guide](docs/tts.md) for the short reference.

## Updating an existing checkout

```bash
git pull --ff-only
source venv/bin/activate
python -m pip install -e '.[transcription,alignment]'
```

Restart the application after updating code or dependencies.

## Development checks

```bash
source venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
pytest
python -m build
```

Tests do not download models or make real model/API calls. GitHub Actions runs lint,
tests, coverage, build, wheel installation, and import validation on macOS with Python
3.10.

## Troubleshooting

- **`No module named qwen_asr`:** activate the application environment and run
  `python -m pip install -e '.[alignment]'`.
- **`HUGGINGFACE_TOKEN is required`:** add the token to `.env`, restart the app, and
  confirm that you accepted the pyannote model conditions.
- **Audio device not found:** use the exact Audio MIDI Setup name in
  `SHADOW_PRACTICE_AUDIO_DEVICE`.
- **No audio or wrong channels:** put BlackHole first (channels 1–2) and the microphone
  third in the aggregate device.
- **Ollama unavailable:** start `ollama serve`, run
  `ollama pull qwen2.5:7b-instruct`, and verify `OLLAMA_URL`.
- **wxPython installation fails:** confirm that Terminal, Homebrew, and Python are all
  running arm64, install current Xcode Command Line Tools, then recreate the venv.
- **Processing fails:** open the newest file in `logs/` and inspect the final traceback.

See the longer [troubleshooting guide](docs/troubleshooting.md) if needed.

## Architecture and file formats

Code lives under `src/shadow_practice`: `domain` contains pure rules,
`application` orchestrates use cases, `infrastructure` integrates audio, models, and
storage, and `presentation/wx` contains the GUI. See the
[architecture guide](docs/architecture.md) and [JSON schemas](docs/schemas.md).
Existing `.words.json` and `.speaks.json` files remain compatible.

## Licensing

The MIT license covers only this project's code. Whisper, pyannote, Qwen, Ollama
models, and their weights remain subject to their respective licenses and access
terms. See [contributing](CONTRIBUTING.md), the [code of conduct](CODE_OF_CONDUCT.md),
and the [security policy](SECURITY.md).
