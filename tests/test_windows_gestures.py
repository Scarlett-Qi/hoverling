import unittest

from hoverling.windows.gestures import SelectionGesture


class WindowsGestureTests(unittest.TestCase):
    def setUp(self):
        self.gesture = SelectionGesture()

    def click(self, time, x=10, window=1):
        self.gesture.down(window, (x, 10), time)
        return self.gesture.up(window, (x, 10), 4, 400, (4, 4))

    def test_fast_double_click_reads_once(self):
        self.assertFalse(self.click(0))
        self.assertTrue(self.click(35, x=11))
        self.assertFalse(self.click(70))

    def test_clicks_must_be_close_in_time_space_and_window(self):
        self.assertFalse(self.click(0))
        self.assertFalse(self.click(401))
        self.assertFalse(self.click(450, x=15))
        self.assertFalse(self.click(480, x=15, window=2))

    def test_drag_still_reads_without_another_click(self):
        self.gesture.down(1, (10, 10), 100)
        self.assertTrue(self.gesture.up(1, (14, 10), 4, 400, (4, 4)))
        self.assertFalse(self.click(200))

    def test_own_window_and_reset_break_click_sequence(self):
        self.assertFalse(self.click(0))
        self.assertFalse(self.click(100, window=None))
        self.assertFalse(self.click(200))
        self.gesture.reset()
        self.assertFalse(self.click(250))
