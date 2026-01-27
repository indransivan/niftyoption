import os, json, asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect

app = FastAPI()
breeze = None

async def get_breeze():
    global breeze
    if breeze is None:
        breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
        breeze.generate_session(
            api_secret=os.getenv("BREEZE_API_SECRET"),
            session_token=os.getenv("BREEZE_SESSION")
        )
    return breeze

@app.get("/")
async def dashboard():
    return HTMLResponse(open("index.html").read())

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    while True:
        try:
            await get_breeze()

            payload = {
                "call_signal": "BUY",
                "call_macd": 1.12,
                "call_strike": 26100,
                "put_signal": "SELL",
                "put_macd": -0.85,
                "put_strike": 24100,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }

            await ws.send_text(json.dumps(payload))
        except Exception as e:
            await ws.send_text(json.dumps({"error": str(e)}))

        await asyncio.sleep(300)
