import pytest
import os
import time
import asyncio
from fastapi.testclient import TestClient

from src.money.ledger import Ledger
from src.market_data.obi import get_imbalance as old_get_imbalance, calculate_obi_from_orderbook as old_calculate_obi
from src.app.obi import get_imbalance, calculate_obi_from_orderbook, calculate_orderbook_metrics
from src.app.signal import SignalEvaluator, Signal
from src.app.risk import RiskManager
from src.app.paper_exec import PaperExecutor, PaperPosition
from src.app.market_data import MarketDataManager, DEFAULT_SYMBOLS
from src.app.main import app

TEST_DB = "test_db.json"


# --- PRESERVED LEDGER TESTS ---
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


# --- PRESERVED OBI TESTS ---
def test_obi_calculations():
    # Basic bids and asks
    bids = [[100, 10], [99, 20], [98, 30], [97, 40]]
    asks = [[101, 5], [102, 5], [103, 10], [104, 10]]

    # V_bid = 10 + 20 + 30 = 60
    # V_ask = 5 + 5 + 10 = 20
    # I = (60 - 20) / (60 + 20) = 40 / 80 = 0.5
    i = get_imbalance(bids, asks)
    assert abs(i - 0.5) < 1e-6
    assert abs(old_get_imbalance(bids, asks) - 0.5) < 1e-6

    # Test dictionary orderbook
    ob = {"bids": bids, "asks": asks}
    i_ob = calculate_obi_from_orderbook(ob)
    assert abs(i_ob - 0.5) < 1e-6
    assert abs(old_calculate_obi(ob) - 0.5) < 1e-6

    # Test metrics calculation
    metrics = calculate_orderbook_metrics(ob)
    assert abs(metrics["obi"] - 0.5) < 1e-6
    assert metrics["bid_vol"] == 60.0
    assert metrics["ask_vol"] == 20.0
    assert metrics["best_bid"] == 100.0
    assert metrics["best_ask"] == 101.0
    assert abs(metrics["mid_price"] - 100.5) < 1e-6
    assert abs(metrics["spread"] - (1.0 / 100.5)) < 1e-6

    # Test empty
    assert get_imbalance([], []) == 0.0
    assert calculate_obi_from_orderbook({}) == 0.0


# --- PRESERVED FASTAPI ENDPOINT TESTS ---
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

    # Insufficient withdraw
    res = client.post("/withdraw", json={"user_id": "user2", "amount": 1000.0})
    assert res.status_code == 400
    assert res.json()["detail"] == "Insufficient balance"

    if os.path.exists("db.json"):
        os.remove("db.json")


# --- NEW HARDENING TESTS ---

def test_default_symbols_verification():
    assert "XAUUSDT" not in DEFAULT_SYMBOLS
    assert "BTCUSDT" in DEFAULT_SYMBOLS
    assert "ETHUSDT" in DEFAULT_SYMBOLS


def test_ws_malformed_message_handling():
    mgr = MarketDataManager(symbols=["BTCUSDT"])

    # Missing bids ('b'/'bids')
    msg1 = '{"asks": [[100, 10]]}'
    assert mgr.parse_message("BTCUSDT", msg1) is None

    # Missing asks ('a'/'asks')
    msg2 = '{"bids": [[100, 10]]}'
    assert mgr.parse_message("BTCUSDT", msg2) is None

    # Malformed non-JSON
    msg3 = 'NOT JSON string'
    assert mgr.parse_message("BTCUSDT", msg3) is None

    # Valid Binance WS depth message with 'b' and 'a'
    valid_msg = '{"b": [["100.0", "10.0"]], "a": [["100.1", "10.0"]], "E": 123456789}'
    parsed = mgr.parse_message("BTCUSDT", valid_msg)
    assert parsed is not None
    assert parsed["symbol"] == "BTCUSDT"
    assert parsed["bids"] == [["100.0", "10.0"]]


def test_stale_data_check():
    mgr = MarketDataManager(symbols=["BTCUSDT"])
    now = 1000.0

    # Process an orderbook update at t = 1000.0
    ob = {"bids": [[100.0, 10.0]], "asks": [[100.05, 10.0]]}
    mgr.process_orderbook("BTCUSDT", ob, timestamp=now)
    assert mgr.symbol_status["BTCUSDT"] == "OK"

    # Check status at t = 1003.0 (3s later -> OK)
    mgr.check_stale_symbols(current_time=1003.0)
    assert mgr.symbol_status["BTCUSDT"] == "OK"

    # Check status at t = 1006.0 (6s later -> STALE)
    mgr.check_stale_symbols(current_time=1006.0)
    assert mgr.symbol_status["BTCUSDT"] == "STALE"


