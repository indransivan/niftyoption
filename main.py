import os
import json
import asyncio
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect

app = FastAPI(title="NIFTY Options Dashboard")

breeze = None


# ---------- Breeze Init ----------
async def get_breeze():
    global breeze
    if breeze is None:
        breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
        breeze.generate_session(
            api_secret=os.getenv("BREEZE_API_SECRET"),
            session_token=os.getenv("BREEZE_SESSION")
        )
        print("✅ Breeze connected")
    return breeze


# ---------- Helpers ----------
def round_to_atm(price: float) -> int:
    return round(price / 50) * 50


def to_candles(data):
    candles = []
    for d in data:
        candles.append({
            "time": int(datetime.fromisoformat(d["datetime"]).timestamp()),
            "open": float(d["open"]),
            "high": float(d["high"]),
            "low": float(d["low"]),
            "close": float(d["close"])
        })
    return candles


# ---------- Routes ----------
@app.get("/")
async def dashboard():
    return HTMLResponse(open("index.html").read())


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- WebSocket ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    while True:
        try:
            b = await get_breeze()

            # 1️⃣ Get NIFTY LTP
            q = b.get_quotes(
                stock_code="NIFTY",
                exchange_code="NSE",
                product_type="cash"
            )["Success"][0]

            ltp = float(q["ltp"])
            atm = round_to_atm(ltp)

            # 2️⃣ Time window (15 days)
            end = datetime.now()
            start = end - timedelta(days=15)

            # 3️⃣ CALL data
            call_raw = b.get_historical_data_v2(
                interval="15minute",
                from_date=start.strftime("%Y-%m-%dT09:15:00.000Z"),
                to_date=end.strftime("%Y-%m-%dT15:30:00.000Z"),
                stock_code="NIFTY",
                exchange_code="NSE",
                product_type="options",
                right="call",
                strike_price=atm
            )["Success"]

            # 4️⃣ PUT data
            put_raw = b.get_historical_data_v2(
                interval="15minute",
                from_date=start.strftime("%Y-%m-%dT09:15:00.000Z"),
                to_date=end.strftime("%Y-%m-%dT15:30:00.000Z"),
                stock_code="NIFTY",
                exchange_code="NSE",
                product_type="options",
                right="put",
                strike_price=atm
            )["Success"]

            payload = {
                "call": {
                    "strike": atm,
                    "candles": to_candles(call_raw)
                },
                "put": {
                    "strike": atm,
                    "candles": to_candles(put_raw)
                },
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }

            await ws.send_text(json.dumps(payload))

        except Exception as e:
            await ws.send_text(json.dumps({"error": str(e)}))

        # Update every 5 minutes
        await asyncio.sleep(300)


# ---------- Local run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
