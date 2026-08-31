# Qwen TTS setup

Create an isolated Python 3.12 environment. Install `qwen-tts`, `torch`, and
`soundfile`, then install this project without its desktop dependencies if needed.
Set `QWEN_TTS_MODEL`, `QWEN_TTS_DEVICE`, and `QWEN_TTS_CACHE_DIR` as desired and run:

```bash
shadow-practice-tts --host 127.0.0.1 --port 8011
```

Keep the service on loopback. Qwen model weights are not covered by this project's MIT
license; review their license before downloading or distributing them.
