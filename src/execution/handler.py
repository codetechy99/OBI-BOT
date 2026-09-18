import logging
from typing import Optional, Dict, Any
from src.alerts.telegram import send_alert

logger = logging.getLogger("execution_handler")

class ExecutionHandler:
    """Handles order execution, toxic cancels, and sends trade alerts."""

    def __init__(self, ledger=None):
        self.ledger = ledger

    def place_order(self, side: str, price: float, qty: float, user_id: str = "user1") -> Dict[str, Any]:
        order = {
            "status": "PLACED",
            "user_id": user_id,
            "side": side.upper(),
            "price": float(price),
            "qty": float(qty)
        }
        logger.info(f"Order placed: {order}")
        send_alert(f"📢 Order Placed: {order['side']} {order['qty']} BTC @ {order['price']}")
        return order

    def fill_order(self, side: str, price: float, qty: float, pnl: float = 0.0, user_id: str = "user1") -> Dict[str, Any]:
        balance_after = None
        if self.ledger:
            try:
                balance_after = self.ledger.record_trade(user_id=user_id, side=side, price=price, qty=qty, pnl=pnl)
            except Exception as e:
                logger.error(f"Failed to record trade in ledger: {e}")

        fill_info = {
            "status": "FILLED",
            "user_id": user_id,
            "side": side.upper(),
            "price": float(price),
            "qty": float(qty),
            "pnl": float(pnl),
            "balance_after": balance_after
        }
        logger.info(f"Order filled: {fill_info}")
        send_alert(f"✅ Order Filled: {fill_info['side']} {fill_info['qty']} BTC @ {fill_info['price']} (PnL: {pnl} UGX)")
        return fill_info

    def trigger_toxic_cancel(self, reason: str) -> Dict[str, Any]:
        logger.warning(f"Toxic cancel triggered: {reason}")
        send_alert(f"🚨 Toxic Cancel Triggered: {reason}")
        return {"status": "TOXIC_CANCEL", "reason": reason}

    def on_signal(self, signal: Dict[str, Any], user_id: str = "user1") -> Dict[str, Any]:
        """Process incoming trade signal."""
        side = signal.get("action", signal.get("side", "BUY"))
        price = float(signal.get("price", 0.0))
        qty = float(signal.get("qty", 1.0))
        pnl = float(signal.get("pnl", 0.0))

        # 1. Place order
        self.place_order(side=side, price=price, qty=qty, user_id=user_id)

        # 2. Check toxic cancel signal if present
        if signal.get("toxic_cancel"):
            return self.trigger_toxic_cancel(reason=signal.get("cancel_reason", "Toxic order flow detected"))

        # 3. Fill order
        return self.fill_order(side=side, price=price, qty=qty, pnl=pnl, user_id=user_id)
