import asyncio
import os
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.money.ledger import Ledger

app = FastAPI(title="OBI-BOT")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ledger = Ledger("db.json")


async def futures_ws_client():
    """Background task for futures WebSocket stream."""
    ws_url = os.getenv("BINANCE_FUTURES_WS", "wss://fstream.binance.com/stream")
    symbols = os.getenv("SYMBOLS", "EURUSDT,GBPUSDT,XAUUSDT,BTCUSDT,ETHUSDT")
    while True:
        await asyncio.sleep(3600)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(futures_ws_client())


class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")


class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")


@app.get("/")
def read_root():
    return {"message": "OBI-BOT API is running", "status": "ok"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/dashboard")
def get_dashboard():
    symbols_str = os.getenv("SYMBOLS", "EURUSDT,GBPUSDT,XAUUSDT,BTCUSDT,ETHUSDT")
    return {
        "status": "ok",
        "message": "OBI-BOT Dashboard",
        "symbols": symbols_str.split(","),
        "trading_mode": os.getenv("TRADING_MODE", "paper")
    }


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


port = int(os.getenv("PORT", 8000))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=port)
