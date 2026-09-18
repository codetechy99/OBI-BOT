def get_imbalance(bids: list, asks: list) -> float:
    """
    Calculate Order Book Imbalance (OBI) using top 3 bids and asks.
    bids: list of [price, volume] or dicts with 'volume' / 'qty' or floats/tuples.
    asks: list of [price, volume] or dicts with 'volume' / 'qty' or floats/tuples.
    Formula: I = (V_bid - V_ask) / (V_bid + V_ask)
    """
    def extract_volume(level):
        if isinstance(level, (int, float)):
            return float(level)
        if isinstance(level, (list, tuple)):
            # typically [price, volume] or (price, volume)
            if len(level) >= 2:
                return float(level[1])
            elif len(level) == 1:
                return float(level[0])
            return 0.0
        if isinstance(level, dict):
            if 'volume' in level:
                return float(level['volume'])
            if 'qty' in level:
                return float(level['qty'])
            if 'size' in level:
                return float(level['size'])
            if 'amount' in level:
                return float(level['amount'])
        return 0.0

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
    orderbook dict format: {'bids': [...], 'asks': [...]}
    """
    if not isinstance(orderbook, dict):
        return 0.0

    bids = orderbook.get('bids', [])
    asks = orderbook.get('asks', [])

    return get_imbalance(bids, asks)
