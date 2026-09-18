import pytest
import os
import time
from fastapi.testclient import TestClient

from src.money.ledger import Ledger
from src.market_data.obi import get_imbalance, calculate_obi_from_orderbook
from src.risk.circuit_breaker import CircuitBreaker
from src.execution.handler import ExecutionHandler
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

    # Reserve & Release
    ledger.reserve("user1", 50.0)
    assert ledger.get_reserved("user1") == 50.0
    assert ledger.get_available_balance("user1") == 100.0

    # Withdraw cannot withdraw reserved funds
    with pytest.raises(ValueError, match="Insufficient balance"):
        ledger.withdraw("user1", 120.0)

    # Cannot reserve more than available
    with pytest.raises(ValueError, match="Insufficient balance to reserve"):
        ledger.reserve("user1", 150.0)

    ledger.release("user1", 50.0)
    assert ledger.get_reserved("user1") == 0.0
    assert ledger.get_available_balance("user1") == 150.0

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
    assert len(history) > 0


def test_obi_calculations():
    bids = [[100, 10], [99, 20], [98, 30], [97, 40]]
    asks = [[101, 5], [102, 5], [103, 10], [104, 10]]

    i = get_imbalance(bids, asks)
    assert abs(i - 0.5) < 1e-6

    ob = {"bids": bids, "asks": asks}
    i_ob = calculate_obi_from_orderbook(ob)
    assert abs(i_ob - 0.5) < 1e-6

    assert get_imbalance([], []) == 0.0
    assert calculate_obi_from_orderbook({}) == 0.0


def test_circuit_breaker():
    cb = CircuitBreaker(spread_threshold=5.0, std_multiplier=3.0, pause_duration=5.0)
    now = 1000.0

    # Normal tick
    paused = cb.process_tick(bid1=100.0, ask1=101.0, timestamp=now)
    assert not paused
    assert not cb.should_pause(now)

    # Spread > threshold triggers pause
    paused = cb.process_tick(bid1=100.0, ask1=107.0, timestamp=now + 1.0)
    assert paused
    assert cb.should_pause(now + 2.0)
    assert not cb.should_pause(now + 6.1)

    # Frequency spike check
    cb2 = CircuitBreaker(spread_threshold=20.0, std_multiplier=3.0, pause_duration=5.0)
    # Establish baseline frequency (dt = 1.0 -> freq = 1.0)
    t = 2000.0
    for i in range(10):
        cb2.process_tick(100.0, 101.0, timestamp=t + i * 1.0)
    assert not cb2.should_pause(t + 9.0)

    # Sudden fast tick (dt = 0.001 -> freq = 1000)
    cb2.process_tick(100.0, 101.0, timestamp=t + 9.001)
    assert cb2.should_pause(t + 9.002)


def test_execution_handler_long_trade(ledger):
    ledger.deposit("user_long", 1000.0)
    cb = CircuitBreaker(spread_threshold=20.0)
    handler = ExecutionHandler(ledger, "user_long", circuit_breaker=cb)

    now = 100.0
    # 1. Buy signal I >= 0.70
    res = handler.on_signal(I=0.75, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now)
    assert res["status"] == "buy_order_placed"
    assert handler.active_order["side"] == "BUY"
    assert handler.active_order["price"] == 100.0
    assert ledger.get_reserved("user_long") == 100.0

    # 2. Next tick, price touches 100 -> Fills BUY order and places PROFIT TARGET
    res = handler.on_signal(I=0.70, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now + 0.1)
    assert res["status"] == "filled_and_tp_placed"
    assert handler.active_order["type"] == "PROFIT_TARGET"
    assert handler.active_order["side"] == "SELL"
    assert handler.active_order["price"] == 101.0  # entry + 1 tick

    # 3. Next tick, price reaches 101 -> TP fills!
    res = handler.on_signal(I=0.50, bid1=101.0, ask1=102.0, tick_size=1.0, current_time=now + 0.2)
    assert res["status"] == "tp_filled"
    assert res["pnl"] == 1.0
    assert handler.active_order is None
    assert ledger.get_reserved("user_long") == 0.0
    assert ledger.get_balance("user_long") == 1001.0
    assert len(handler.trades) == 1


def test_execution_handler_toxic_cancel(ledger):
    ledger.deposit("user_toxic", 1000.0)
    handler = ExecutionHandler(ledger, "user_toxic")

    now = 100.0
    # Buy signal
    handler.on_signal(I=0.80, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now)
    assert handler.active_order["side"] == "BUY"
    assert ledger.get_reserved("user_toxic") == 100.0

    # Toxic cancel signal I < 0.30 before fill
    res = handler.on_signal(I=0.20, bid1=100.5, ask1=101.5, tick_size=1.0, current_time=now + 0.1)
    assert res["status"] == "toxic_cancelled"
    assert handler.active_order is None
    assert ledger.get_reserved("user_toxic") == 0.0


def test_execution_handler_flatten_timeout(ledger):
    ledger.deposit("user_timeout", 1000.0)
    handler = ExecutionHandler(ledger, "user_timeout")

    now = 100.0
    # 1. Buy signal
    handler.on_signal(I=0.80, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now)
    # 2. Fill entry
    handler.on_signal(I=0.80, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now + 0.1)
    assert handler.active_order["type"] == "PROFIT_TARGET"

    # 3. Tick 1 seen
    handler.on_signal(I=0.50, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now + 0.2)
    # 4. Tick 2 seen
    handler.on_signal(I=0.50, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now + 0.3)
    # 5. Tick 3 seen -> not filled in 3 ticks -> flatten with market IOC at bid1 (100.0)
    res = handler.on_signal(I=0.50, bid1=100.0, ask1=101.0, tick_size=1.0, current_time=now + 0.4)
    assert res["status"] == "flattened"
    assert res["pnl"] == 0.0
    assert handler.active_order is None
    assert ledger.get_reserved("user_timeout") == 0.0


def test_fastapi_endpoints():
    if os.path.exists("db.json"):
        os.remove("db.json")

    client = TestClient(app)

    # Deposit via API
    res = client.post("/deposit", json={"user_id": "api_user", "amount": 500.0})
    assert res.status_code == 200

    # Post signal
    res = client.post("/signal", json={"user_id": "api_user", "I": 0.75, "bid1": 100.0, "ask1": 101.0})
    assert res.status_code == 200
    assert res.json()["status"] == "buy_order_placed"

    # Get orders
    res = client.get("/orders/api_user")
    assert res.status_code == 200
    assert res.json()["active_order"]["side"] == "BUY"

    # Fill and TP
    res = client.post("/signal", json={"user_id": "api_user", "I": 0.75, "bid1": 100.0, "ask1": 101.0})
    assert res.json()["status"] == "filled_and_tp_placed"

    # Get trades (empty before TP fill)
    res = client.get("/trades/api_user")
    assert res.status_code == 200
    assert len(res.json()["trades"]) == 0

    # Fill TP
    res = client.post("/signal", json={"user_id": "api_user", "I": 0.50, "bid1": 101.0, "ask1": 102.0})
    assert res.json()["status"] == "tp_filled"

    # Get trades (should contain 1 completed trade)
    res = client.get("/trades/api_user")
    assert res.status_code == 200
    assert len(res.json()["trades"]) == 1

    if os.path.exists("db.json"):
        os.remove("db.json")
