import unittest

from shadow_practice.application.playback_controller import PlaybackController


class PlaybackControllerTests(unittest.TestCase):
    def test_start_seek_and_pause_are_ui_independent(self):
        controller = PlaybackController(10.0)

        self.assertTrue(controller.start(3.0, 8.0).is_playing)
        self.assertEqual(controller.seek_relative(10.0).current_time, 8.0)
        self.assertFalse(controller.pause().is_playing)

    def test_advance_loops_when_a_loop_range_is_configured(self):
        controller = PlaybackController(10.0)
        controller.start(2.0, 4.0, loop_range=(2.0, 4.0))

        self.assertEqual(controller.advance_to(4.0).current_time, 2.0)
        self.assertTrue(controller.state.is_playing)


if __name__ == "__main__":
    unittest.main()
