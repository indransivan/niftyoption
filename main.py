import os, json, asyncio, random
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect

app = FastAPI()
breeze = None


# ---------------- Breeze Init ----------------
async def get_breeze():
    global breeze
    try:
        if breeze is None:
            breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
            breeze.generate_session(
                api_secret=os.getenv("BREEZE_API_SECRET"),
                session_token=os.getenv("BREEZE_SESSION")
            )
        return breeze
    except Exception as e:
        print("Breeze unavailable:", e)
        return None


# ---------------- Helpers ----------------
def generate_mock_candles(days=15):
    candles = []
    now = datetime.now() - timedelta(days=days)
    price = 100

    for _ in range(days * 25):  # ~15 min candles
        open_ = price
        close = open_ + random.uniform(-2, 2)
        high = max(open_, close) + random.uniform(0, 1)
        low = min(open_, close) - random.uniform(0, 1)

        candles.append({
            "time": int(now.timestamp()),
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
        })

        price = close
        now += timedelta(minutes=15)

    return candles


def round_to_atm(price):
    return round(price / 50) * 50


# ---------------- Routes ----------------
@app.get("/")
async def dashboard():
    return HTMLResponse(open("index.html").read())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    while True:
        try:
            b = await get_breeze()

            # ---- Try live NIFTY LTP ----
            ltp = 22500  # fallback
            if b:
                q = b.get_quotes(
                    stock_code="NIFTY",
                    exchange_code="NSE",
                    product_type="cash"
                )
                if q and "Success" in q:
                    ltp = float(q["Success"][0]["ltp"])

            atm = round_to_atm(ltp)

            payload = {
                "call": {
                    "strike": atm,
                    "candles": generate_mock_candles()
                },
                "put": {
                    "strike": atm,
                    "candles": generate_mock_candles()
                },
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }

            await ws.send_text(json.dumps(payload))

        except Exception as e:
            print("WS error:", e)

        await asyncio.sleep(5)  # fast refresh for testing