def test_signal_filters_spread_and_volatility():
    evaluator = SignalEvaluator()
    sym = "BTCUSDT"

    # High spread (> 0.1%): best_bid=100, best_ask=101 -> mid=100.5, spread = 1 / 100.5 = 0.995%
    high_spread_ob = {
        "bids": [[100.0, 90.0]],
        "asks": [[101.0, 10.0]]
    }
    # Feed 3 updates
    sig1 = evaluator.evaluate(sym, high_spread_ob, timestamp=100.0)
    sig2 = evaluator.evaluate(sym, high_spread_ob, timestamp=100.1)
    sig3 = evaluator.evaluate(sym, high_spread_ob, timestamp=100.2)
    # Should be rejected by spread filter
    assert sig3 is None

    # Tight spread (< 0.1%): best_bid=100.00, best_ask=100.02 -> mid=100.01, spread = 0.02 / 100.01 = 0.02%
    evaluator_clean = SignalEvaluator()
    tight_spread_ob_high_vol = {
        "bids": [[100.00, 90.0]],
        "asks": [[100.02, 10.0]]
    }
    # Populate price history at t=100 with price=100.01
    evaluator_clean.evaluate(sym, tight_spread_ob_high_vol, timestamp=100.0)
    evaluator_clean.evaluate(sym, tight_spread_ob_high_vol, timestamp=100.1)

    # Now at t=100.5 price jumps to 103.00 (> 2% change in 1 sec)
    jump_ob = {
        "bids": [[103.00, 90.0]],
        "asks": [[103.02, 10.0]]
    }
    sig_vol = evaluator_clean.evaluate(sym, jump_ob, timestamp=100.5)
    # Rejection by volatility pause filter
    assert sig_vol is None


def test_validate_symbols():
    async def _test():
        mgr = MarketDataManager(symbols=["BTCUSDT", "INVALID_SYM"])
        mgr.process_orderbook("BTCUSDT", {"bids": [[50000, 1]], "asks": [[50001, 1]]})
        valid = await mgr.validate_symbols(timeout=0.2)
        assert valid == ["BTCUSDT"]
        assert "INVALID_SYM" not in mgr.symbols

    asyncio.run(_test())


def test_e2e_paper_flow():
    """
    Requirement 10: PAPER-TRADING TEST:
    fake orderbook -> OBI 0.8 for 500ms -> signal generated -> risk check -> paper position -> PnL calc.
    """
    evaluator = SignalEvaluator()
    risk_mgr = RiskManager()
    paper_exec = PaperExecutor()
    sym = "BTCUSDT"

    # Orderbook yielding OBI = (90 - 10) / (90 + 10) = 80 / 100 = 0.8
    # Tight spread: bid 50000.0, ask 50001.0 -> mid 50000.5, spread = 1 / 50000.5 = 0.002% (< 0.1%)
    high_obi_ob = {
        "bids": [[50000.0, 90.0]],
        "asks": [[50001.0, 10.0]]
    }

    t0 = 1000.0
    # Simulate 5 consecutive 100ms updates over 500ms
    signals = []
    for i in range(5):
        t = t0 + (i * 0.1)
        sig = evaluator.evaluate(sym, high_obi_ob, timestamp=t)
        if sig:
            signals.append(sig)

    # 1. Verify signal is generated (from update 3 onwards due to persistence)
    assert len(signals) >= 1
    signal = signals[-1]

    assert isinstance(signal, Signal)
    assert signal.symbol == "BTCUSDT"
    assert signal.side == "LONG"
    assert abs(signal.obi - 0.8) < 1e-6
    assert signal.strength == 0.8
    assert signal.expires_at == signal.timestamp + 5.0

    # 2. Risk check
    risk_passed = risk_mgr.check_risk(signal, requested_size=1.0, current_time=t0 + 0.4)
    assert risk_passed is True

    # 3. Paper position
    position = paper_exec.execute_paper_trade(signal, size=1.0, timestamp=t0 + 0.4)
    assert isinstance(position, PaperPosition)
    assert position.symbol == "BTCUSDT"
    assert position.side == "LONG"
    assert position.entry_price == 50000.5
    assert position.status == "OPEN"

    # 4. PnL calculation
    # Price rises to 50100.5 -> PnL for LONG 1.0 unit = 50100.5 - 50000.5 = +100.0
    current_price = 50100.5
    pnl = paper_exec.calculate_pnl(position, current_price)
    assert pnl == 100.0

    closed_position = paper_exec.close_position(position.id, exit_price=current_price, timestamp=t0 + 1.0)
    assert closed_position.status == "CLOSED"
    assert closed_position.pnl == 100.0
