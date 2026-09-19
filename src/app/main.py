import asyncio, json, os, time
from collections import deque
import websockets
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

obi_state = {
    "BTCUSDT": {"obi": 0.0, "bid_vol": 0, "ask_vol": 0, "price": 0, "last_update": 0},
    "ETHUSDT": {"obi": 0.0, "bid_vol": 0, "ask_vol": 0, "price": 0, "last_update": 0},
    "XAUUSDT": {"obi": 0.0, "bid_vol": 0, "ask_vol": 0, "price": 0, "last_update": 0},
}
trade_history = deque(maxlen=100)
balance_state = {"balance": 50000, "currency": "UGX", "mode": "paper"}

SYMBOLS = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,XAUUSDT").split(",")
WS_URL = os.getenv("BINANCE_FUTURES_WS", "wss://fstream.binance.com/stream")

def calc_obi(bids, asks):
    bid_vol = sum(float(q) for p,q in bids[:20])
    ask_vol = sum(float(q) for p,q in asks[:20])
    total = bid_vol + ask_vol
    if total == 0: return 0, bid_vol, ask_vol
    return (bid_vol - ask_vol)/total, bid_vol, ask_vol

async def futures_ws_client():
    streams = "/".join([f"{s.lower()}@depth20@100ms" for s in SYMBOLS])
    url = f"{WS_URL}?streams={streams}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                print("BINANCE WS CONNECTED - REAL DATA")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    payload = data.get("data")
                    if not payload: continue
                    symbol = payload.get("s")
                    bids = payload.get("b", [])
                    asks = payload.get("a", [])
                    if not bids or not asks: continue
                    obi, bid_vol, ask_vol = calc_obi(bids, asks)
                    price = float(bids[0][0]) if bids else 0
                    obi_state[symbol] = {"obi": round(obi,4), "bid_vol": round(bid_vol,4), "ask_vol": round(ask_vol,4), "price": price, "last_update": time.time()}
                    if obi > 0.7: trade_history.append({"symbol": symbol, "side": "LONG", "obi": round(obi,4), "price": price, "time": time.time()})
                    elif obi < -0.7: trade_history.append({"symbol": symbol, "side": "SHORT", "obi": round(obi,4), "price": price, "time": time.time()})
        except Exception as e:
            print(f"WS Error {e} retry 5s")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup():
    asyncio.create_task(futures_ws_client())

@app.get("/health")
def health(): return {"status": "ok", "obi_live": len([v for v in obi_state.values() if v["last_update"]>0])>0}

@app.get("/api/obi")
def get_obi(): return obi_state

@app.get("/api/trades")
def get_trades(): return list(trade_history)

@app.get("/api/balance")
def balance(): return balance_state

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/static/icon.png"><meta name="theme-color" content="#050a1a">
<title>OBI-BOT</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#050a1a] text-white">
<div id="splash" style="position:fixed;inset:0;z-index:9999;background:radial-gradient(circle at center,#0a1628 0%,#050a1a 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;transition:opacity 1s;">
<img src="/static/icon.png" onerror="this.style.display='none'" style="width:70vw;max-width:300px;filter:drop-shadow(0 0 25px #00aaff);animation:pulse 2s infinite;">
<h1 style="color:#00d4ff;font-family:monospace;margin-top:20px;letter-spacing:5px;">OBI-BOT</h1>
<p style="color:#8a8aff;font-size:11px;margin-top:6px;">Order Book Imbalance • Live Engine</p>
<div style="margin-top:30px;width:140px;height:2px;background:#111;overflow:hidden;border-radius:2px;"><div id="loader" style="height:100%;width:0%;background:linear-gradient(90deg,#00aaff,#aa44ff);animation:load 10s linear forwards;"></div></div>
<style>@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}@keyframes load{0%{width:0%}100%{width:100%}}</style>
</div>
<div class="p-4 max-w-md mx-auto">
<h2 class="text-center text-cyan-400 font-bold tracking-widest mt-2">LIVE OBI</h2>
<div id="obi-cards" class="mt-6 space-y-3"></div>
<div class="mt-8"><h3 class="text-xs text-gray-400">RECENT SIGNALS</h3><div id="trades" class="mt-2 text-xs space-y-1"></div></div>
<div class="mt-8 grid grid-cols-2 gap-3"><button onclick="deposit()" class="bg-cyan-600 py-3 rounded-lg font-bold">DEPOSIT +50k</button><button onclick="withdraw()" class="bg-purple-600 py-3 rounded-lg font-bold">WITHDRAW</button></div>
<div id="bal" class="text-center mt-4 text-sm text-gray-300"></div>
</div>
<script>
let obiRunning=false;
function startOBI(){
 if(obiRunning) return; obiRunning=true;
 setInterval(async()=>{
  try{
   let r=await fetch('/api/obi'); let data=await r.json();
   let html='';
   for(let sym in data){
    let o=data[sym]; let color=o.obi>0.5?'text-green-400':o.obi<-0.5?'text-red-400':'text-yellow-300';
    html+=`<div class="bg-[#0f1a33] p-3 rounded-xl border border-[#1a2a5a]"><div class="flex justify-between"><span class="font-bold">${sym}</span><span class="${color} font-mono">${o.obi}</span></div><div class="text-xs text-gray-400">$${o.price} | Bid ${o.bid_vol.toFixed(1)} Ask ${o.ask_vol.toFixed(1)}</div></div>`;
   }
   document.getElementById('obi-cards').innerHTML=html;
   let tr=await (await fetch('/api/trades')).json();
   document.getElementById('trades').innerHTML=tr.slice(-5).reverse().map(t=>`<div>${t.symbol} <b class="${t.side=='LONG'?'text-green-400':'text-red-400'}">${t.side}</b> OBI ${t.obi} @ $${t.price}</div>`).join('');
   let b=await (await fetch('/api/balance')).json();
   document.getElementById('bal').innerText='Balance: '+b.balance+' '+b.currency+' ('+b.mode+')';
  }catch(e){}
 },500);
}
setTimeout(()=>{
 let s=document.getElementById('splash'); s.style.opacity='0'; setTimeout(()=>{s.remove(); startOBI();},1000);
},10000);
async function deposit(){await fetch('/api/balance'); alert('Simulated +50k added');}
async function withdraw(){alert('Simulated withdraw');}
</script>
</body></html>
    """

@app.get("/")
def root(): return {"status": "OBI-BOT LIVE", "dashboard": "/dashboard", "api": "/api/obi"}
