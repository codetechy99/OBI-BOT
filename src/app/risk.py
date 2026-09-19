"""
Risk Management Layer (Placeholder)
Performs pre-trade risk evaluation before paper/simulated execution.
"""

import time
from typing import Optional
from src.app.signal import Signal


class RiskManager:
    """
    Placeholder Risk Manager to enforce pre-trade checks:
    - Signal expiry check
    - Maximum position size limits
    - Max allowed spread check
    """

    def __init__(self, max_position_size: float = 1000.0, max_spread: float = 0.001):
        self.max_position_size = max_position_size
        self.max_spread = max_spread

    def check_risk(self, signal: Signal, requested_size: float = 1.0, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.time()

        # 1. Expiration check
        if signal.expires_at <= now:
            return False

        # 2. Position size check
        if requested_size <= 0 or requested_size > self.max_position_size:
            return False

        # 3. Spread check
        if signal.spread > self.max_spread:
            return False

        return True
