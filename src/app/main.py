import os
import csv
import io
from fastapi import FastAPI, HTTPException, status, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import Optional

from src.money.ledger import Ledger
from src.risk.limits import RiskManager
from src.alerts.telegram import send_alert, is_telegram_connected

app = FastAPI(title="OBI-BOT")
ledger = Ledger("db.json")
risk_manager = RiskManager()

templates = Jinja2Templates(directory="src/app/templates")

class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")

class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(request: Request, user_id: str = "user1"):
    daily_pnl = ledger.get_pnl(user_id)
    risk_status = risk_manager.get_status()
    telegram_connected = is_telegram_connected()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "daily_pnl": daily_pnl,
            "risk_status": risk_status,
            "telegram_connected": telegram_connected,
            "user_id": user_id
        }
    )


@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    balance = ledger.get_balance(user_id)
    return {"user_id": user_id, "balance": balance}


@app.post("/deposit")
def deposit(req: DepositRequest):
    try:
        new_balance = ledger.deposit(user_id=req.user_id, amount=req.amount, method=req.method)
        send_alert(f"💰 Deposit Confirmed: {req.amount} UGX for user '{req.user_id}' via {req.method}")
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


@app.get("/export/trades/{user_id}")
def export_trades(user_id: str):
    trades = ledger.get_trades(user_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "side", "price", "qty", "pnl", "balance_after"])

    for trade in trades:
        writer.writerow([
            trade.get("date", ""),
            trade.get("side", ""),
            trade.get("price", 0.0),
            trade.get("qty", 0.0),
            trade.get("pnl", 0.0),
            trade.get("balance_after", 0.0)
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=trades_{user_id}.csv"}
    )


@app.get("/risk/status")
def get_risk_status():
    return risk_manager.get_status()


@app.post("/risk/reset")
def reset_risk_circuit_breaker():
    risk_manager.circuit_breaker.reset()
    return {
        "status": "success",
        "message": "Circuit breaker reset successfully",
        "circuit_breaker": risk_manager.circuit_breaker.get_status()
    }
