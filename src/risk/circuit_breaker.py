import time
import collections
import statistics
from typing import Optional

class CircuitBreaker:
    def __init__(self, spread_threshold: float = 5.0, std_multiplier: float = 3.0, pause_duration: float = 5.0):
        self.spread_threshold = spread_threshold
        self.std_multiplier = std_multiplier
        self.pause_duration = pause_duration
        self.timestamps = collections.deque(maxlen=100)
        self.frequencies = collections.deque(maxlen=100)
        self.paused_until: float = 0.0

    def should_pause(self, current_time: Optional[float] = None) -> bool:
        if current_time is None:
            current_time = time.time()
        return current_time < self.paused_until

    def process_tick(self, bid1: float, ask1: float, timestamp: Optional[float] = None) -> bool:
        if timestamp is None:
            timestamp = time.time()

        spread = ask1 - bid1
        if spread > self.spread_threshold:
            self.paused_until = max(self.paused_until, timestamp + self.pause_duration)

        if self.timestamps:
            dt = timestamp - self.timestamps[-1]
            if dt > 0:
                curr_freq = 1.0 / dt
                if len(self.frequencies) >= 2:
                    mean_f = statistics.mean(self.frequencies)
                    std_f = statistics.stdev(self.frequencies)
                    if curr_freq > mean_f + self.std_multiplier * std_f:
                        self.paused_until = max(self.paused_until, timestamp + self.pause_duration)
                self.frequencies.append(curr_freq)

        self.timestamps.append(timestamp)
        return self.should_pause(timestamp)
