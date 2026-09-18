import os
import pytest
import asyncio
from fastapi.testclient import TestClient

from src.money.ledger import Ledger
from src.money.momo_sim import MoMoSim
from src.market_data.obi import get_imbalance, calculate_obi_from_orderbook
from src.risk.circuit_breaker import CircuitBreaker
from src.execution.execution_handler import ExecutionHandler
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

def test_ledger_reserve_release(ledger):
    ledger.create_account("user1")
    ledger.deposit("user1", 200.0)

    assert ledger.get_balance("user1") == 200.0
    assert ledger.get_reserved_balance("user1") == 0.0
    assert ledger.get_available_balance("user1") == 200.0

    # Reserve 100
    assert ledger.reserve("user1", 100.0) is True
    assert ledger.get_reserved_balance("user1") == 100.0
    assert ledger.get_available_balance("user1") == 100.0

    # Reserve more than available -> fails
    assert ledger.reserve("user1", 150.0) is False

    # Release 50
    assert ledger.release("user1", 50.0) is True
    assert ledger.get_reserved_balance("user1") == 50.0
    assert ledger.get_available_balance("user1") == 150.0

def test_momo_sim(ledger):
    momo = MoMoSim(ledger)

    async def run_test():
        req = await momo.request_deposit("user_momo", 300.0, "256700000000")
        assert req["status"] == "pending"
        assert ledger.get_balance("user_momo") == 0.0

        await asyncio.sleep(2.1)
        assert momo.transactions[req["transaction_id"]]["status"] == "confirmed"
        assert ledger.get_balance("user_momo") == 300.0

    asyncio.run(run_test())

def test_circuit_breaker():
    assert CircuitBreaker.should_pause() is False
    CircuitBreaker.set_paused(True)
    assert CircuitBreaker.should_pause() is True
    CircuitBreaker.set_paused(False)

def test_execution_handler(ledger):
    ledger.create_account("exec_user")
    ledger.deposit("exec_user", 500.0)

    handler = ExecutionHandler(ledger, default_user_id="exec_user", order_size=100.0, obi_threshold=0.5)

    # Weak signal -> no order
    handler.on_signal(0.2, 50000.0, 50001.0)
    assert handler.active_order is None

    # Strong buy signal -> order placed
    handler.on_signal(0.7, 50000.0, 50001.0)
    assert handler.active_order is not None
    assert handler.active_order["side"] == "BUY"
    assert handler.active_order["price"] == 50000.0
    assert ledger.get_reserved_balance("exec_user") == 100.0

    # Price moves to fill buy order (best_ask <= order price)
    handler.on_signal(0.1, 49999.0, 50000.0)
    assert handler.active_order is None
    assert len(handler.trades) == 1
    assert handler.trades[0]["status"] == "FILLED"
    assert ledger.get_reserved_balance("exec_user") == 0.0

def test_fastapi_dashboard_endpoints():
    if os.path.exists("db.json"):
        os.remove("db.json")

    client = TestClient(app)

    # Dashboard HTML
    res = client.get("/")
    assert res.status_code == 200
    assert "OBI-BOT DMA Dashboard" in res.text

    # Live OBI endpoint
    res = client.get("/live/obi")
    assert res.status_code == 200
    assert "I" in res.json()

    # MoMo deposit endpoint
    res = client.post("/momo/deposit", json={"user_id": "test_momo", "amount": 100.0, "phone": "256712345678"})
    assert res.status_code == 200
    assert res.json()["status"] == "pending"

    # Dashboard data endpoint
    res = client.get("/dashboard/data/test_momo")
    assert res.status_code == 200
    data = res.json()
    assert "balance" in data
    assert "reserved" in data
    assert "active_order" in data

    if os.path.exists("db.json"):
        os.remove("db.json")
