import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
import httpx
import websockets

logger = logging.getLogger("obi_bot")

WS_ENDPOINTS = [
    "wss://data-stream.binance.vision/ws/btcusdt@depth20@100ms/ethusdt@depth20@100ms",
    "wss://stream.binance.com:9443/ws",
    "wss://stream.binance.us:9443/ws",
    "wss://data-stream.binance.vision/ws/btcusdt@depth@100ms",
]

REST_BASE_URLS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
    "https://api.binance.us",
]


def calculate_obi(bids: list, asks: list, limit: int = 20) -> float:
    top_bids = bids[:limit] if bids else []
    top_asks = asks[:limit] if asks else []

    def extract_qty(level):
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            return float(level[1])
        if isinstance(level, dict):
            for k in ("volume", "qty", "size", "amount"):
                if k in level:
                    return float(level[k])
        if isinstance(level, (int, float)):
            return float(level)
        return 0.0

    v_bid = sum(extract_qty(b) for b in top_bids)
    v_ask = sum(extract_qty(a) for a in top_asks)

    total_vol = v_bid + v_ask
    if total_vol == 0:
        return 0.0

    return (v_bid - v_ask) / total_vol


class OrderBookState:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids_dict: Dict[float, float] = {}  # price -> qty
        self.asks_dict: Dict[float, float] = {}  # price -> qty
        self.best_bid: float = 0.0
        self.best_ask: float = 0.0
        self.last_price: float = 0.0
        self.obi: float = 0.0
        self.updated_at: float = 0.0

    def update_snapshot(self, bids: List, asks: List):
        self.bids_dict.clear()
        self.asks_dict.clear()
        for b in bids:
            try:
                p, q = float(b[0]), float(b[1])
                if q > 0:
                    self.bids_dict[p] = q
            except (IndexError, ValueError, TypeError):
                pass
        for a in asks:
            try:
                p, q = float(a[0]), float(a[1])
                if q > 0:
                    self.asks_dict[p] = q
            except (IndexError, ValueError, TypeError):
                pass
        self._recalculate()

    def update_diff(self, bids_diff: List, asks_diff: List):
        for b in bids_diff:
            try:
                p, q = float(b[0]), float(b[1])
                if q == 0:
                    self.bids_dict.pop(p, None)
                else:
                    self.bids_dict[p] = q
            except (IndexError, ValueError, TypeError):
                pass
        for a in asks_diff:
            try:
                p, q = float(a[0]), float(a[1])
                if q == 0:
                    self.asks_dict.pop(p, None)
                else:
                    self.asks_dict[p] = q
            except (IndexError, ValueError, TypeError):
                pass
        self._recalculate()

    def _recalculate(self):
        sorted_bids = sorted(self.bids_dict.items(), key=lambda x: x[0], reverse=True)
        sorted_asks = sorted(self.asks_dict.items(), key=lambda x: x[0])

        self.best_bid = sorted_bids[0][0] if sorted_bids else 0.0
        self.best_ask = sorted_asks[0][0] if sorted_asks else 0.0

        if self.best_bid > 0 and self.best_ask > 0:
            self.last_price = (self.best_bid + self.best_ask) / 2.0
        elif self.best_bid > 0:
            self.last_price = self.best_bid
        elif self.best_ask > 0:
            self.last_price = self.best_ask

        top_bids = [[p, q] for p, q in sorted_bids[:20]]
        top_asks = [[p, q] for p, q in sorted_asks[:20]]
        self.obi = calculate_obi(top_bids, top_asks, limit=20)
        self.updated_at = time.time()

    def get_snapshot(self) -> Dict[str, Any]:
        sorted_bids = sorted(self.bids_dict.items(), key=lambda x: x[0], reverse=True)[:10]
        sorted_asks = sorted(self.asks_dict.items(), key=lambda x: x[0])[:10]

        top_bids_list = [[float(p), float(q)] for p, q in sorted_bids]
        top_asks_list = [[float(p), float(q)] for p, q in sorted_asks]

        spread = (self.best_ask - self.best_bid) if (self.best_ask > 0 and self.best_bid > 0) else 0.0

        return {
            "symbol": self.symbol,
            "best_bid": round(self.best_bid, 2),
            "best_ask": round(self.best_ask, 2),
            "price": round(self.last_price, 2),
            "spread": round(spread, 2),
            "obi": self.obi,
            "obi_percent": round(self.obi * 100, 1),
            "bids": top_bids_list,
            "asks": top_asks_list,
            "updated_at": self.updated_at,
        }


