import asyncio
import pytest
from fastapi.testclient import TestClient

from src.market_data.orderbook import calculate_obi, OrderBookManager, WS_ENDPOINTS, REST_BASE_URLS
from src.app.main import app


def test_calculate_obi_top_20():
    bids = [[100 - i, 10] for i in range(25)]
    asks = [[101 + i, 5] for i in range(25)]

    # Top 20 bids = 20 * 10 = 200
    # Top 20 asks = 20 * 5 = 100
    # OBI = (200 - 100) / (200 + 100) = 100 / 300 = 0.3333333333333333
    obi = calculate_obi(bids, asks, limit=20)
    assert abs(obi - (1 / 3)) < 1e-6


def test_endpoints_order():
    assert WS_ENDPOINTS[0] == "wss://data-stream.binance.vision/ws/btcusdt@depth20@100ms/ethusdt@depth20@100ms"
    assert WS_ENDPOINTS[1] == "wss://stream.binance.com:9443/ws"
    assert WS_ENDPOINTS[2] == "wss://stream.binance.us:9443/ws"


def test_orderbook_manager_process_msg():
    mgr = OrderBookManager()

    # Direct raw depth message for BTC
    raw_msg_btc = '{"lastUpdateId": 12345, "bids": [["80000", "2.0"]], "asks": [["80100", "1.0"]]}'
    mgr._process_ws_message(raw_msg_btc)
    status = mgr.get_status()
    assert status["btcusdt_obi"] == pytest.approx((2.0 - 1.0) / (2.0 + 1.0))

    # Stream wrapper message for ETH
    stream_msg_eth = '{"stream": "ethusdt@depth20@100ms", "data": {"bids": [["2500", "5.0"]], "asks": [["2510", "15.0"]]}}'
    mgr._process_ws_message(stream_msg_eth)
    status = mgr.get_status()
    assert status["ethusdt_obi"] == pytest.approx((5.0 - 15.0) / (5.0 + 15.0))


def test_fastapi_dashboard_endpoints():
    client = TestClient(app)

    # Test / route redirect or response
    r_root = client.get("/", follow_redirects=False)
    assert r_root.status_code in (200, 307, 302)

    # Test /dashboard
    r_dash = client.get("/dashboard")
    assert r_dash.status_code == 200
    assert "OBI" in r_dash.text

    # Test /api/dashboard/status
    r_status = client.get("/api/dashboard/status")
    assert r_status.status_code == 200
    data = r_status.json()
    assert "status" in data
    assert "obi" in data
    assert "btcusdt_obi" in data
    assert "ethusdt_obi" in data


@pytest.mark.asyncio
async def test_orderbook_live_connection():
    mgr = OrderBookManager()
    await mgr.start()
    await asyncio.sleep(2)
    status = mgr.get_status()
    assert status["status"] == "ok"
    assert status["connected_endpoint"] is not None
    assert isinstance(status["obi"], float)
    await mgr.stop()
