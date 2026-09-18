import pytest
import os
import time
from fastapi.testclient import TestClient

from src.money.ledger import Ledger
from src.money.momo_sim import MoMoSim
from src.money.momo_real import MoMoReal
from src.risk.limits import RiskManager
from src.risk.circuit_breaker import CircuitBreaker
from src.alerts.telegram import send_alert, is_telegram_connected
from src.execution.handler import ExecutionHandler
from src.ws_client import WSClient
from src.market_data.obi import get_imbalance, calculate_obi_from_orderbook
from src.app.main import app, risk_manager

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

    # Trades
    ledger.record_trade("user1", "BUY", 50000.0, 0.1, 100.0)
    trades = ledger.get_trades("user1")
    assert len(trades) >= 1
    assert trades[-1]["side"] == "BUY"
    assert trades[-1]["price"] == 50000.0

    pnl = ledger.get_pnl("user1")
    assert isinstance(pnl, float)


def test_momo_sim_and_real(monkeypatch):
    # Simulated MoMo
    sim = MoMoSim()
    pay_res = sim.request_to_pay(1000.0, "256700000000", "EXT-123")
    assert pay_res["status"] == "SUCCESS"
    assert "SIM-" in pay_res["tx_id"]
    status_res = sim.check_status(pay_res["tx_id"])
    assert status_res["status"] == "SUCCESS"

    # MoMoReal without env vars -> Fallback to MoMoSim
    monkeypatch.delenv("MOMO_API_KEY", raising=False)
    monkeypatch.delenv("MOMO_API_SECRET", raising=False)
    real_sim = MoMoReal()
    assert real_sim.use_sim is True
    res = real_sim.request_to_pay(500.0, "256700000000", "EXT-456")
    assert res["status"] == "SUCCESS"

    # MoMoReal with env vars
    monkeypatch.setenv("MOMO_API_KEY", "dummy_key")
    monkeypatch.setenv("MOMO_API_SECRET", "dummy_secret")
    real_live = MoMoReal()
    assert real_live.use_sim is False
    res_live = real_live.request_to_pay(500.0, "256700000000", "EXT-789")
    assert res_live["status"] == "SUCCESS"


def test_circuit_breaker():
    cb = CircuitBreaker()
    assert cb.is_paused() is False

    cb.pause(seconds=1)
    assert cb.is_paused() is True

    time.sleep(1.1)
    assert cb.is_paused() is False

    cb.pause(seconds=100)
    assert cb.is_paused() is True
    cb.reset()
    assert cb.is_paused() is False


def test_risk_manager(ledger):
    rm = RiskManager(max_daily_loss=100.0, max_position=1.0, max_orders_per_min=3)
    ledger.deposit("user_risk", 1000.0)

    # Normal trade check
    assert rm.check_can_trade("user_risk", ledger, position=0.5) is True

    # Daily loss breach check
    ledger.apply_pnl("user_risk", -150.0)
    assert rm.check_can_trade("user_risk", ledger, position=0.5) is False
    assert rm.circuit_breaker.is_paused() is True
    rm.circuit_breaker.reset()

    # Position breach check
    assert rm.check_can_trade("user_risk", ledger, position=1.5) is False
    assert rm.circuit_breaker.is_paused() is True
    rm.circuit_breaker.reset()

    # Rate limit breach check
    ledger.deposit("user_risk", 500.0) # recover PnL impact
    for _ in range(3):
        rm.record_order()
    assert rm.check_can_trade("user_risk", ledger, position=0.0) is False
    assert rm.circuit_breaker.is_paused() is True


def test_telegram_alerts(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert is_telegram_connected() is False
    assert send_alert("Test alert console") is False


def test_ws_client_and_execution_handler(ledger):
    ledger.deposit("user_ws", 10000.0)
    handler = ExecutionHandler(ledger=ledger)
    rm = RiskManager(max_daily_loss=5000.0, max_position=2.0)
    ws = WSClient(risk_manager=rm, execution_handler=handler, ledger=ledger)

    # Orderbook with high bid imbalance (buy signal)
    ob = {
        "bids": [[50000, 10], [49900, 20], [49800, 30]],
        "asks": [[50100, 1], [50200, 1], [50300, 1]]
    }
    res = ws.process_orderbook_message(ob, user_id="user_ws")
    assert res is not None
    assert res["status"] == "FILLED"
    assert res["side"] == "BUY"


def test_fastapi_endpoints():
    if os.path.exists("db.json"):
        os.remove("db.json")

    client = TestClient(app)

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

    # Risk status
    res = client.get("/risk/status")
    assert res.status_code == 200
    assert "circuit_breaker" in res.json()

    # Risk reset
    res = client.post("/risk/reset")
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Export trades CSV
    res = client.get("/export/trades/user2")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "date,side,price,qty,pnl,balance_after" in res.text

    # Dashboard HTML
    res = client.get("/")
    assert res.status_code == 200
    assert "OBI-BOT Dashboard" in res.text

    if os.path.exists("db.json"):
        os.remove("db.json")
