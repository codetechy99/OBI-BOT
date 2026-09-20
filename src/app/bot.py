import asyncio
import datetime
import logging
import time
from typing import Dict, Any, List, Optional
from src.market_data.orderbook import orderbook_manager
from src.money.ledger import Ledger

logger = logging.getLogger("obi_bot")


class TradingBotEngine:
    def __init__(self, ledger_path: str = "db.json"):
        self.ledger = Ledger(ledger_path)
        self.user_id = "default_user"

        # Ensure default user exists with $10,000 initial balance in demo mode
        if self.ledger.get_balance(self.user_id) <= 0:
            self.ledger.deposit(self.user_id, 10000.0, method="Demo Virtual Deposit")

        self.is_running: bool = False
        self.mode: str = "demo"  # "demo" or "live"
        self.lot_size: float = 0.1  # BTC lot size
        self.threshold: float = 0.35  # OBI threshold (e.g. 0.35 = 35%)
        self.tp_usd: float = 150.0  # Take profit in USD
        self.sl_usd: float = 100.0  # Stop loss in USD
        self.close_on_stop: bool = True

        # Live Binance testnet credentials
        self.binance_api_key: str = ""
        self.binance_api_secret: str = ""

        self.open_positions: List[Dict[str, Any]] = []
        self.trades_history: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        self.equity_history: List[Dict[str, Any]] = []

        self._task: Optional[asyncio.Task] = None
        self._last_signal_time: float = 0.0

        self.add_log("SYSTEM", "OBI Bot Trading Engine initialized.")

    def add_log(self, category: str, message: str, level: str = "INFO"):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {
            "time": now_str,
            "timestamp": time.time(),
            "category": category,
            "message": message,
            "level": level,
        }
        self.logs.append(entry)
        if len(self.logs) > 300:
            self.logs.pop(0)
        logger.info(f"[{category}] {message}")

    def reset_demo_balance(self):
        # Reset user ledger and clear open positions
        data = self.ledger._load_db()
        data[self.user_id] = {
            "balance": 10000.0,
            "history": [{
                "type": "deposit",
                "amount": 10000.0,
                "method": "Demo Reset",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "balance_after": 10000.0
            }]
        }
        self.ledger._save_db(data)
        self.open_positions.clear()
        self.trades_history.clear()
        self.equity_history.clear()
        self.add_log("DEMO", "Demo account reset to $10,000 virtual balance.")

    def update_settings(self, mode: Optional[str] = None, lot_size: Optional[float] = None,
                        threshold: Optional[float] = None, tp_usd: Optional[float] = None,
                        sl_usd: Optional[float] = None, api_key: Optional[str] = None,
                        api_secret: Optional[str] = None):
        if mode in ("demo", "live"):
            self.mode = mode
        if lot_size is not None and lot_size > 0:
            self.lot_size = lot_size
        if threshold is not None and 0.05 <= threshold <= 0.95:
            self.threshold = threshold
        if tp_usd is not None and tp_usd > 0:
            self.tp_usd = tp_usd
        if sl_usd is not None and sl_usd > 0:
            self.sl_usd = sl_usd
        if api_key is not None:
            self.binance_api_key = api_key
        if api_secret is not None:
            self.binance_api_secret = api_secret

        self.add_log("SETTINGS", f"Settings updated: Mode={self.mode.upper()}, Lot={self.lot_size}, OBI Threshold={int(self.threshold*100)}%, TP=${self.tp_usd}, SL=${self.sl_usd}")

    async def start_bot(self) -> Dict[str, Any]:
        if self.is_running:
            return {"status": "already_running", "message": "Bot is already running."}

        if self.mode == "live" and (not self.binance_api_key or not self.binance_api_secret):
            raise ValueError("Live trading requires Binance Testnet API Key and Secret in Settings.")

        self.is_running = True
        self.add_log("BOT", f"BOT STARTED in {self.mode.upper()} mode! Monitoring OBI signals...", level="SUCCESS")
        self._task = asyncio.create_task(self._run_loop())
        return {"status": "success", "message": f"Bot started in {self.mode} mode."}

    async def stop_bot(self, close_positions: bool = True) -> Dict[str, Any]:
        if not self.is_running:
            return {"status": "not_running", "message": "Bot is not running."}

        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        closed_count = 0
        if close_positions and self.open_positions:
            snap = orderbook_manager.get_market_snapshot("BTCUSDT")
            current_price = snap.get("price", 67000.0)
            for pos in list(self.open_positions):
                self._close_position(pos, current_price, reason="BOT STOPPED")
                closed_count += 1

        self.add_log("BOT", f"BOT STOPPED. Closed {closed_count} position(s).", level="WARNING")
        return {"status": "success", "message": f"Bot stopped. Closed {closed_count} positions."}

    def _close_position(self, pos: Dict[str, Any], close_price: float, reason: str):
        if pos not in self.open_positions:
            return

        side = pos["side"]
        entry_price = pos["entry_price"]
        amount = pos["amount"]

        if side == "BUY":
            pnl = (close_price - entry_price) * amount
        else:
            pnl = (entry_price - close_price) * amount

        self.open_positions.remove(pos)

        # Apply PnL in ledger
        try:
            new_bal = self.ledger.apply_pnl(self.user_id, pnl)
        except Exception as e:
            logger.error(f"Failed to apply PnL to ledger: {e}")
            new_bal = self.ledger.get_balance(self.user_id)

        trade_record = {
            "id": pos["id"],
            "side": side,
            "entry_price": round(entry_price, 2),
            "close_price": round(close_price, 2),
            "amount": amount,
            "pnl": round(pnl, 2),
            "reason": reason,
            "opened_at": pos["opened_at"],
            "closed_at": datetime.datetime.now().strftime("%H:%M:%S"),
        }
        self.trades_history.insert(0, trade_record)
        if len(self.trades_history) > 100:
            self.trades_history.pop()

        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        self.add_log(
            "TRADE",
            f"CLOSED {side} position #{pos['id']} at ${close_price:,.2f} ({reason}) | PnL: {pnl_str} | Bal: ${new_bal:,.2f}",
            level="SUCCESS" if pnl >= 0 else "ERROR"
        )

    def _open_position(self, side: str, current_price: float, obi_value: float):
        position_id = f"POS-{int(time.time() * 1000) % 100000}"
        pos = {
            "id": position_id,
            "side": side,
            "entry_price": current_price,
            "amount": self.lot_size,
            "opened_at": datetime.datetime.now().strftime("%H:%M:%S"),
            "obi_trigger": round(obi_value, 4),
        }
        self.open_positions.append(pos)
        self._last_signal_time = time.time()

        self.add_log(
            "SIGNAL",
            f"OBI {obi_value:+.4f} -> {side} SIGNAL! Opened {self.lot_size} BTC @ ${current_price:,.2f}",
            level="BUY" if side == "BUY" else "SELL"
        )

    async def _run_loop(self):
        while self.is_running:
            try:
                await asyncio.sleep(0.5)
                snap = orderbook_manager.get_market_snapshot("BTCUSDT")
                current_price = snap.get("price", 0.0)
                obi_val = snap.get("obi", 0.0)

                if current_price <= 0:
                    continue

                # 1. Manage open positions for TP/SL and opposite signal
                for pos in list(self.open_positions):
                    side = pos["side"]
                    entry_price = pos["entry_price"]
                    amount = pos["amount"]

                    pnl = (current_price - entry_price) * amount if side == "BUY" else (entry_price - current_price) * amount

                    if pnl >= self.tp_usd:
                        self._close_position(pos, current_price, reason="TAKE PROFIT")
                    elif pnl <= -self.sl_usd:
                        self._close_position(pos, current_price, reason="STOP LOSS")
                    elif side == "BUY" and obi_val < -self.threshold:
                        self._close_position(pos, current_price, reason="SIGNAL REVERSAL")
                    elif side == "SELL" and obi_val > self.threshold:
                        self._close_position(pos, current_price, reason="SIGNAL REVERSAL")

                # 2. Check for new position entry if no position is open and cooldown passed (3 seconds)
                if len(self.open_positions) == 0 and (time.time() - self._last_signal_time) > 3.0:
                    if obi_val >= self.threshold:
                        self._open_position("BUY", current_price, obi_val)
                    elif obi_val <= -self.threshold:
                        self._open_position("SELL", current_price, obi_val)

                # 3. Track equity
                balance = self.ledger.get_balance(self.user_id)
                unrealized_pnl = sum(
                    (current_price - p["entry_price"]) * p["amount"] if p["side"] == "BUY" else (p["entry_price"] - current_price) * p["amount"]
                    for p in self.open_positions
                )
                equity = balance + unrealized_pnl

                if not self.equity_history or (time.time() - self.equity_history[-1]["timestamp"]) >= 2.0:
                    self.equity_history.append({
                        "time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "timestamp": time.time(),
                        "balance": round(balance, 2),
                        "equity": round(equity, 2),
                    })
                    if len(self.equity_history) > 100:
                        self.equity_history.pop(0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in bot loop: {e}")
                await asyncio.sleep(1)

    def get_status(self) -> Dict[str, Any]:
        snap = orderbook_manager.get_market_snapshot("BTCUSDT")
        current_price = snap.get("price", 0.0)
        balance = self.ledger.get_balance(self.user_id)

        unrealized_pnl = sum(
            (current_price - p["entry_price"]) * p["amount"] if p["side"] == "BUY" else (p["entry_price"] - current_price) * p["amount"]
            for p in self.open_positions
        )
        equity = balance + unrealized_pnl

        # Calculate open positions enriched with current PnL
        positions_enriched = []
        for p in self.open_positions:
            side = p["side"]
            p_pnl = (current_price - p["entry_price"]) * p["amount"] if side == "BUY" else (p["entry_price"] - current_price) * p["amount"]
            positions_enriched.append({
                **p,
                "current_price": round(current_price, 2),
                "unrealized_pnl": round(p_pnl, 2),
            })

        return {
            "is_running": self.is_running,
            "mode": self.mode,
            "lot_size": self.lot_size,
            "threshold": self.threshold,
            "threshold_percent": int(self.threshold * 100),
            "tp_usd": self.tp_usd,
            "sl_usd": self.sl_usd,
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "open_positions": positions_enriched,
            "open_positions_count": len(self.open_positions),
            "today_trades_count": len(self.trades_history),
            "trades_history": self.trades_history,
            "equity_history": self.equity_history,
        }


bot_engine = TradingBotEngine()