class OrderBookManager:
    def __init__(self):
        self.books: Dict[str, OrderBookState] = {
            "BTCUSDT": OrderBookState("BTCUSDT"),
            "ETHUSDT": OrderBookState("ETHUSDT"),
        }
        self.connected_endpoint: Optional[str] = None
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._log_counter: int = 0

    @property
    def obi_data(self) -> Dict[str, float]:
        return {
            "BTCUSDT": self.books["BTCUSDT"].obi,
            "ETHUSDT": self.books["ETHUSDT"].obi,
        }

    def get_market_snapshot(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        if symbol not in self.books:
            symbol = "BTCUSDT"
        return self.books[symbol].get_snapshot()

    def get_status(self) -> Dict[str, Any]:
        btc_book = self.books["BTCUSDT"]
        eth_book = self.books["ETHUSDT"]
        overall_obi = btc_book.obi if btc_book.obi != 0.0 else eth_book.obi
        return {
            "status": "ok",
            "obi": overall_obi,
            "btcusdt_obi": btc_book.obi,
            "ethusdt_obi": eth_book.obi,
            "btcusdt_price": round(btc_book.last_price, 2),
            "btcusdt_best_bid": round(btc_book.best_bid, 2),
            "btcusdt_best_ask": round(btc_book.best_ask, 2),
            "connected_endpoint": self.connected_endpoint,
        }

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self.run_loop())

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_loop(self):
        while self.is_running:
            connected = False
            for endpoint in WS_ENDPOINTS:
                if not self.is_running:
                    break
                try:
                    connected = await self._connect_and_listen_ws(endpoint)
                    if connected:
                        break
                except Exception as e:
                    logger.warning(f"Failed connection to {endpoint}: {e}")

            if not connected and self.is_running:
                logger.warning("All WebSocket endpoints failed. Falling back to REST polling.")
                await self._run_rest_fallback()

            if self.is_running:
                await asyncio.sleep(1)

    async def _connect_and_listen_ws(self, endpoint: str) -> bool:
        parsed = urlparse(endpoint)
        host = parsed.netloc.split(":")[0]

        try:
            async with websockets.connect(endpoint, ping_interval=20, ping_timeout=20) as ws:
                self.connected_endpoint = host
                msg_log = f"Connected to Binance OrderBook Stream at {host} ({endpoint})"
                logger.info(msg_log)
                print(msg_log)

                if "/ws" in endpoint and "@" not in endpoint:
                    sub_msg = {
                        "method": "SUBSCRIBE",
                        "params": ["btcusdt@depth20@100ms", "ethusdt@depth20@100ms"],
                        "id": 1,
                    }
                    await ws.send(json.dumps(sub_msg))

                # Fetch initial REST snapshot for BTCUSDT if empty to seed orderbook
                await self._seed_initial_snapshots()

                while self.is_running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=15)
                        self._process_ws_message(msg)
                    except asyncio.TimeoutError:
                        await ws.ping()
                return True
        except Exception as e:
            logger.warning(f"WebSocket error on {endpoint}: {e}")
            return False

    async def _seed_initial_snapshots(self):
        async with httpx.AsyncClient(timeout=5.0) as client:
            for symbol in ["BTCUSDT", "ETHUSDT"]:
                for base_url in REST_BASE_URLS:
                    try:
                        url = f"{base_url}/api/v3/depth?symbol={symbol}&limit=20"
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            data = resp.json()
                            bids = data.get("bids", [])
                            asks = data.get("asks", [])
                            self.books[symbol].update_snapshot(bids, asks)
                            logger.info(f"Seeded snapshot for {symbol}: Bid={self.books[symbol].best_bid}, Ask={self.books[symbol].best_ask}, OBI={self.books[symbol].obi:.4f}")
                            break
                    except Exception as e:
                        logger.debug(f"Snapshot seed failed for {symbol} on {base_url}: {e}")

    def _process_ws_message(self, msg: str):
        try:
            data = json.loads(msg)
        except Exception:
            return

        if "result" in data and "id" in data:
            return

        stream = data.get("stream", "")
        payload = data.get("data", data)

        symbol = None
        if stream:
            symbol_raw = stream.split("@")[0].upper()
            if symbol_raw in self.books:
                symbol = symbol_raw
        elif "s" in payload:
            s = payload["s"].upper()
            if s in self.books:
                symbol = s

        # Check fields
        if "bids" in payload and "asks" in payload:
            if not symbol:
                bids = payload.get("bids", [])
                if bids:
                    try:
                        p = float(bids[0][0])
                        symbol = "BTCUSDT" if p > 10000 else "ETHUSDT"
                    except Exception:
                        symbol = "BTCUSDT"
            if symbol and symbol in self.books:
                self.books[symbol].update_snapshot(payload["bids"], payload["asks"])
        elif "b" in payload or "a" in payload:
            if not symbol:
                symbol = "BTCUSDT"
            if symbol in self.books:
                bids_diff = payload.get("b", [])
                asks_diff = payload.get("a", [])
                self.books[symbol].update_diff(bids_diff, asks_diff)

        # Log orderbook update every 50 packets (~5s) to Render logs
        self._log_counter += 1
        if self._log_counter % 50 == 0:
            btc_snap = self.books["BTCUSDT"].get_snapshot()
            logger.info(
                f"[ORDERBOOK UPDATE] BTCUSDT Price: ${btc_snap['price']} | "
                f"Bid: ${btc_snap['best_bid']} | Ask: ${btc_snap['best_ask']} | "
                f"Spread: ${btc_snap['spread']} | OBI: {btc_snap['obi']:+.4f} ({btc_snap['obi_percent']:+.1f}%)"
            )

    async def _run_rest_fallback(self):
        self.connected_endpoint = "REST Fallback"
        async with httpx.AsyncClient(timeout=5.0) as client:
            while self.is_running:
                for symbol in ["BTCUSDT", "ETHUSDT"]:
                    for base_url in REST_BASE_URLS:
                        url = f"{base_url}/api/v3/depth?symbol={symbol}&limit=20"
                        try:
                            resp = await client.get(url)
                            if resp.status_code == 200:
                                data = resp.json()
                                bids = data.get("bids", [])
                                asks = data.get("asks", [])
                                self.books[symbol].update_snapshot(bids, asks)
                                break
                        except Exception as e:
                            logger.warning(f"REST fetch failed for {symbol} on {base_url}: {e}")

                self._log_counter += 1
                if self._log_counter % 5 == 0:
                    btc_snap = self.books["BTCUSDT"].get_snapshot()
                    logger.info(
                        f"[REST ORDERBOOK] BTCUSDT Price: ${btc_snap['price']} | "
                        f"Bid: ${btc_snap['best_bid']} | Ask: ${btc_snap['best_ask']} | "
                        f"OBI: {btc_snap['obi']:+.4f}"
                    )
                await asyncio.sleep(0.5)


orderbook_manager = OrderBookManager()
