class CircuitBreaker:
    _paused: bool = False

    @classmethod
    def should_pause(cls) -> bool:
        return cls._paused

    @classmethod
    def set_paused(cls, paused: bool):
        cls._paused = paused
