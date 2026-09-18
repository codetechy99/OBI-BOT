# OBI-BOT

OBI-BOT is a custom Direct Market Access (DMA) application built without third-party broker dependencies. It includes an internal money handling system (ledger), an Order Book Imbalance (OBI) strategy module, live WebSocket streaming from Binance, MoMo payment simulation, and a dark-theme web dashboard.

## Architecture & Features

1. **Money Ledger (`src/money/ledger.py`)**
   - Internal simulated payment system storing account state in `db.json`.
   - Supports creating accounts, deposits (e.g., via MoMo), withdrawals, funds reservation & release for active orders, PnL updates, and transaction history.

2. **Mobile Money Simulator (`src/money/momo_sim.py`)**
   - Simulates Uganda MoMo deposits with pending-to-confirmed asynchronous workflow (2-second confirmation).

3. **Market Data & OBI WebSocket Client (`src/market_data/ws_client.py`)**
   - Asynchronously streams L2 orderbook data from Binance (`wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms`).
   - Calculates Order Book Imbalance $I$:
     $$I = \frac{V_{bid} - V_{ask}}{V_{bid} + V_{ask}}$$
   - Logs ticks with timestamp, OBI value, and top bid/ask to `data/ticks.log`.
   - Integrates `CircuitBreaker` pause checking before triggering order execution signals.

4. **Execution Handler (`src/execution/execution_handler.py`)**
   - Checks ledger available balance and reserves funds before placing limit orders upon strong OBI signals.
   - Simulates order fills and cancels, releasing reserves and updating account PnL.

5. **FastAPI Application & Live Dashboard (`src/app/main.py`)**
   - Serves dark-theme HTML dashboard at `GET /` (`src/app/templates/dashboard.html`).
   - `GET /live/obi`: Live OBI value, best bid, best ask, and timestamp.
   - `POST /momo/deposit`: Initiates simulated MoMo deposit.
   - `GET /dashboard/data/{user_id}`: Account balance, reserved/available funds, active orders, trade history, and total PnL.

## Getting Started

### Prerequisites
Install dependencies:
```bash
pip install -r requirements.txt
```

### Running the Application
Start the uvicorn server:
```bash
python -m uvicorn src.app.main:app --reload
```
Then open [http://localhost:8000](http://localhost:8000) in your web browser.

### Running Tests
Execute pytest suite:
```bash
PYTHONPATH=. pytest
```
