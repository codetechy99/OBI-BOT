import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.money.ledger import Ledger
from src.market_data.orderbook import orderbook_manager
from src.app.bot import bot_engine

logger = logging.getLogger("obi_bot")


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()
_ws_broadcast_task = None


async def ws_broadcast_loop():
    while True:
        try:
            await asyncio.sleep(0.1)  # Broadcast every 100ms
            if ws_manager.active_connections:
                snap = orderbook_manager.get_market_snapshot("BTCUSDT")
                bot_stat = bot_engine.get_status()
                payload = {
                    "type": "ticker",
                    "timestamp": time.time(),
                    "market": snap,
                    "bot": {
                        "is_running": bot_stat["is_running"],
                        "mode": bot_stat["mode"],
                        "balance": bot_stat["balance"],
                        "equity": bot_stat["equity"],
                        "unrealized_pnl": bot_stat["unrealized_pnl"],
                        "open_positions": bot_stat["open_positions"],
                        "open_positions_count": bot_stat["open_positions_count"],
                        "today_trades_count": bot_stat["today_trades_count"],
                        "recent_logs": bot_engine.logs[-10:],
                    }
                }
                await ws_manager.broadcast(payload)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in websocket broadcast loop: {e}")
            await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_broadcast_task
    await orderbook_manager.start()
    _ws_broadcast_task = asyncio.create_task(ws_broadcast_loop())
    yield
    if _ws_broadcast_task:
        _ws_broadcast_task.cancel()
    await orderbook_manager.stop()


app = FastAPI(title="OBI-BOT MT5 DMA", lifespan=lifespan)
ledger = Ledger("db.json")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return RedirectResponse("/dashboard")


@app.get("/manifest.json")
def manifest():
    if os.path.exists("static/manifest.json"):
        return FileResponse("static/manifest.json", media_type="application/json")
    raise HTTPException(status_code=404, detail="Manifest not found")


@app.get("/favicon.ico")
def favicon():
    if os.path.exists("static/favicon.ico"):
        return FileResponse("static/favicon.ico")
    if os.path.exists("static/icon-192.png"):
        return FileResponse("static/icon-192.png")
    return FileResponse("static/dashboard.html") if os.path.exists("static/dashboard.html") else HTMLResponse("OK")


@app.get("/dashboard")
def dashboard():
    if os.path.exists("static/dashboard.html"):
        return FileResponse("static/dashboard.html")
    return HTMLResponse("<h1>OBI Dashboard</h1>")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard/status")
def get_dashboard_status():
    return orderbook_manager.get_status()


@app.get("/live/obi")
def get_live_obi():
    snap = orderbook_manager.get_market_snapshot("BTCUSDT")
    return {
        "I": snap.get("obi", 0.0),
        "bid": snap.get("best_bid", 0.0),
        "ask": snap.get("best_ask", 0.0),
        "timestamp": snap.get("updated_at", time.time())
    }


@app.get("/dashboard/data/{user_id}")
def get_dashboard_data(user_id: str):
    bot_stat = bot_engine.get_status()
    balance = bot_stat["balance"]
    equity = bot_stat["equity"]
    trades = bot_stat["trades_history"]
    open_pos = bot_stat["open_positions"]

    return {
        "balance": balance,
        "reserved": 0.0,
        "available": balance,
        "pnl_total": equity - 10000.0,
        "active_order": open_pos[0] if open_pos else None,
        "trades": trades
    }


# WebSocket endpoint broadcasting market data & bot status
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial state
        snap = orderbook_manager.get_market_snapshot("BTCUSDT")
        bot_stat = bot_engine.get_status()
        await websocket.send_json({
            "type": "init",
            "market": snap,
            "bot": bot_stat
        })
        while True:
            # Keep socket alive and receive incoming settings updates if sent
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        ws_manager.disconnect(websocket)


# Bot API Controllers

class BotStartRequest(BaseModel):
    mode: Optional[str] = Field("demo", description="Trading mode: demo or live")
    lot_size: Optional[float] = Field(0.1, gt=0, description="Lot size in BTC")
    threshold: Optional[float] = Field(0.35, ge=0.05, le=0.95, description="OBI threshold ratio (0.05 to 0.95)")
    tp_usd: Optional[float] = Field(150.0, gt=0, description="Take Profit in USD")
    sl_usd: Optional[float] = Field(100.0, gt=0, description="Stop Loss in USD")
    api_key: Optional[str] = Field("", description="Binance Testnet API Key")
    api_secret: Optional[str] = Field("", description="Binance Testnet API Secret")


class BotStopRequest(BaseModel):
    close_positions: Optional[bool] = Field(True, description="Close all open positions on stop")


@app.post("/api/bot/start")
async def start_bot(req: BotStartRequest = BotStartRequest()):
    bot_engine.update_settings(
        mode=req.mode,
        lot_size=req.lot_size,
        threshold=req.threshold,
        tp_usd=req.tp_usd,
        sl_usd=req.sl_usd,
        api_key=req.api_key,
        api_secret=req.api_secret,
    )
    try:
        res = await bot_engine.start_bot()
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/bot/stop")
async def stop_bot(req: BotStopRequest = BotStopRequest()):
    res = await bot_engine.stop_bot(close_positions=req.close_positions)
    return res


@app.get("/api/bot/status")
def get_bot_status():
    return bot_engine.get_status()


@app.get("/api/bot/logs")
def get_bot_logs():
    return {"logs": bot_engine.logs}


@app.post("/api/bot/reset_demo")
def reset_demo():
    bot_engine.reset_demo_balance()
    return {"status": "success", "message": "Demo balance reset to $10,000"}


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


class MomoDepositRequest(BaseModel):
    user_id: str = Field("default_user", description="User ID")
    amount: float = Field(..., gt=0, description="Amount to deposit")
    phone: str = Field(..., description="Phone number")


@app.post("/momo/deposit")
def momo_deposit(req: MomoDepositRequest):
    new_bal = ledger.deposit(req.user_id, req.amount, method=f"MoMo ({req.phone})")
    return {
        "status": "PENDING",
        "transaction_id": f"MM-{int(time.time()*1000)%1000000}",
        "balance": new_bal
    }
