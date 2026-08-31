# Contributing

Use Python 3.10 on macOS. Create a virtual environment and install `.[dev]` (and
`.[transcription]` when working on that integration). Keep model/network calls mocked.

Before opening a pull request, run:

```bash
ruff check .
pytest
python -m build
```

Open an issue before a large behavioral or schema change. Do not submit recordings,
transcripts, credentials, model weights, or other people's personal information.
Contributions must follow the Code of Conduct and are licensed under MIT.
