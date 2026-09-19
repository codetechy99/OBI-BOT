"""
WebSocket Market Data Layer
Handles connection to Binance Futures order book streams, symbol validation, stale data monitoring,
and exponential backoff reconnection.

NOTE:
Binance XAUUSDT is not real gold (it is non-existent/synthetic on Binance Futures websocket streams).
Default symbols set to BTCUSDT and ETHUSDT.
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable
import websockets

logger = logging.getLogger(__name__)

# Default active symbols - XAUUSDT is removed because Binance XAUUSDT is not real gold
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


class MarketDataManager:
    def __init__(self, symbols: Optional[List[str]] = None, on_orderbook_callback: Optional[Callable] = None):
        self.symbols = [s.upper() for s in (symbols or DEFAULT_SYMBOLS)]
        self.on_orderbook_callback = on_orderbook_callback
        self.orderbooks: Dict[str, dict] = {}
        self.last_update: Dict[str, float] = {}
        self.symbol_status: Dict[str, str] = {s: "INITIALIZING" for s in self.symbols}
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    def parse_message(self, symbol: str, raw_msg: str) -> Optional[dict]:
        """
        Safely parses orderbook message from WebSocket stream.
        Checks for missing 'b'/'a' or 'bids'/'asks'. Returns dict if valid, else logs WARN and returns None.
        """
        try:
            data = json.loads(raw_msg)
        except Exception as e:
            logger.warning(f"Malformed JSON message received for {symbol}: {e}")
            return None

        if not isinstance(data, dict):
            logger.warning(f"Malformed message structure for {symbol}: expected dict, got {type(data)}")
            return None

        # Check for nested payload (e.g., combined stream wrapper)
        if "data" in data and isinstance(data["data"], dict):
            payload = data["data"]
        else:
            payload = data

        bids = payload.get("b", payload.get("bids"))
        asks = payload.get("a", payload.get("asks"))

        if bids is None or asks is None:
            logger.warning(f"Malformed orderbook message missing 'b'/'bids' or 'a'/'asks' for {symbol}")
            return None

        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "timestamp": payload.get("E", payload.get("T", time.time()))
        }

    def process_orderbook(self, symbol: str, orderbook: dict, timestamp: Optional[float] = None):
        now = timestamp if timestamp is not None else time.time()
        self.orderbooks[symbol] = orderbook
        self.last_update[symbol] = now
        self.symbol_status[symbol] = "OK"

        if self.on_orderbook_callback:
            self.on_orderbook_callback(symbol, orderbook, now)

    def check_stale_symbols(self, current_time: Optional[float] = None) -> Dict[str, str]:
        """
        Marks symbol as STALE if last_update > 5 seconds ago.
        """
        now = current_time if current_time is not None else time.time()
        for sym in list(self.symbols):
            last_t = self.last_update.get(sym, 0)
            if last_t == 0:
                continue
            if now - last_t > 5.0:
                self.symbol_status[sym] = "STALE"
                logger.warning(f"Symbol {sym} data is STALE (last update {now - last_t:.2f}s ago)")
        return self.symbol_status

    async def validate_symbols(self, timeout: float = 10.0) -> List[str]:
        """
        Validates configured symbols by waiting up to `timeout` seconds for valid bids/asks.
        If a symbol returns no valid bids/asks, logs WARN invalid symbol and removes it.
        """
        logger.info(f"Validating symbols {self.symbols} over {timeout}s stream window...")
        start_t = time.time()
        valid_symbols = []
        invalid_symbols = []

        while time.time() - start_t < timeout:
            for sym in list(self.symbols):
                ob = self.orderbooks.get(sym)
                if ob and ob.get("bids") and ob.get("asks"):
                    if sym not in valid_symbols:
                        valid_symbols.append(sym)

            if len(valid_symbols) == len(self.symbols):
                break
            await asyncio.sleep(0.5)

        for sym in list(self.symbols):
            if sym not in valid_symbols:
                invalid_symbols.append(sym)
                logger.warning(f"WARN invalid symbol: {sym} returned no valid bids/asks in {timeout}s. Removing from active symbols.")
                self.symbol_status[sym] = "INVALID"

        self.symbols = [s for s in self.symbols if s not in invalid_symbols]
        return self.symbols

    async def connect_and_stream(self, stream_url: Optional[str] = None):
        """
        Connects to Binance WS depth stream with exponential backoff reconnect logic.
        """
        self.is_running = True
        backoff_delay = 1.0
        max_backoff = 30.0

        if not self.symbols:
            logger.warning("No active symbols to stream.")
            return

        stream_names = "/".join([f"{s.lower()}@depth5@100ms" for s in self.symbols])
        url = stream_url or f"wss://fstream.binance.com/stream?streams={stream_names}"

        while self.is_running:
            try:
                logger.info(f"Connecting to market data stream: {url}")
                async with websockets.connect(url) as ws:
                    backoff_delay = 1.0  # Reset backoff on successful connection
                    logger.info("Market data WebSocket connected.")
                    while self.is_running:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(msg)
                        stream = data.get("stream", "")
                        symbol = stream.split("@")[0].upper() if "@" in stream else self.symbols[0]
                        parsed = self.parse_message(symbol, msg)
                        if parsed:
                            self.process_orderbook(symbol, parsed)
                        self.check_stale_symbols()
            except asyncio.TimeoutError:
                self.check_stale_symbols()
            except asyncio.CancelledError:
                logger.info("Market data WebSocket stream task cancelled.")
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}. Reconnecting in {backoff_delay}s...")
                await asyncio.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, max_backoff)

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        if not self.is_running:
            self.is_running = True
            loop = loop or asyncio.get_event_loop()
            self._task = loop.create_task(self.connect_and_stream())

    def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
