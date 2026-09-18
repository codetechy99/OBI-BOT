import datetime
import uuid
from typing import Dict, List, Optional, Any

class ExecutionHandler:
    def __init__(self, ledger, default_user_id: str = "default_user", order_size: float = 100.0, obi_threshold: float = 0.5):
        self.ledger = ledger
        self.default_user_id = default_user_id
        self.order_size = order_size
        self.obi_threshold = obi_threshold

        self.active_order: Optional[Dict[str, Any]] = None
        self.trades: List[Dict[str, Any]] = []
        self.total_pnl: float = 0.0

    def on_signal(self, I: float, best_bid: float, best_ask: float, tick_size: float = 0.1, user_id: Optional[str] = None):
        user = user_id or self.default_user_id

        # If we currently have an active order, attempt simulated fill / exit condition
        if self.active_order is not None:
            order = self.active_order
            side = order["side"]
            price = order["price"]

            # Check for simulated fill
            filled = False
            if side == "BUY" and best_ask <= price:
                filled = True
            elif side == "SELL" and best_bid >= price:
                filled = True

            if filled:
                # Calculate PnL (simulated fixed return or price delta, e.g. 0.5% gain or loss based on signal)
                # Simple simulated trade PnL calculation:
                pnl = round(self.order_size * 0.005, 2)
                self.ledger.release(user, self.order_size)
                try:
                    self.ledger.apply_pnl(user, pnl)
                except ValueError:
                    pass

                self.total_pnl += pnl
                trade = {
                    "id": order["id"],
                    "side": side,
                    "price": price,
                    "amount": self.order_size,
                    "pnl": pnl,
                    "status": "FILLED",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                self.trades.insert(0, trade)
                self.active_order = None
            else:
                # Check for signal reversal to cancel order
                if (side == "BUY" and I < -0.2) or (side == "SELL" and I > 0.2):
                    self.ledger.release(user, self.order_size)
                    order["status"] = "CANCELLED"
                    self.active_order = None
            return

        # No active order -> check if OBI signal triggers a new order
        if I > self.obi_threshold: # Strong buy imbalance
            if self.ledger.reserve(user, self.order_size):
                order_price = best_bid
                self.active_order = {
                    "id": f"ord_{uuid.uuid4().hex[:8]}",
                    "side": "BUY",
                    "price": order_price,
                    "amount": self.order_size,
                    "status": "OPEN",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
        elif I < -self.obi_threshold: # Strong sell imbalance
            if self.ledger.reserve(user, self.order_size):
                order_price = best_ask
                self.active_order = {
                    "id": f"ord_{uuid.uuid4().hex[:8]}",
                    "side": "SELL",
                    "price": order_price,
                    "amount": self.order_size,
                    "status": "OPEN",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }

    def get_dashboard_data(self, user_id: str) -> dict:
        balance = self.ledger.get_balance(user_id)
        reserved = self.ledger.get_reserved_balance(user_id)
        available = self.ledger.get_available_balance(user_id)
        return {
            "user_id": user_id,
            "balance": balance,
            "reserved": reserved,
            "available": available,
            "active_order": self.active_order,
            "trades": self.trades,
            "pnl_total": self.total_pnl
        }
