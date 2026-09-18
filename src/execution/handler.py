import time
from typing import Optional, Dict, Any, List
from src.risk.circuit_breaker import CircuitBreaker

class ExecutionHandler:
    def __init__(self, ledger, user_id: str, circuit_breaker: Optional[CircuitBreaker] = None):
        self.ledger = ledger
        self.user_id = user_id
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.active_order: Optional[Dict[str, Any]] = None
        self.orders: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []

    def on_signal(self, I: float, bid1: float, ask1: float, tick_size: float = 1.0, current_time: Optional[float] = None) -> Dict[str, Any]:
        if current_time is None:
            current_time = time.time()

        # Update circuit breaker
        is_paused = self.circuit_breaker.process_tick(bid1, ask1, timestamp=current_time)

        # 1. Process active order if exists
        if self.active_order is not None:
            order_type = self.active_order.get("type", "ENTRY")

            if order_type == "ENTRY":
                # Check toxic cancel
                side = self.active_order["side"]
                if side == "BUY" and I < 0.30:
                    # Cancel buy order
                    reserved = self.active_order.get("reserved_amount", self.active_order["price"] * self.active_order["amount"])
                    self.ledger.release(self.user_id, reserved)
                    self.active_order["status"] = "CANCELLED"
                    self.orders.append(dict(self.active_order))
                    self.active_order = None
                    return {"status": "toxic_cancelled", "active_order": self.active_order}

                elif side == "SELL" and I > -0.30:
                    # Cancel sell order
                    reserved = self.active_order.get("reserved_amount", self.active_order["price"] * self.active_order["amount"])
                    self.ledger.release(self.user_id, reserved)
                    self.active_order["status"] = "CANCELLED"
                    self.orders.append(dict(self.active_order))
                    self.active_order = None
                    return {"status": "toxic_cancelled", "active_order": self.active_order}

                # Check simulated fill for entry order
                price = self.active_order["price"]
                filled = False
                if side == "BUY" and (ask1 <= price or bid1 <= price):
                    filled = True
                elif side == "SELL" and (bid1 >= price or ask1 >= price):
                    filled = True

                if filled:
                    entry_price = price
                    amount = self.active_order["amount"]
                    reserved = self.active_order.get("reserved_amount", price * amount)
                    self.active_order["status"] = "FILLED"
                    self.orders.append(dict(self.active_order))

                    # On fill: place profit target immediately
                    if side == "BUY":
                        tp_side = "SELL"
                        tp_price = entry_price + (1.0 * tick_size)
                        position_side = "LONG"
                    else:
                        tp_side = "BUY"
                        tp_price = entry_price - (1.0 * tick_size)
                        position_side = "SHORT"

                    self.active_order = {
                        "side": tp_side,
                        "price": tp_price,
                        "amount": amount,
                        "entry_time": current_time,
                        "ticks_seen": 0,
                        "type": "PROFIT_TARGET",
                        "entry_price": entry_price,
                        "position_side": position_side,
                        "reserved_amount": reserved,
                        "status": "OPEN"
                    }
                    self.orders.append(dict(self.active_order))
                    return {"status": "filled_and_tp_placed", "active_order": self.active_order}
                else:
                    self.active_order["ticks_seen"] += 1

            elif order_type == "PROFIT_TARGET":
                self.active_order["ticks_seen"] += 1
                tp_side = self.active_order["side"]
                tp_price = self.active_order["price"]
                entry_price = self.active_order["entry_price"]
                amount = self.active_order["amount"]
                position_side = self.active_order["position_side"]
                reserved = self.active_order["reserved_amount"]

                # Check TP fill
                tp_filled = False
                if tp_side == "SELL" and bid1 >= tp_price:
                    tp_filled = True
                elif tp_side == "BUY" and ask1 <= tp_price:
                    tp_filled = True

                if tp_filled:
                    if position_side == "LONG":
                        pnl = (tp_price - entry_price) * amount
                    else:
                        pnl = (entry_price - tp_price) * amount

                    self.ledger.release(self.user_id, reserved)
                    self.ledger.apply_pnl(self.user_id, pnl)

                    trade = {
                        "user_id": self.user_id,
                        "side": position_side,
                        "entry_price": entry_price,
                        "exit_price": tp_price,
                        "pnl": pnl,
                        "type": "PROFIT_TARGET",
                        "timestamp": current_time
                    }
                    self.trades.append(trade)
                    self.active_order["status"] = "FILLED"
                    self.orders.append(dict(self.active_order))
                    self.active_order = None
                    return {"status": "tp_filled", "pnl": pnl, "active_order": self.active_order}
                else:
                    # Check 3 ticks or 800ms condition
                    time_elapsed = current_time - self.active_order["entry_time"]
                    if self.active_order["ticks_seen"] >= 3 or time_elapsed >= 0.8:
                        # Flatten with market IOC
                        if position_side == "LONG":
                            exit_price = bid1
                            pnl = (bid1 - entry_price) * amount
                        else:
                            exit_price = ask1
                            pnl = (entry_price - ask1) * amount

                        self.ledger.release(self.user_id, reserved)
                        self.ledger.apply_pnl(self.user_id, pnl)

                        trade = {
                            "user_id": self.user_id,
                            "side": position_side,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": pnl,
                            "type": "MARKET_IOC_FLATTEN",
                            "timestamp": current_time
                        }
                        self.trades.append(trade)
                        self.active_order["status"] = "FLATTENED"
                        self.orders.append(dict(self.active_order))
                        self.active_order = None
                        return {"status": "flattened", "pnl": pnl, "active_order": self.active_order}

        # 2. If no active order, check signal to place new limit order
        if self.active_order is None and not is_paused:
            amount = 1.0
            if I >= 0.70:
                price = bid1
                required_reserve = price * amount
                try:
                    self.ledger.reserve(self.user_id, required_reserve)
                except ValueError as e:
                    return {"status": "rejected", "reason": str(e), "active_order": None}

                self.active_order = {
                    "side": "BUY",
                    "price": price,
                    "amount": amount,
                    "entry_time": current_time,
                    "ticks_seen": 0,
                    "type": "ENTRY",
                    "reserved_amount": required_reserve,
                    "status": "OPEN"
                }
                self.orders.append(dict(self.active_order))
                return {"status": "buy_order_placed", "active_order": self.active_order}

            elif I <= -0.70:
                price = ask1
                required_reserve = price * amount
                try:
                    self.ledger.reserve(self.user_id, required_reserve)
                except ValueError as e:
                    return {"status": "rejected", "reason": str(e), "active_order": None}

                self.active_order = {
                    "side": "SELL",
                    "price": price,
                    "amount": amount,
                    "entry_time": current_time,
                    "ticks_seen": 0,
                    "type": "ENTRY",
                    "reserved_amount": required_reserve,
                    "status": "OPEN"
                }
                self.orders.append(dict(self.active_order))
                return {"status": "sell_order_placed", "active_order": self.active_order}

        return {"status": "no_action", "active_order": self.active_order}
