import asyncio
import json
import os
import time
import datetime
import websockets
from src.market_data.obi import calculate_obi_from_orderbook
from src.risk.circuit_breaker import CircuitBreaker

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms"
LOG_DIR = "data"
LOG_FILE = os.path.join(LOG_DIR, "ticks.log")

latest_obi_data = {
    "I": 0.0,
    "bid": 0.0,
    "ask": 0.0,
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
}

def log_tick(timestamp: str, I: float, bid1: float, ask1: float):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_line = f"{timestamp} | OBI: {I:+.4f} | Bid1: {bid1:.2f} | Ask1: {ask1:.2f}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line)

async def start_ws_client(execution_handler=None):
    global latest_obi_data
    while True:
        try:
            async with websockets.connect(BINANCE_WS_URL) as ws:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    bids = data.get("bids", [])
                    asks = data.get("asks", [])

                    if not bids or not asks:
                        continue

                    # Bids/asks are lists of [price, qty]
                    best_bid = float(bids[0][0]) if bids else 0.0
                    best_ask = float(asks[0][0]) if asks else 0.0

                    # Parse numerical bids/asks for OBI calculation
                    parsed_bids = [[float(p), float(q)] for p, q in bids]
                    parsed_asks = [[float(p), float(q)] for p, q in asks]

                    I = calculate_obi_from_orderbook({"bids": parsed_bids, "asks": parsed_asks})
                    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

                    latest_obi_data = {
                        "I": round(I, 4),
                        "bid": best_bid,
                        "ask": best_ask,
                        "timestamp": timestamp
                    }

                    # Log tick
                    log_tick(timestamp, I, best_bid, best_ask)

                    # Signal execution handler if circuit breaker allows
                    if not CircuitBreaker.should_pause():
                        if execution_handler:
                            execution_handler.on_signal(I, best_bid, best_ask, tick_size=0.1)

        except Exception as e:
            # Reconnect after brief pause on connection drop or error
            await asyncio.sleep(2)
