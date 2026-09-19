import time
from typing import Dict, Optional


class SignalStateMachine:
    """
    Per-symbol Signal State Machine.

    States:
    - NEUTRAL
    - LONG_SIGNALED
    - SHORT_SIGNALED

    Rules:
    - NEUTRAL -> OBI > 0.7 for 3 consecutive updates (and >= 5s cooldown since last signal) -> emit 1 LONG -> LONG_SIGNALED
    - LONG_SIGNALED -> wait OBI < 0.5 -> NEUTRAL
    - NEUTRAL -> OBI < -0.7 for 3 consecutive updates (and >= 5s cooldown since last signal) -> emit 1 SHORT -> SHORT_SIGNALED
    - SHORT_SIGNALED -> wait OBI > -0.5 -> NEUTRAL
    """

    STATE_NEUTRAL = "NEUTRAL"
    STATE_LONG_SIGNALED = "LONG_SIGNALED"
    STATE_SHORT_SIGNALED = "SHORT_SIGNALED"

    def __init__(self, symbol: str, cooldown_seconds: float = 5.0, consecutive_required: int = 3):
        self.symbol = symbol.upper()
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_required = consecutive_required

        self.state = self.STATE_NEUTRAL
        self.last_obi: float = 0.0
        self.last_signal_time: Optional[float] = None
        self.last_signal_type: Optional[str] = None
        self.long_counter: int = 0
        self.short_counter: int = 0

    def update(self, obi: float, current_time: Optional[float] = None) -> Optional[Dict]:
        """
        Processes a new OBI update for this symbol.
        Returns a dict representing emitted signal if a signal is triggered, or None otherwise.
        """
        if current_time is None:
            current_time = time.time()

        self.last_obi = float(obi)
        emitted_signal = None

        if self.state == self.STATE_NEUTRAL:
            if self.last_obi > 0.7:
                self.long_counter += 1
                self.short_counter = 0
            elif self.last_obi < -0.7:
                self.short_counter += 1
                self.long_counter = 0
            else:
                self.long_counter = 0
                self.short_counter = 0

            # Check for LONG trigger condition
            if self.long_counter >= self.consecutive_required:
                cooldown_passed = (
                    self.last_signal_time is None
                    or (current_time - self.last_signal_time) >= self.cooldown_seconds
                )
                if cooldown_passed:
                    self.state = self.STATE_LONG_SIGNALED
                    self.last_signal_time = current_time
                    self.last_signal_type = "BUY"
                    emitted_signal = {
                        "symbol": self.symbol,
                        "signal": "BUY",
                        "obi": self.last_obi,
                        "timestamp": current_time,
                        "state": self.state
                    }

            # Check for SHORT trigger condition
            elif self.short_counter >= self.consecutive_required:
                cooldown_passed = (
                    self.last_signal_time is None
                    or (current_time - self.last_signal_time) >= self.cooldown_seconds
                )
                if cooldown_passed:
                    self.state = self.STATE_SHORT_SIGNALED
                    self.last_signal_time = current_time
                    self.last_signal_type = "SELL"
                    emitted_signal = {
                        "symbol": self.symbol,
                        "signal": "SELL",
                        "obi": self.last_obi,
                        "timestamp": current_time,
                        "state": self.state
                    }

        elif self.state == self.STATE_LONG_SIGNALED:
            self.long_counter = 0
            self.short_counter = 0
            if self.last_obi < 0.5:
                self.state = self.STATE_NEUTRAL

        elif self.state == self.STATE_SHORT_SIGNALED:
            self.long_counter = 0
            self.short_counter = 0
            if self.last_obi > -0.5:
                self.state = self.STATE_NEUTRAL

        return emitted_signal

    def get_info(self) -> Dict:
        return {
            "symbol": self.symbol,
            "state": self.state,
            "last_obi": self.last_obi,
            "last_signal_time": self.last_signal_time,
            "last_signal_type": self.last_signal_type,
        }


class SignalEngine:
    """
    Registry and coordinator for per-symbol signal state machines.
    """

    def __init__(self, cooldown_seconds: float = 5.0, consecutive_required: int = 3):
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_required = consecutive_required
        self.machines: Dict[str, SignalStateMachine] = {}

    def get_machine(self, symbol: str) -> SignalStateMachine:
        symbol = symbol.upper()
        if symbol not in self.machines:
            self.machines[symbol] = SignalStateMachine(
                symbol,
                cooldown_seconds=self.cooldown_seconds,
                consecutive_required=self.consecutive_required
            )
        return self.machines[symbol]

    def process_obi_update(self, symbol: str, obi: float, current_time: Optional[float] = None) -> Optional[Dict]:
        machine = self.get_machine(symbol)
        return machine.update(obi, current_time=current_time)

    def get_symbol_status(self, symbol: str) -> Dict:
        machine = self.get_machine(symbol)
        return machine.get_info()
