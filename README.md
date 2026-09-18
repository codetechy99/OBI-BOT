# OBI-BOT

OBI-BOT is a custom Direct Market Access (DMA) application built without third-party broker dependencies. It includes an internal money handling system (ledger), an Order Book Imbalance (OBI) strategy module, real MTN MoMo integration, risk controls, Telegram alerts, and containerized production deployment.

## Architecture & Features

1. **Money Ledger (`src/money/ledger.py`)**
   - Internal simulated payment system storing account state in `db.json`.
   - Supports creating accounts, deposits (e.g., via MoMo), withdrawals, PnL updates, trade records, and CSV trade export for tax compliance (URA).

2. **MTN MoMo Integration (`src/money/momo_real.py` & `src/money/momo_sim.py`)**
   - Class `MoMoReal` interacts with the MTN MoMo API.
   - Configured via environment variables: `MOMO_API_KEY`, `MOMO_API_SECRET`, and `MOMO_ENV` (`sandbox` or `production`).
   - If API credentials are not set, it transparently falls back to `MoMoSim` (`src/money/momo_sim.py`) while logging all operations.

3. **Risk Management (`src/risk/limits.py` & `src/risk/circuit_breaker.py`)**
   - Class `RiskManager` enforces trade safety thresholds:
     - **Max Daily Loss**: `100,000 UGX`
     - **Max Position**: `1 BTC`
     - **Max Orders per Minute**: `10 orders/min`
   - Class `CircuitBreaker`: Automatically triggers a 5-minute (300 seconds) pause upon any risk breach. Can be manually reset via `POST /risk/reset`.
   - Risk events and breaches are logged locally in `data/risk.log`.

4. **Telegram Alerts (`src/alerts/telegram.py`)**
   - Provides real-time notifications for:
     - Order placed / Order filled
     - Toxic cancel triggered
     - Circuit breaker triggered
     - Deposit confirmed
   - Configured via `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Falls back to console output if unset.

5. **FastAPI Application & Dashboard (`src/app/main.py` & `src/app/templates/dashboard.html`)**
   - Interactive HTML Dashboard at `GET /` or `GET /dashboard`.
   - REST API endpoints:
     - `GET /balance/{user_id}`: Retrieve account balance.
     - `POST /deposit`: Deposit funds into ledger.
     - `POST /withdraw`: Withdraw funds.
     - `GET /export/trades/{user_id}`: Download CSV of trade history (`date,side,price,qty,pnl,balance_after`).
     - `GET /risk/status`: Fetch RiskManager and CircuitBreaker status.
     - `POST /risk/reset`: Manually unpause the circuit breaker.

---

## Getting Started

### Prerequisites
Install dependencies:
```bash
pip install -r requirements.txt
```

### Environment Configuration
Copy `.env.example` to `.env` and fill in your configuration:
```bash
cp .env.example .env
```

Example `.env` settings:
```env
MOMO_API_KEY=your_momo_api_key
MOMO_API_SECRET=your_momo_api_secret
MOMO_ENV=sandbox
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyZ
TELEGRAM_CHAT_ID=987654321
BINANCE_WS=wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms
```

### Running Locally
Start the FastAPI server with Uvicorn:
```bash
uvicorn src.app.main:app --reload
```
Open `http://localhost:8000` in your browser to view the dashboard.

---

## Telegram Setup
1. Create a bot by messaging [@BotFather](https://t.me/BotFather) on Telegram and copy your HTTP API token into `TELEGRAM_BOT_TOKEN`.
2. Get your personal or group Chat ID by messaging [@userinfobot](https://t.me/userinfobot) or using Telegram API, and set `TELEGRAM_CHAT_ID`.
3. If no tokens are set, alerts will log to stdout without throwing errors.

---

## Production Deployment (Render / Railway / VPS)

### Using Docker Compose
To deploy on a VPS or cloud host with Docker Compose:
```bash
docker-compose up -d --build
```

### Deploying to Render / Railway
1. **Render**: Create a new **Web Service**, connect your Git repository, choose **Docker** as the runtime, and add environment variables from `.env`.
2. **Railway**: Deploy directly from Git repo using the included `Dockerfile`. Mount persistent volume at `/app/data` to preserve trade databases and risk logs.

---

## Testing
Run the test suite using pytest:
```bash
python3 -m pytest
```
