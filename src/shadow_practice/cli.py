"""Installed command-line entrypoint."""

from __future__ import annotations

import wx

from .infrastructure.application_logging import configure_application_logging
from .presentation.wx.launcher import ShadowPracticeFrame


def main() -> None:
    configure_application_logging()
    app = wx.App(False)
    frame = ShadowPracticeFrame()
    frame.Show()
    app.MainLoop()
