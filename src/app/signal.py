import uuid
import time
from typing import Optional, Dict, Literal
from collections import deque
from pydantic import BaseModel, Field

from src.app.obi import calculate_orderbook_metrics


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    timestamp: float
    obi: float
    bid_vol: float
    ask_vol: float
    mid_price: float
    spread: float
    side: Literal["LONG", "SHORT"]
    strength: float
    expires_at: float


class SignalEvaluator:
    """
    Evaluates market orderbook metrics against signal filters:
    1. Persistence filter (anti-spoof): OBI > 0.7 or < -0.7 for 3 consecutive updates in obi_buffer (maxlen=5).
    2. Spread filter: max allowed spread 0.1% (0.001).
    3. Volatility filter: price change > 2% (0.02) within 1 sec suppresses signals.
    """

    def __init__(self):
        self.obi_buffers: Dict[str, deque] = {}
        self.price_histories: Dict[str, deque] = {}

    def get_obi_buffer(self, symbol: str) -> deque:
        if symbol not in self.obi_buffers:
            self.obi_buffers[symbol] = deque(maxlen=5)
        return self.obi_buffers[symbol]

    def get_price_history(self, symbol: str) -> deque:
        if symbol not in self.price_histories:
            self.price_histories[symbol] = deque(maxlen=100)
        return self.price_histories[symbol]

    def evaluate(self, symbol: str, orderbook: dict, timestamp: Optional[float] = None) -> Optional[Signal]:
        now = timestamp if timestamp is not None else time.time()
        metrics = calculate_orderbook_metrics(orderbook)

        obi = metrics["obi"]
        bid_vol = metrics["bid_vol"]
        ask_vol = metrics["ask_vol"]
        mid_price = metrics["mid_price"]
        spread = metrics["spread"]

        # Append to buffers
        obi_buf = self.get_obi_buffer(symbol)
        obi_buf.append(obi)

        price_hist = self.get_price_history(symbol)
        if mid_price > 0:
            price_hist.append((now, mid_price))

        # Filter 1: Spread filter (> 0.1% spread -> no signal)
        if spread > 0.001:
            return None

        # Filter 2: Volatility filter (> 2% price change in 1 sec -> no signal)
        if mid_price > 0 and len(price_hist) > 1:
            recent_prices = [p for t, p in price_hist if (now - t) <= 1.0]
            if recent_prices:
                min_p = min(recent_prices)
                max_p = max(recent_prices)
                if min_p > 0 and ((max_p - min_p) / min_p > 0.02 or abs(mid_price - recent_prices[0]) / recent_prices[0] > 0.02):
                    return None

        # Filter 3: Persistence filter (anti-spoof: 3 consecutive updates > 0.7 or < -0.7)
        if len(obi_buf) < 3:
            return None

        last_3 = list(obi_buf)[-3:]
        if all(val > 0.7 for val in last_3):
            side = "LONG"
        elif all(val < -0.7 for val in last_3):
            side = "SHORT"
        else:
            return None

        # Note: Signal generation is purely a SIGNAL notification and NOT an auto-trade execution.
        signal = Signal(
            symbol=symbol,
            timestamp=now,
            obi=obi,
            bid_vol=bid_vol,
            ask_vol=ask_vol,
            mid_price=mid_price,
            spread=spread,
            side=side,
            strength=abs(obi),
            expires_at=now + 5.0
        )
        return signal
