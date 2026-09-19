import pytest
import time
from src.app.signal import SignalStateMachine, SignalEngine


def test_10_updates_with_obi_0_8_produces_only_1_signal():
    sm = SignalStateMachine("BTCUSDT", cooldown_seconds=5.0, consecutive_required=3)

    signals = []
    base_time = 1000.0

    # Feed 10 consecutive updates with OBI = 0.8
    for i in range(10):
        sig = sm.update(0.8, current_time=base_time + i)
        if sig is not None:
            signals.append(sig)

    # Must produce exactly 1 signal
    assert len(signals) == 1
    assert signals[0]["symbol"] == "BTCUSDT"
    assert signals[0]["signal"] == "BUY"
    assert signals[0]["state"] == SignalStateMachine.STATE_LONG_SIGNALED
    assert sm.state == SignalStateMachine.STATE_LONG_SIGNALED


def test_long_state_transitions():
    sm = SignalStateMachine("BTCUSDT", cooldown_seconds=5.0, consecutive_required=3)
    t = 1000.0

    # Updates 1 & 2: OBI = 0.8 (Neutral)
    assert sm.update(0.8, current_time=t) is None
    assert sm.state == SignalStateMachine.STATE_NEUTRAL

    assert sm.update(0.8, current_time=t + 1) is None
    assert sm.state == SignalStateMachine.STATE_NEUTRAL

    # Update 3: OBI = 0.8 -> Triggers BUY
    sig = sm.update(0.8, current_time=t + 2)
    assert sig is not None
    assert sig["signal"] == "BUY"
    assert sm.state == SignalStateMachine.STATE_LONG_SIGNALED

    # Update 4: OBI = 0.6 (> 0.5) -> Remains LONG_SIGNALED
    sig2 = sm.update(0.6, current_time=t + 3)
    assert sig2 is None
    assert sm.state == SignalStateMachine.STATE_LONG_SIGNALED

    # Update 5: OBI = 0.4 (< 0.5) -> Transitions back to NEUTRAL
    sig3 = sm.update(0.4, current_time=t + 4)
    assert sig3 is None
    assert sm.state == SignalStateMachine.STATE_NEUTRAL


def test_short_state_transitions():
    sm = SignalStateMachine("ETHUSDT", cooldown_seconds=5.0, consecutive_required=3)
    t = 1000.0

    # 3 consecutive OBI = -0.8
    assert sm.update(-0.8, current_time=t) is None
    assert sm.update(-0.8, current_time=t + 1) is None
    sig = sm.update(-0.8, current_time=t + 2)

    assert sig is not None
    assert sig["signal"] == "SELL"
    assert sm.state == SignalStateMachine.STATE_SHORT_SIGNALED

    # OBI = -0.6 (still < -0.5) -> Remains SHORT_SIGNALED
    assert sm.update(-0.6, current_time=t + 3) is None
    assert sm.state == SignalStateMachine.STATE_SHORT_SIGNALED

    # OBI = -0.4 (> -0.5) -> NEUTRAL
    assert sm.update(-0.4, current_time=t + 4) is None
    assert sm.state == SignalStateMachine.STATE_NEUTRAL


def test_cooldown_and_retrigger():
    sm = SignalStateMachine("BTCUSDT", cooldown_seconds=5.0, consecutive_required=3)
    t = 1000.0

    # Trigger BUY at t=1002
    sm.update(0.8, t)
    sm.update(0.8, t + 1)
    sig1 = sm.update(0.8, t + 2)
    assert sig1 is not None  # Emitted at t=1002

    # Drop OBI to 0.1 to reset state to NEUTRAL at t=1003
    sm.update(0.1, t + 3)
    assert sm.state == SignalStateMachine.STATE_NEUTRAL

    # Immediately feed OBI > 0.7 for 3 updates at t=1004, 1005, 1006
    sm.update(0.8, t + 4)
    sm.update(0.8, t + 5)
    sig2 = sm.update(0.8, t + 6)

    # At t=1006, cooldown since last signal (1002) is 4s < 5s -> should NOT emit signal
    assert sig2 is None
    assert sm.state == SignalStateMachine.STATE_NEUTRAL

    # Next update at t=1008 (6s > 5s cooldown)
    sig3 = sm.update(0.8, t + 8)
    assert sig3 is not None
    assert sig3["signal"] == "BUY"
    assert sm.state == SignalStateMachine.STATE_LONG_SIGNALED


def test_signal_engine_multi_symbol():
    engine = SignalEngine(cooldown_seconds=5.0, consecutive_required=3)
    t = 1000.0

    # Symbol BTCUSDT
    for i in range(3):
        res = engine.process_obi_update("BTCUSDT", 0.8, current_time=t + i)
        if i < 2:
            assert res is None
        else:
            assert res["symbol"] == "BTCUSDT"
            assert res["signal"] == "BUY"

    # Symbol ETHUSDT
    for i in range(3):
        res = engine.process_obi_update("ETHUSDT", -0.9, current_time=t + i)
        if i < 2:
            assert res is None
        else:
            assert res["symbol"] == "ETHUSDT"
            assert res["signal"] == "SELL"

    btc_status = engine.get_symbol_status("BTCUSDT")
    eth_status = engine.get_symbol_status("ETHUSDT")

    assert btc_status["state"] == SignalStateMachine.STATE_LONG_SIGNALED
    assert eth_status["state"] == SignalStateMachine.STATE_SHORT_SIGNALED
