import time

class CircuitBreaker:
    """Circuit Breaker to pause trading activities when risk limits are breached."""

    def __init__(self):
        self.paused = False
        self.paused_until = 0.0

    def pause(self, seconds: int = 300) -> None:
        self.paused = True
        self.paused_until = time.time() + float(seconds)

    def is_paused(self) -> bool:
        if self.paused:
            if time.time() >= self.paused_until:
                self.paused = False
                self.paused_until = 0.0
                return False
            return True
        return False

    def reset(self) -> None:
        self.paused = False
        self.paused_until = 0.0

    def get_status(self) -> dict:
        active_paused = self.is_paused()
        remaining = max(0.0, self.paused_until - time.time()) if active_paused else 0.0
        return {
            "paused": active_paused,
            "paused_until": self.paused_until if active_paused else None,
            "seconds_remaining": round(remaining, 1)
        }
