import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.money.ledger import Ledger
from src.money.momo_sim import MoMoSim
from src.execution.execution_handler import ExecutionHandler
from src.market_data.ws_client import start_ws_client, latest_obi_data

ledger = Ledger("db.json")
# Create default account if not exists
ledger.create_account("default_user")

momo_sim = MoMoSim(ledger)
execution_handler = ExecutionHandler(ledger, default_user_id="default_user")

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ws_task = asyncio.create_task(start_ws_client(execution_handler))
    yield
    ws_task.cancel()

app = FastAPI(title="OBI-BOT", lifespan=lifespan)

class DepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit, must be > 0")
    method: Optional[str] = Field("MoMo", description="Payment method")

class WithdrawRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to withdraw, must be > 0")

class MoMoDepositRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit")
    phone: str = Field(..., description="Phone number")

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@app.get("/live/obi")
async def get_live_obi():
    return latest_obi_data

@app.post("/momo/deposit")
async def momo_deposit(req: MoMoDepositRequest):
    try:
        res = await momo_sim.request_deposit(user_id=req.user_id, amount=req.amount, phone=req.phone)
        return res
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.get("/dashboard/data/{user_id}")
async def get_dashboard_data(user_id: str):
    return execution_handler.get_dashboard_data(user_id)

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
