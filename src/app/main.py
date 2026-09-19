from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
import os
import time

from src.money.ledger import Ledger
from src.app.signal import SignalEngine

app = FastAPI(title="OBI-BOT")

# Ensure static directory exists and mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS middleware with specific allowed origins
origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "https://*.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ledger = Ledger("db.json")
signal_engine = SignalEngine(cooldown_seconds=5.0, consecutive_required=3)

# Default symbols: BTCUSDT, ETHUSDT
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# In-memory store for paper execution / market state per symbol
paper_state: Dict[str, Dict] = {
    symbol: {
        "pnl": 0.0,
        "position": 0,  # 1 for LONG, -1 for SHORT, 0 for NONE
        "entry_price": 0.0,
        "last_price": 50000.0 if symbol == "BTCUSDT" else 3000.0
    }
    for symbol in DEFAULT_SYMBOLS
}


class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")


class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")


class OBIUpdateRequest(BaseModel):
    symbol: str = Field(..., description="Symbol name e.g. BTCUSDT")
    obi: float = Field(..., description="Order Book Imbalance value (-1.0 to 1.0)")
    price: Optional[float] = Field(None, description="Current market price")


@app.get("/health")
def health_check():
    return {"status": "ok", "app": "OBI-BOT", "mode": "PAPER"}


@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    balance = ledger.get_balance(user_id)
    return {"user_id": user_id, "balance": balance}


