import os
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect

app = FastAPI(title="NIFTY MACD Dashboard")
breeze = None

async def get_breeze():
    global breeze
    if breeze is None:
        try:
            breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
            breeze.generate_session(
                api_secret=os.getenv("BREEZE_API_SECRET"),
                session_token=os.getenv("BREEZE_SESSION")
            )
            print("✅ Breeze connected")
        except Exception as e:
            print(f"⚠️ Breeze unavailable: {e}")
            breeze = None
    return breeze


@app.get("/")
async def dashboard():
    with open("index.html") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    while True:
        try:
            await get_breeze()

            # 🔁 REPLACE with your real MACD logic
            payload = {
                "call_signal": "BUY",
                "call_macd": 1.23,
                "call_strike": 26100,

                "put_signal": "SELL",
                "put_macd": -0.87,
                "put_strike": 24100,

                "timestamp": datetime.now().strftime("%d %b %H:%M:%S")
            }

            # ✅ SEND PROPER JSON
            await ws.send_text(json.dumps(payload))

        except Exception as e:
            await ws.send_text(json.dumps({
                "error": "Temporary unavailable",
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }))

        await asyncio.sleep(300)  # 5 min


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
