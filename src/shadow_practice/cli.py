"""Installed command-line entrypoint."""

from __future__ import annotations

import wx

from .presentation.wx.launcher import ShadowPracticeFrame


def main() -> None:
    app = wx.App(False)
    frame = ShadowPracticeFrame()
    frame.Show()
    app.MainLoop()
