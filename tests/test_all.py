import pytest
import os
import json
from fastapi.testclient import TestClient

from src.money.ledger import Ledger
from src.market_data.obi import get_imbalance, calculate_obi_from_orderbook
from src.market_data.orderbook import OrderBookManager, orderbook_manager
from src.app.main import app

TEST_DB = "test_db.json"

@pytest.fixture
def ledger():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    l = Ledger(TEST_DB)
    yield l
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def test_ledger_operations(ledger):
    assert ledger.get_balance("user1") == 0.0

    # Deposit
    bal = ledger.deposit("user1", 200.0, method="MoMo")
    assert bal == 200.0
    assert ledger.get_balance("user1") == 200.0

    # Withdraw
    bal = ledger.withdraw("user1", 50.0)
    assert bal == 150.0

    # Insufficient balance withdrawal
    with pytest.raises(ValueError, match="Insufficient balance"):
        ledger.withdraw("user1", 500.0)

    # PnL
    bal = ledger.apply_pnl("user1", 25.0)
    assert bal == 175.0

    bal = ledger.apply_pnl("user1", -50.0)
    assert bal == 125.0

    # Insufficient balance negative PnL
    with pytest.raises(ValueError, match="Insufficient balance for negative PnL"):
        ledger.apply_pnl("user1", -200.0)

    # History
    history = ledger.get_history("user1")
    assert len(history) == 4


def test_obi_calculations():
    # Basic bids and asks
    bids = [[100, 10], [99, 20], [98, 30], [97, 40]]
    asks = [[101, 5], [102, 5], [103, 10], [104, 10]]

    # V_bid = 10 + 20 + 30 = 60
    # V_ask = 5 + 5 + 10 = 20
    # I = (60 - 20) / (60 + 20) = 40 / 80 = 0.5
    i = get_imbalance(bids, asks)
    assert abs(i - 0.5) < 1e-6

    # Test dictionary orderbook
    ob = {"bids": bids, "asks": asks}
    i_ob = calculate_obi_from_orderbook(ob)
    assert abs(i_ob - 0.5) < 1e-6

    # Test empty
    assert get_imbalance([], []) == 0.0
    assert calculate_obi_from_orderbook({}) == 0.0


def test_orderbook_manager_process_message():
    mgr = OrderBookManager()

    # Combined stream message format for BTCUSDT
    msg_btc = {
        "stream": "btcusdt@depth20@100ms",
        "data": {
            "bids": [["80000", "10"], ["79900", "20"]],
            "asks": [["80100", "5"], ["80200", "5"]]
        }
    }
    mgr.process_message(json.dumps(msg_btc))
    btc_state = mgr.state["BTCUSDT"]
    # bids = 30, asks = 10, OBI = (30 - 10) / 40 = 0.5
    assert btc_state["last_obi"] == 0.5
    assert btc_state["bids"] == 30.0
    assert btc_state["asks"] == 10.0
    assert btc_state["state"] == "NEUTRAL"

    # Combined stream message format for ETHUSDT
    msg_eth = {
        "stream": "ethusdt@depth20@100ms",
        "data": {
            "bids": [["2000", "5"]],
            "asks": [["2010", "15"]]
        }
    }
    mgr.process_message(json.dumps(msg_eth))
    eth_state = mgr.state["ETHUSDT"]
    # bids = 5, asks = 15, OBI = (5 - 15) / 20 = -0.5
    assert eth_state["last_obi"] == -0.5
    assert eth_state["bids"] == 5.0
    assert eth_state["asks"] == 15.0


def test_fastapi_endpoints():
    if os.path.exists("db.json"):
        os.remove("db.json")

    client = TestClient(app)

    # Dashboard status
    res = client.get("/api/dashboard/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "BTCUSDT" in data
    assert "ETHUSDT" in data

    # Get balance
    res = client.get("/balance/user2")
    assert res.status_code == 200
    assert res.json() == {"user_id": "user2", "balance": 0.0}

    # Deposit
    res = client.post("/deposit", json={"user_id": "user2", "amount": 100.0, "method": "MoMo"})
    assert res.status_code == 200
    assert res.json()["balance"] == 100.0

    # Withdraw
    res = client.post("/withdraw", json={"user_id": "user2", "amount": 40.0})
    assert res.status_code == 200
    assert res.json()["balance"] == 60.0

    # Insufficient withdraw
    res = client.post("/withdraw", json={"user_id": "user2", "amount": 1000.0})
    assert res.status_code == 400
    assert res.json()["detail"] == "Insufficient balance"

    if os.path.exists("db.json"):
        os.remove("db.json")
