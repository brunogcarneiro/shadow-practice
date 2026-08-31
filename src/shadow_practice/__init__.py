"""Transcript Player package."""

__all__ = ["TranscriptPlayer"]


def __getattr__(name: str):
    """Avoid importing wxPython when consumers only need domain modules."""
    if name == "TranscriptPlayer":
        from .presentation.wx.main_frame import TranscriptPlayer

        return TranscriptPlayer
    raise AttributeError(name)
