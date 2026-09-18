from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional

from src.money.ledger import Ledger

app = FastAPI(title="OBI-BOT")
ledger = Ledger("db.json")


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
