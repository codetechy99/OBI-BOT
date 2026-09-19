from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from contextlib import asynccontextmanager
import os
import asyncio

from src.money.ledger import Ledger
from src.app.market_data import MarketDataManager, DEFAULT_SYMBOLS
from src.app.signal import SignalEvaluator, Signal
from src.app.risk import RiskManager
from src.app.paper_exec import PaperExecutor, PaperPosition

# Initialize Core Services
ledger = Ledger("db.json")
signal_evaluator = SignalEvaluator()
risk_manager = RiskManager()
paper_executor = PaperExecutor()

# Global state for generated signals
generated_signals: List[Signal] = []

def on_orderbook_received(symbol: str, orderbook: dict, timestamp: float):
    sig = signal_evaluator.evaluate(symbol, orderbook, timestamp)
    if sig:
        generated_signals.append(sig)
        if len(generated_signals) > 100:
            generated_signals.pop(0)

market_manager = MarketDataManager(
    symbols=DEFAULT_SYMBOLS,
    on_orderbook_callback=on_orderbook_received
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start market data WebSocket connection in background task
    # Ensures backend execution is non-blocking to splash screen or UI
    market_manager.start()
    yield
    # Shutdown: Stop market data manager
    market_manager.stop()

app = FastAPI(
    title="OBI-BOT Market Data & Signal Engine",
    description="Custom Order Book Imbalance (OBI) Market Data Engine for Futures Streams.",
    version="1.0.0",
    lifespan=lifespan
)

# SECURITY: Restrict CORS origins (auth to be added before real money)
# auth to be added before real money
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://obi-bot.onrender.com",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve Static Assets if directory exists
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# --- DASHBOARD ROUTE ---
@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return HTMLResponse("<h1>PAPER MODE - SIMULATED - NO REAL MONEY</h1>")


# --- MONEY LEDGER ROUTES ---
class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")


class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")


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


# --- MARKET & SIGNAL STATUS ROUTES ---
@app.get("/status")
def get_market_status():
    symbol_statuses = market_manager.check_stale_symbols()
    return {
        "mode": "PAPER_SIMULATED",
        "symbols": market_manager.symbols,
        "symbol_status": symbol_statuses,
        "last_updates": market_manager.last_update
    }


@app.get("/signals", response_model=List[Signal])
def get_recent_signals():
    return generated_signals[-20:]


@app.get("/paper/positions", response_model=List[PaperPosition])
def get_paper_positions():
    return paper_executor.get_all_positions()
