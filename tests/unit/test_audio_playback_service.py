import unittest

from shadow_practice.infrastructure.audio import AudioPlaybackService


class FakePlayObject:
    def __init__(self):
        self.stopped = False

    def is_playing(self):
        return not self.stopped

    def stop(self):
        self.stopped = True


class FakeSegment:
    raw_data = b"audio"
    channels = 1
    sample_width = 2
    frame_rate = 16000

    def __getitem__(self, key):
        self.last_slice = key
        return self


class AudioPlaybackServiceTests(unittest.TestCase):
    def test_play_builds_segment_and_stops_previous_object(self):
        segment = FakeSegment()
        objects = []

        def play_buffer(*args):
            obj = FakePlayObject()
            objects.append((obj, args))
            return obj

        service = AudioPlaybackService(segment, play_buffer)
        first = service.play(1.25, 2.5)
        second = service.play(3.0)

        self.assertTrue(first.stopped)
        self.assertIs(service.play_obj, second)
        self.assertEqual(segment.last_slice, slice(3000, None))
        self.assertEqual(objects[0][1], (b"audio", 1, 2, 16000))

    def test_stop_is_idempotent(self):
        service = AudioPlaybackService(FakeSegment(), lambda *args: FakePlayObject())
        service.stop()
        service.stop()
        self.assertFalse(service.is_playing())


if __name__ == "__main__":
    unittest.main()
