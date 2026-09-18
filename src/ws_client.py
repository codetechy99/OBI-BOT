import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any

from src.risk.limits import RiskManager
from src.execution.handler import ExecutionHandler
from src.money.ledger import Ledger
from src.market_data.obi import calculate_obi_from_orderbook

logger = logging.getLogger("ws_client")

class WSClient:
    """Binance WebSocket client integrated with RiskManager and ExecutionHandler."""

    def __init__(
        self,
        ws_url: Optional[str] = None,
        risk_manager: Optional[RiskManager] = None,
        execution_handler: Optional[ExecutionHandler] = None,
        ledger: Optional[Ledger] = None
    ):
        self.ws_url = ws_url or os.getenv("BINANCE_WS", "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms")
        self.risk_manager = risk_manager or RiskManager()
        self.ledger = ledger or Ledger()
        self.execution_handler = execution_handler or ExecutionHandler(ledger=self.ledger)
        self.current_position = 0.0

    def process_signal(self, signal: Dict[str, Any], user_id: str = "user1") -> Optional[Dict[str, Any]]:
        """Checks RiskManager before delegating signal to ExecutionHandler."""
        logger.info(f"Processing signal for user '{user_id}': {signal}")

        # Check risk limits prior to execution
        can_trade = self.risk_manager.check_can_trade(
            user_id=user_id,
            ledger=self.ledger,
            position=self.current_position
        )

        if not can_trade:
            logger.warning(f"Trade blocked by RiskManager for user '{user_id}'. Signal dropped.")
            return None

        self.risk_manager.record_order()
        result = self.execution_handler.on_signal(signal, user_id=user_id)

        # Update position tracker if order filled
        if result and result.get("status") == "FILLED":
            qty = result.get("qty", 0.0)
            side = result.get("side", "BUY")
            if side == "BUY":
                self.current_position += qty
            else:
                self.current_position -= qty

        return result

    def process_orderbook_message(self, data: Dict[str, Any], user_id: str = "user1") -> Optional[Dict[str, Any]]:
        """Process incoming orderbook snapshot/update and generate OBI signal."""
        imbalance = calculate_obi_from_orderbook(data)
        logger.debug(f"Calculated OrderBook Imbalance: {imbalance}")

        # Basic OBI strategy signal trigger
        signal = None
        if imbalance > 0.6:
            signal = {"action": "BUY", "price": float(data.get("bids", [[100, 1]])[0][0]), "qty": 0.1, "pnl": 1000.0}
        elif imbalance < -0.6:
            signal = {"action": "SELL", "price": float(data.get("asks", [[100, 1]])[0][0]), "qty": 0.1, "pnl": 1000.0}

        if signal:
            return self.process_signal(signal, user_id=user_id)
        return None
