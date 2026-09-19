import pytest
import os
from fastapi.testclient import TestClient

from src.money.ledger import Ledger
from src.market_data.obi import get_imbalance, calculate_obi_from_orderbook
from src.app.main import app, calc_obi

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


def test_main_calc_obi():
    bids = [["100.0", "10.0"], ["99.0", "20.0"]]
    asks = [["101.0", "5.0"], ["102.0", "5.0"]]
    obi, b_vol, a_vol = calc_obi(bids, asks)
    assert abs(b_vol - 30.0) < 1e-6
    assert abs(a_vol - 10.0) < 1e-6
    assert abs(obi - 0.5) < 1e-6

    # Zero total
    obi_zero, b_zero, a_zero = calc_obi([], [])
    assert obi_zero == 0
    assert b_zero == 0
    assert a_zero == 0


def test_fastapi_endpoints():
    client = TestClient(app)

    # Root
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "OBI-BOT LIVE"

    # Health
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # OBI API
    res = client.get("/api/obi")
    assert res.status_code == 200
    data = res.json()
    assert "BTCUSDT" in data
    assert "ETHUSDT" in data
    assert "XAUUSDT" in data

    # Trades API
    res = client.get("/api/trades")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Balance API
    res = client.get("/api/balance")
    assert res.status_code == 200
    assert res.json()["balance"] == 50000

    # Dashboard HTML
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "OBI-BOT" in res.text
    assert "/static/icon.png" in res.text
    assert "splash" in res.text

    # Static Icon
    res = client.get("/static/icon.png")
    assert res.status_code == 200
