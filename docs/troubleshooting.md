# Troubleshooting

- **Audio device not found:** verify the exact Audio MIDI Setup name or set
  `SHADOW_PRACTICE_AUDIO_DEVICE`.
- **No audio / wrong channels:** put BlackHole first (channels 1-2) and the microphone
  third in the aggregate device.
- **Diarization denied:** accept the pyannote model terms and export a valid
  `HUGGINGFACE_TOKEN`.
- **Ollama unavailable:** start Ollama, pull the configured model, and verify
  `OLLAMA_URL`. The app falls back to one group per chunk when grouping fails.
- **Qwen TTS unavailable:** start the isolated service and check `/health` at the URL in
  `QWEN_TTS_SERVICE_URL`.
- **wxPython install fails:** use Python 3.10 arm64 and current Xcode command-line tools.
