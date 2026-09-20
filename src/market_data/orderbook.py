import asyncio
import json
import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional
import httpx
import websockets

logger = logging.getLogger(__name__)

WS_ENDPOINTS = [
    "wss://data-stream.binance.vision/ws/btcusdt@depth20@100ms/ethusdt@depth20@100ms",
    "wss://stream.binance.com:9443/ws",
    "wss://stream.binance.us:9443/ws",
]

REST_BASE_URLS = [
    "https://api.binance.com",
    "https://api.binance.us",
    "https://data-api.binance.vision",
]


def calculate_obi(bids: list, asks: list, limit: int = 20) -> float:
    """
    Calculate Order Book Imbalance (OBI) for top N (default 20) levels:
    OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    """
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


class OrderBookManager:
    def __init__(self):
        self.obi_data: Dict[str, float] = {
            "BTCUSDT": 0.0,
            "ETHUSDT": 0.0,
        }
        self.connected_endpoint: Optional[str] = None
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None

    def get_status(self) -> Dict[str, Any]:
        btc_obi = self.obi_data.get("BTCUSDT", 0.0)
        eth_obi = self.obi_data.get("ETHUSDT", 0.0)
        overall_obi = btc_obi if btc_obi != 0.0 else eth_obi
        return {
            "status": "ok",
            "obi": overall_obi,
            "btcusdt_obi": btc_obi,
            "ethusdt_obi": eth_obi,
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
                msg_log = f"Connected to {host}"
                logger.info(msg_log)
                print(msg_log)

                if "/ws" in endpoint and "@" not in endpoint:
                    sub_msg = {
                        "method": "SUBSCRIBE",
                        "params": ["btcusdt@depth20@100ms", "ethusdt@depth20@100ms"],
                        "id": 1,
                    }
                    await ws.send(json.dumps(sub_msg))

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

    def _process_ws_message(self, msg: str):
        try:
            data = json.loads(msg)
        except Exception:
            return

        if "result" in data and "id" in data:
            return

        stream = data.get("stream", "")
        bids = []
        asks = []
        symbol = None

        if stream:
            symbol_raw = stream.split("@")[0].upper()
            if symbol_raw in ("BTCUSDT", "ETHUSDT"):
                symbol = symbol_raw
            payload = data.get("data", {})
            bids = payload.get("bids", [])
            asks = payload.get("asks", [])
        else:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            s = data.get("s", "").upper()
            if s in ("BTCUSDT", "ETHUSDT"):
                symbol = s
            elif bids:
                try:
                    top_bid_price = float(bids[0][0])
                    symbol = "BTCUSDT" if top_bid_price > 10000 else "ETHUSDT"
                except (IndexError, ValueError, TypeError):
                    pass

        if symbol and (bids or asks):
            obi_val = calculate_obi(bids, asks, limit=20)
            self.obi_data[symbol] = obi_val

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
                                obi_val = calculate_obi(bids, asks, limit=20)
                                self.obi_data[symbol] = obi_val
                                break
                        except Exception as e:
                            logger.warning(f"REST fetch failed for {symbol} on {base_url}: {e}")
                await asyncio.sleep(2)


orderbook_manager = OrderBookManager()
