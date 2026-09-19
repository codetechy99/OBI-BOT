"""
Paper Execution & PnL Engine (Placeholder)
Simulates paper position management and mark-to-market PnL calculations.
"""

import uuid
import time
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

from src.app.signal import Signal


class PaperPosition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    size: float = 1.0
    opened_at: float
    closed_at: Optional[float] = None
    status: str = "OPEN"  # "OPEN" or "CLOSED"
    pnl: float = 0.0


class PaperExecutor:
    """
    Executes simulated paper trades based on signals and calculates PnL.
    """

    def __init__(self):
        self.positions: Dict[str, PaperPosition] = {}

    def execute_paper_trade(self, signal: Signal, size: float = 1.0, timestamp: Optional[float] = None) -> PaperPosition:
        now = timestamp if timestamp is not None else time.time()
        pos = PaperPosition(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.mid_price,
            size=size,
            opened_at=now,
            status="OPEN",
            pnl=0.0
        )
        self.positions[pos.id] = pos
        return pos

    def calculate_pnl(self, position: PaperPosition, current_price: float) -> float:
        if position.side == "LONG":
            return (current_price - position.entry_price) * position.size
        elif position.side == "SHORT":
            return (position.entry_price - current_price) * position.size
        return 0.0

    def close_position(self, position_id: str, exit_price: float, timestamp: Optional[float] = None) -> PaperPosition:
        if position_id not in self.positions:
            raise ValueError(f"Position {position_id} not found")

        pos = self.positions[position_id]
        if pos.status == "CLOSED":
            return pos

        now = timestamp if timestamp is not None else time.time()
        pos.pnl = self.calculate_pnl(pos, exit_price)
        pos.status = "CLOSED"
        pos.closed_at = now
        return pos

    def get_open_positions(self) -> List[PaperPosition]:
        return [pos for pos in self.positions.values() if pos.status == "OPEN"]

    def get_all_positions(self) -> List[PaperPosition]:
        return list(self.positions.values())
