import os, json, asyncio, random
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect

app = FastAPI(title="NIFTY MACD Dashboard")
breeze = None

# -------------------------
# Initialize Breeze API
# -------------------------
async def get_breeze():
    global breeze
    if breeze is None:
        try:
            breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
            breeze.generate_session(
                api_secret=os.getenv("BREEZE_API_SECRET"),
                session_token=os.getenv("BREEZE_SESSION")
            )
            print("✅ Breeze API Connected!")
        except Exception as e:
            print(f"⚠️ Breeze unavailable: {e}")
            breeze = None
    return breeze

# -------------------------
# Serve frontend
# -------------------------
@app.get("/")
async def dashboard():
    return HTMLResponse(open("index.html").read())

@app.get("/health")
async def health():
    return {"status": "ok"}

# -------------------------
# WebSocket endpoint
# -------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    while True:
        try:
            # ---- MOCK 15-DAY HISTORICAL CANDLES ----
            now = datetime.now()

            def mock_candles(base_price):
                candles = []
                for i in range(15*24*4):  # 15 days, 15-min candles
                    t = now - timedelta(minutes=(15*24*4 - i)*15)
                    o = base_price + random.uniform(-50, 50)
                    h = o + random.uniform(0, 25)
                    l = o - random.uniform(0, 25)
                    c = o + random.uniform(-20, 20)
                    candles.append({
                        "time": int(t.timestamp()*1000),  # JS uses ms
                        "open": round(o,2),
                        "high": round(h,2),
                        "low": round(l,2),
                        "close": round(c,2)
                    })
                return candles

            # Auto ATM strike example
            spot_price = 25150
            atm_call = round(spot_price / 100) * 100
            atm_put = atm_call - 200

            payload = {
                "call": {"strike": atm_call, "candles": mock_candles(atm_call)},
                "put": {"strike": atm_put, "candles": mock_candles(atm_put)},
                "timestamp": now.strftime("%d-%b-%Y %H:%M:%S")
            }

            await ws.send_text(json.dumps(payload))

            # ---- Placeholder for WhatsApp alert ----
            # Example: send WhatsApp if MACD crosses threshold
            # if macd_call > 50: send_whatsapp_alert("CALL BUY")

        except Exception as e:
            await ws.send_text(json.dumps({"error": str(e)}))

        await asyncio.sleep(300)  # Update every 5 min

# -------------------------
# Run with uvicorn
# -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
