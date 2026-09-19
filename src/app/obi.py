"""
Order Book Imbalance (OBI) & Metrics Calculation Module
"""

def extract_volume(level) -> float:
    if isinstance(level, (int, float)):
        return float(level)
    if isinstance(level, (list, tuple)):
        if len(level) >= 2:
            return float(level[1])
        elif len(level) == 1:
            return float(level[0])
        return 0.0
    if isinstance(level, dict):
        for key in ['volume', 'qty', 'size', 'amount']:
            if key in level:
                return float(level[key])
    return 0.0


def extract_price(level) -> float:
    if isinstance(level, (int, float)):
        return float(level)
    if isinstance(level, (list, tuple)):
        if len(level) >= 1:
            return float(level[0])
        return 0.0
    if isinstance(level, dict):
        for key in ['price', 'p']:
            if key in level:
                return float(level[key])
    return 0.0


def get_imbalance(bids: list, asks: list) -> float:
    """
    Calculate Order Book Imbalance (OBI) using top 3 bids and asks.
    Formula: I = (V_bid - V_ask) / (V_bid + V_ask)
    """
    top_bids = bids[:3] if bids else []
    top_asks = asks[:3] if asks else []

    v_bid = sum(extract_volume(b) for b in top_bids)
    v_ask = sum(extract_volume(a) for a in top_asks)

    total_volume = v_bid + v_ask
    if total_volume == 0:
        return 0.0

    return (v_bid - v_ask) / total_volume


def calculate_obi_from_orderbook(orderbook: dict) -> float:
    """
    Extracts bids and asks from orderbook dict and returns imbalance I.
    """
    if not isinstance(orderbook, dict):
        return 0.0

    bids = orderbook.get('bids', orderbook.get('b', []))
    asks = orderbook.get('asks', orderbook.get('a', []))

    return get_imbalance(bids, asks)


def calculate_orderbook_metrics(orderbook: dict) -> dict:
    """
    Calculates detailed metrics from an orderbook dict:
    - OBI
    - bid_vol (top 3)
    - ask_vol (top 3)
    - best_bid & best_ask
    - mid_price
    - spread (as percentage/ratio: (best_ask - best_bid) / mid_price)
    """
    if not isinstance(orderbook, dict):
        return {
            "obi": 0.0,
            "bid_vol": 0.0,
            "ask_vol": 0.0,
            "best_bid": 0.0,
            "best_ask": 0.0,
            "mid_price": 0.0,
            "spread": 0.0
        }

    bids = orderbook.get('bids', orderbook.get('b', []))
    asks = orderbook.get('asks', orderbook.get('a', []))

    top_bids = bids[:3] if bids else []
    top_asks = asks[:3] if asks else []

    bid_vol = sum(extract_volume(b) for b in top_bids)
    ask_vol = sum(extract_volume(a) for a in top_asks)

    total_vol = bid_vol + ask_vol
    obi = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

    best_bid = extract_price(bids[0]) if bids else 0.0
    best_ask = extract_price(asks[0]) if asks else 0.0

    if best_bid > 0 and best_ask > 0:
        mid_price = (best_bid + best_ask) / 2.0
        spread = (best_ask - best_bid) / mid_price if mid_price > 0 else 0.0
    else:
        mid_price = best_bid or best_ask
        spread = 0.0

    return {
        "obi": float(obi),
        "bid_vol": float(bid_vol),
        "ask_vol": float(ask_vol),
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "mid_price": float(mid_price),
        "spread": float(spread)
    }
