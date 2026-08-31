"""Composition root for production adapters."""

from .application.transcript_controller import TranscriptController
from .infrastructure.audio import AudioPlaybackService
from .infrastructure.generative import GenerativeModelManager

__all__ = ["AudioPlaybackService", "GenerativeModelManager", "TranscriptController"]
