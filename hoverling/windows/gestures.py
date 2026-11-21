"""Recognize selection gestures from pairs of primary-button events."""


class SelectionGesture:
    def __init__(self):
        self.reset()

    def reset(self):
        self.press = None
        self.last_click = None

    def down(self, window, point, timestamp):
        self.press = (window, point, timestamp) if window else None
        if not window:
            self.last_click = None

    def up(self, window, point, drag_distance, double_time, double_size):
        press = self.press
        previous = self.last_click
        self.reset()
        if not press or press[0] != window:
            return False
        _, start, timestamp = press
        if max(abs(a - b) for a, b in zip(start, point)) >= drag_distance:
            return True
        if previous and previous[0] == window:
            _, first, first_time = previous
            # Windows mouse event timestamps wrap at 2**32 milliseconds.
            elapsed = (timestamp - first_time) & 0xffffffff
            if elapsed <= double_time and all(
                2 * abs(a - b) <= span for a, b, span in zip(start, first, double_size)
            ):
                return True
        self.last_click = press
        return False
