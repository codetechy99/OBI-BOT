from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, Dict

from src.money.ledger import Ledger
from src.execution.handler import ExecutionHandler

app = FastAPI(title="OBI-BOT")
ledger = Ledger("db.json")
handlers: Dict[str, ExecutionHandler] = {}

def get_handler(user_id: str) -> ExecutionHandler:
    if user_id not in handlers:
        handlers[user_id] = ExecutionHandler(ledger, user_id)
    return handlers[user_id]


class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")


class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")


class SignalRequest(BaseModel):
    user_id: Optional[str] = Field("user1", description="User ID")
    I: float = Field(..., description="Order Book Imbalance")
    bid1: float = Field(..., gt=0, description="Top bid price")
    ask1: float = Field(..., gt=0, description="Top ask price")
    tick_size: Optional[float] = Field(1.0, description="Tick size")


@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    balance = ledger.get_balance(user_id)
    reserved = ledger.get_reserved(user_id)
    return {"user_id": user_id, "balance": balance, "reserved": reserved}


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


@app.post("/signal")
def post_signal(req: SignalRequest):
    user_id = req.user_id or "user1"
    handler = get_handler(user_id)
    res = handler.on_signal(
        I=req.I,
        bid1=req.bid1,
        ask1=req.ask1,
        tick_size=req.tick_size or 1.0
    )
    return {
        "status": res.get("status"),
        "user_id": user_id,
        "active_order": handler.active_order,
        "balance": ledger.get_balance(user_id),
        "reserved": ledger.get_reserved(user_id),
        "details": res
    }


@app.get("/orders/{user_id}")
def get_orders(user_id: str):
    handler = get_handler(user_id)
    return {
        "user_id": user_id,
        "active_order": handler.active_order,
        "orders": handler.orders
    }


@app.get("/trades/{user_id}")
def get_trades(user_id: str):
    handler = get_handler(user_id)
    return {
        "user_id": user_id,
        "trades": handler.trades
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=True)
