import asyncio
import json
import logging
import time
import websockets

from src.market_data.obi import get_imbalance

logger = logging.getLogger("orderbook_manager")


class OrderBookManager:
    def __init__(self):
        self.state = {
            "BTCUSDT": {
                "last_obi": 0.0,
                "state": "NEUTRAL",
                "bids": 0.0,
                "asks": 0.0,
                "bids_vol": 0.0,
                "asks_vol": 0.0,
                "last_updated": None,
            },
            "ETHUSDT": {
                "last_obi": 0.0,
                "state": "NEUTRAL",
                "bids": 0.0,
                "asks": 0.0,
                "bids_vol": 0.0,
                "asks_vol": 0.0,
                "last_updated": None,
            },
        }
        self.connected = False
        self.last_log_times = {}
        self.logger = logger

    def process_message(self, message: str):
        try:
            data = json.loads(message)
        except Exception as e:
            self.logger.error(f"Failed to parse JSON WS message: {e}")
            return

        symbol = None
        ob_data = data

        if "stream" in data:
            stream_name = data["stream"]
            symbol = stream_name.split("@")[0].upper()
            ob_data = data.get("data", {})
        elif "s" in data:
            symbol = data["s"].upper()
        elif "symbol" in data:
            symbol = data["symbol"].upper()

        bids = ob_data.get("bids", [])
        asks = ob_data.get("asks", [])

        if not symbol and bids:
            try:
                top_bid_price = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0])
                symbol = "BTCUSDT" if top_bid_price > 10000 else "ETHUSDT"
            except Exception:
                pass

        if not symbol or symbol not in self.state:
            return

        top_bids = bids[:20]
        top_asks = asks[:20]

        bid_vol = sum(float(b[1]) if isinstance(b, (list, tuple)) else float(b) for b in top_bids)
        ask_vol = sum(float(a[1]) if isinstance(a, (list, tuple)) else float(a) for a in top_asks)

        total_vol = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

        now = time.time()
        self.state[symbol] = {
            "last_obi": round(obi, 4),
            "state": self.state[symbol].get("state", "NEUTRAL"),
            "bids": round(bid_vol, 4),
            "asks": round(ask_vol, 4),
            "bids_vol": round(bid_vol, 4),
            "asks_vol": round(ask_vol, 4),
            "last_updated": now,
        }

        last_log = self.last_log_times.get(symbol, 0.0)
        if now - last_log >= 5.0:
            self.logger.info(f"OBI {symbol}={obi:.2f} bids={bid_vol:.2f} asks={ask_vol:.2f}")
            self.last_log_times[symbol] = now

    async def start(self):
        urls = [
            "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms/ethusdt@depth20@100ms",
            "wss://data-stream.binance.com/ws/btcusdt@depth20@100ms/ethusdt@depth20@100ms",
            "wss://data-stream.binance.com/stream?streams=btcusdt@depth20@100ms/ethusdt@depth20@100ms",
        ]
        backoff = 1.0
        max_backoff = 30.0

        while True:
            for url in urls:
                try:
                    self.logger.info(f"Attempting WS connection to {url}")
                    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                        self.logger.info("WS connected")
                        self.connected = True
                        backoff = 1.0
                        async for message in ws:
                            self.process_message(message)
                except asyncio.CancelledError:
                    self.logger.info("OrderBookManager task cancelled")
                    self.connected = False
                    return
                except Exception as e:
                    self.logger.warning(f"WS connection error ({url}): {e}")
                    self.connected = False

            self.logger.info(f"Reconnecting in {backoff:.1f} seconds...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    def get_status(self) -> dict:
        return {
            "status": "connected" if self.connected else "disconnected",
            "symbols": self.state,
            "BTCUSDT": self.state.get("BTCUSDT", {}),
            "ETHUSDT": self.state.get("ETHUSDT", {}),
        }


orderbook_manager = OrderBookManager()
