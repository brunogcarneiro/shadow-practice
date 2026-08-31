"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    recordings_dir: Path
    audio_device: str
    huggingface_token: str | None
    ollama_url: str
    ollama_model: str
    openai_api_key: str | None
    openai_responses_url: str
    openai_rewrite_model: str
    qwen_tts_service_url: str
    debug: bool


def get_settings() -> Settings:
    """Read settings at call time so tests and shells can change the environment."""
    return Settings(
        recordings_dir=Path(os.getenv("SHADOW_PRACTICE_RECORDINGS_DIR", "recordings")).expanduser(),
        audio_device=os.getenv("SHADOW_PRACTICE_AUDIO_DEVICE", "Aggregate Device"),
        huggingface_token=os.getenv("HUGGINGFACE_TOKEN"),
        ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_responses_url=os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses"),
        openai_rewrite_model=os.getenv("OPENAI_REWRITE_MODEL", "gpt-5.4-mini"),
        qwen_tts_service_url=os.getenv("QWEN_TTS_SERVICE_URL", "http://127.0.0.1:8011"),
        debug=os.getenv("SHADOW_PRACTICE_DEBUG", "").lower() in {"1", "true", "yes"},
    )
