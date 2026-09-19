# OBI-BOT

OBI-BOT is a custom Direct Market Access (DMA) application built without third-party broker dependencies. It includes an internal money handling system (ledger) and an Order Book Imbalance (OBI) strategy module.

## Architecture & Features

1. **Money Ledger (`src/money/ledger.py`)**
   - Internal simulated payment system storing account state in `db.json`.
   - Supports creating accounts, deposits (e.g., via MoMo), withdrawals with insufficient balance protection, PnL updates, and transaction history.

2. **Market Data & OBI (`src/market_data/obi.py`)**
   - Implements Order Book Imbalance calculation based on top 3 bid and ask levels:
     $$I = \frac{V_{bid} - V_{ask}}{V_{bid} + V_{ask}}$$
     where $V_{bid}$ is the sum of volumes of the top 3 bids and $V_{ask}$ is the sum of volumes of the top 3 asks.
   - If total volume ($V_{bid} + V_{ask}$) is zero, $I = 0$.

3. **FastAPI Application (`src/app/main.py`)**
   - Provides HTTP endpoints for managing funds:
     - `GET /balance/{user_id}`
     - `POST /deposit` (`{"user_id": "...", "amount": 100, "method": "MoMo"}`)
     - `POST /withdraw` (`{"user_id": "...", "amount": 50}`)

## Live Server
Connected to Render. Auto-deploy on push to main.
- Live: https://obi-bot.onrender.com
- Dashboard: /dashboard
- Health: /health
- To edit after deploy: just push to GitHub via Jules, Render auto-redeploys in ~2min. No need to touch Render.

## Getting Started

### Prerequisites
Install dependencies:
```bash
pip install -r requirements.txt
```

### Running the API Server
Start the FastAPI app with uvicorn:
```bash
uvicorn src.app.main:app --reload
```