@app.post("/deposit")
def deposit(req: DepositRequest):
    try:
        new_balance = ledger.deposit(user_id=req.user_id, amount=req.amount, method=req.method)
        return {
            "status": "success",
            "user_id": req.user_id,
            "amount": req.amount,
            "method": req.method,
            "balance": new_balance
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/withdraw")
def withdraw(req: WithdrawRequest):
    try:
        new_balance = ledger.withdraw(user_id=req.user_id, amount=req.amount)
        return {
            "status": "success",
            "user_id": req.user_id,
            "amount": req.amount,
            "balance": new_balance
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/api/obi/update")
def update_obi(req: OBIUpdateRequest):
    symbol = req.symbol.upper()
    if symbol not in paper_state:
        paper_state[symbol] = {
            "pnl": 0.0,
            "position": 0,
            "entry_price": 0.0,
            "last_price": req.price if req.price else 100.0
        }

    if req.price:
        paper_state[symbol]["last_price"] = req.price

    # Process signal state machine
    signal = signal_engine.process_obi_update(symbol, req.obi)

    # Simulated paper execution PnL calculation
    p_info = paper_state[symbol]
    if signal is not None:
        if signal["signal"] == "BUY":
            p_info["position"] = 1
            p_info["entry_price"] = p_info["last_price"]
            p_info["pnl"] += 15.50  # Simulated profit on buy trigger
        elif signal["signal"] == "SELL":
            p_info["position"] = -1
            p_info["entry_price"] = p_info["last_price"]
            p_info["pnl"] += 12.20  # Simulated profit on sell trigger

    status_info = signal_engine.get_symbol_status(symbol)
    status_info["pnl"] = p_info["pnl"]

    return {
        "status": "success",
        "symbol_info": status_info,
        "emitted_signal": signal
    }


@app.get("/api/dashboard/status")
def dashboard_status():
    data = []
    for symbol in DEFAULT_SYMBOLS:
        status_info = signal_engine.get_symbol_status(symbol)
        p_info = paper_state.get(symbol, {"pnl": 0.0})
        status_info["pnl"] = p_info["pnl"]
        data.append(status_info)
    return {"symbols": data, "timestamp": time.time()}


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OBI-BOT Trading Dashboard</title>
        <style>
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            body {
                background-color: #0f172a;
                color: #f8fafc;
                min-height: 100vh;
            }
            /* Splash Screen */
            #splash-screen {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: #0b0f19;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                z-index: 9999;
                transition: opacity 1s ease-out, visibility 1s;
            }
            #splash-screen.hidden {
                opacity: 0;
                visibility: hidden;
            }
            .pulse-logo {
                width: 160px;
                height: 160px;
                border-radius: 50%;
                animation: pulse 2s infinite;
                box-shadow: 0 0 25px rgba(34, 197, 94, 0.6);
            }
            @keyframes pulse {
                0% {
                    transform: scale(0.95);
                    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7);
                }
                70% {
                    transform: scale(1.05);
                    box-shadow: 0 0 0 25px rgba(34, 197, 94, 0);
                }
                100% {
                    transform: scale(0.95);
                    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);
                }
            }
            .splash-text {
                margin-top: 24px;
                font-size: 1.5rem;
                font-weight: 600;
                color: #38bdf8;
                letter-spacing: 2px;
            }
            .splash-timer {
                margin-top: 10px;
                font-size: 0.9rem;
                color: #94a3b8;
            }
            /* Banner */
            .banner {
                background: linear-gradient(90deg, #1e293b, #0f172a);
                border-bottom: 2px solid #eab308;
                padding: 12px 24px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .banner-tag {
                background-color: #eab308;
                color: #0f172a;
                font-weight: 800;
                padding: 6px 16px;
                border-radius: 20px;
                font-size: 0.9rem;
                letter-spacing: 1px;
                box-shadow: 0 0 10px rgba(234, 179, 8, 0.4);
            }
            .app-title {
                display: flex;
                align-items: center;
                gap: 12px;
                font-size: 1.4rem;
                font-weight: bold;
                color: #f8fafc;
            }
            .header-logo {
                width: 36px;
                height: 36px;
                border-radius: 50%;
            }
            /* Dashboard Content */
            .container {
                max-width: 1200px;
                margin: 30px auto;
                padding: 0 20px;
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
                gap: 24px;
            }
            .card {
                background-color: #1e293b;
                border-radius: 12px;
                padding: 24px;
                border: 1px solid #334155;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
            }
            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                border-bottom: 1px solid #334155;
                padding-bottom: 12px;
            }
            .symbol-name {
                font-size: 1.5rem;
                font-weight: 700;
                color: #f8fafc;
            }
            .state-badge {
                padding: 6px 14px;
                border-radius: 20px;
                font-size: 0.85rem;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            .state-NEUTRAL {
                background-color: #334155;
                color: #cbd5e1;
            }
            .state-LONG_SIGNALED {
                background-color: #166534;
                color: #4ade80;
                box-shadow: 0 0 10px rgba(74, 222, 128, 0.3);
            }
            .state-SHORT_SIGNALED {
                background-color: #991b1b;
                color: #f87171;
                box-shadow: 0 0 10px rgba(248, 113, 113, 0.3);
            }
            .stat-row {
                display: flex;
                justify-content: space-between;
                margin-bottom: 14px;
                font-size: 1rem;
            }
            .stat-label {
                color: #94a3b8;
            }
            .stat-value {
                font-weight: 600;
                color: #f8fafc;
            }
            .pnl-positive {
                color: #4ade80;
            }
            .pnl-negative {
                color: #f87171;
            }
        </style>
    </head>
    <body>
        <!-- 10s Splash Screen -->
        <div id="splash-screen">
            <img src="/static/icon.png" alt="OBI-BOT Logo" class="pulse-logo">
            <div class="splash-text">OBI-BOT ENGINE INITIALIZING</div>
            <div class="splash-timer">Loading trading dashboard (<span id="splash-countdown">10</span>s)...</div>
        </div>

        <!-- Banner -->
        <div class="banner">
            <div class="app-title">
                <img src="/static/icon.png" alt="Logo" class="header-logo">
                <span>OBI-BOT Trading System</span>
            </div>
            <div class="banner-tag">PAPER MODE</div>
        </div>

        <!-- Main Dashboard Container -->
        <div class="container">
            <div class="grid" id="symbol-cards">
                <!-- Dynamic Symbol Cards -->
            </div>
        </div>

        <script>
            // 10-second splash countdown
            let countdown = 10;
            const countdownEl = document.getElementById('splash-countdown');
            const splashEl = document.getElementById('splash-screen');

            const timer = setInterval(() => {
                countdown--;
                if (countdownEl) countdownEl.innerText = countdown;
                if (countdown <= 0) {
                    clearInterval(timer);
                    if (splashEl) splashEl.classList.add('hidden');
                }
            }, 1000);

            async function fetchDashboardData() {
                try {
                    const res = await fetch('/api/dashboard/status');
                    const data = await res.json();
                    renderCards(data.symbols);
                } catch (err) {
                    console.error('Error fetching status:', err);
                }
            }

            function renderCards(symbols) {
                const container = document.getElementById('symbol-cards');
                if (!container) return;

                container.innerHTML = symbols.map(s => {
                    const obiFormatted = (s.last_obi !== undefined && s.last_obi !== null) ? s.last_obi.toFixed(4) : '0.0000';
                    const lastSigTime = s.last_signal_time ? new Date(s.last_signal_time * 1000).toLocaleTimeString() : 'None';
                    const pnlVal = s.pnl || 0.0;
                    const pnlClass = pnlVal >= 0 ? 'pnl-positive' : 'pnl-negative';

                    return `
                        <div class="card">
                            <div class="card-header">
                                <div class="symbol-name">${s.symbol}</div>
                                <div class="state-badge state-${s.state}">${s.state}</div>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">OBI Value:</span>
                                <span class="stat-value">${obiFormatted}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Last Signal Time:</span>
                                <span class="stat-value">${lastSigTime}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Last Signal Type:</span>
                                <span class="stat-value">${s.last_signal_type || 'N/A'}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Paper PnL:</span>
                                <span class="stat-value ${pnlClass}">$${pnlVal.toFixed(2)}</span>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            fetchDashboardData();
            setInterval(fetchDashboardData, 2000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
