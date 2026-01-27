import os, json, asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect

app = FastAPI()
breeze = None


# -------------------------------
# Breeze lazy init (Render-safe)
# -------------------------------
async def get_breeze():
    global breeze
    if breeze is None:
        breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
        breeze.generate_session(
            api_secret=os.getenv("BREEZE_API_SECRET"),
            session_token=os.getenv("BREEZE_SESSION")
        )
    return breeze


# -------------------------------
# Routes
# -------------------------------
@app.get("/")
async def dashboard():
    return HTMLResponse(open("index.html").read())


@app.get("/health")
async def health():
    return {"status": "ok"}


# -------------------------------
# WebSocket (charts + signals)
# -------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    while True:
        try:
            await get_breeze()

            # 🔁 TEMP MOCK DATA (replace later with Breeze + MACD)
            labels = ["10:00", "10:15", "10:30", "10:45", "11:00"]

            payload = {
                "call": {
                    "strike": 26100,
                    "signal": "BUY",
                    "price": [102, 106, 111, 115, 118],
                    "macd":  [0.4, 0.7, 1.0, 1.2, 1.35],
                    "labels": labels
                },
                "put": {
                    "strike": 24100,
                    "signal": "SELL",
                    "price": [98, 94, 90, 86, 82],
                    "macd":  [-0.3, -0.6, -0.9, -1.1, -1.3],
                    "labels": labels
                },
                "timestamp": datetime.now().strftime("%d %b %H:%M:%S")
            }

            await ws.send_text(json.dumps(payload))

        except Exception as e:
            await ws.send_text(json.dumps({"error": str(e)}))

        await asyncio.sleep(300)  # 5 min refresh
