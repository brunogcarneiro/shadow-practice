"""Minimal import contract for the presentation layer."""

import unittest


class PresentationImportTests(unittest.TestCase):
    def test_main_frame_imports_when_wx_is_available(self):
        try:
            import wx  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("wxPython não está instalado neste ambiente.")

        from shadow_practice.presentation.wx.main_frame import MainFrame, TranscriptPlayer

        self.assertIs(MainFrame, TranscriptPlayer)

    def test_behavior_adapter_preserves_static_methods(self):
        try:
            import wx  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("wxPython não está instalado neste ambiente.")

        from shadow_practice.presentation.wx.main_frame import _BehaviorAdapter
        from shadow_practice.presentation.wx.speaks_tab import SpeaksBehavior

        adapter = _BehaviorAdapter(object(), SpeaksBehavior)
        path = adapter.bind("get_speaks_file_path")("sample.words.json")
        self.assertEqual(path, "sample.speaks.json")
