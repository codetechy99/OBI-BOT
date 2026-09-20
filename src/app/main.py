import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.money.ledger import Ledger
from src.market_data.orderbook import orderbook_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orderbook_manager.start()
    yield
    await orderbook_manager.stop()


app = FastAPI(title="OBI-BOT", lifespan=lifespan)
ledger = Ledger("db.json")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")


class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")


@app.get("/")
def read_root():
    if os.path.exists("static/dashboard.html"):
        return FileResponse("static/dashboard.html")
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def read_dashboard():
    if os.path.exists("static/dashboard.html"):
        return FileResponse("static/dashboard.html")
    return """<!DOCTYPE html>
<html>
<head><title>OBI Dashboard</title></head>
<body>
<h1>OBI-BOT Dashboard</h1>
<div id="status">Loading...</div>
<script>
async function update() {
    const res = await fetch('/api/dashboard/status');
    const data = await res.json();
    document.getElementById('status').innerText = JSON.stringify(data, null, 2);
}
setInterval(update, 1000);
update();
</script>
</body>
</html>"""


@app.get("/api/dashboard/status")
def get_dashboard_status():
    return orderbook_manager.get_status()


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
            "balance": new_balance,
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
            "balance": new_balance,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
