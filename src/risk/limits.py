import os
import time
import logging
import datetime
from src.risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger("risk_manager")

class RiskManager:
    """Risk Management System for order controls and loss limits."""

    def __init__(
        self,
        max_daily_loss: float = 100000.0,
        max_position: float = 1.0,
        max_orders_per_min: int = 10,
        log_file: str = "data/risk.log"
    ):
        self.max_daily_loss = max_daily_loss
        self.max_position = max_position
        self.max_orders_per_min = max_orders_per_min
        self.log_file = log_file
        self.circuit_breaker = CircuitBreaker()
        self.order_timestamps = []

        # Ensure directory for log file exists
        os.makedirs(os.path.dirname(self.log_file) or ".", exist_ok=True)
        if not os.path.exists(self.log_file):
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] RiskManager initialized\n")

    def _log_risk(self, message: str) -> None:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log_entry = f"[{timestamp}] {message}\n"
        logger.warning(message)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except OSError as e:
            logger.error(f"Failed to write to risk log file: {e}")

    def record_order(self) -> None:
        self.order_timestamps.append(time.time())

    def check_can_trade(self, user_id: str, ledger, position: float = 0.0) -> bool:
        # 1. Circuit breaker check
        if self.circuit_breaker.is_paused():
            self._log_risk(f"Trade blocked for user '{user_id}': Circuit breaker is currently PAUSED")
            return False

        # 2. Daily loss check from ledger
        daily_pnl = ledger.get_pnl(user_id)
        if daily_pnl <= -self.max_daily_loss:
            msg = f"RISK BREACH: Daily loss limit exceeded for user '{user_id}' (PnL: {daily_pnl} UGX <= -{self.max_daily_loss} UGX)"
            self._log_risk(msg)
            self.circuit_breaker.pause(300)
            self._trigger_alert(f"⚠️ Circuit Breaker Triggered! {msg}")
            return False

        # 3. Position limit check
        if abs(position) > self.max_position:
            msg = f"RISK BREACH: Position limit exceeded ({abs(position)} BTC > {self.max_position} BTC)"
            self._log_risk(msg)
            self.circuit_breaker.pause(300)
            self._trigger_alert(f"⚠️ Circuit Breaker Triggered! {msg}")
            return False

        # 4. Rate limit check (orders per minute)
        now = time.time()
        self.order_timestamps = [t for t in self.order_timestamps if now - t <= 60.0]
        if len(self.order_timestamps) >= self.max_orders_per_min:
            msg = f"RISK BREACH: Rate limit exceeded ({len(self.order_timestamps)} orders/min >= {self.max_orders_per_min})"
            self._log_risk(msg)
            self.circuit_breaker.pause(300)
            self._trigger_alert(f"⚠️ Circuit Breaker Triggered! {msg}")
            return False

        return True

    def _trigger_alert(self, msg: str) -> None:
        try:
            from src.alerts.telegram import send_alert
            send_alert(msg)
        except Exception as e:
            logger.error(f"Failed to send alert from RiskManager: {e}")

    def get_status(self) -> dict:
        now = time.time()
        recent_orders = len([t for t in self.order_timestamps if now - t <= 60.0])
        return {
            "max_daily_loss": self.max_daily_loss,
            "max_position": self.max_position,
            "max_orders_per_min": self.max_orders_per_min,
            "orders_last_min": recent_orders,
            "circuit_breaker": self.circuit_breaker.get_status()
        }
