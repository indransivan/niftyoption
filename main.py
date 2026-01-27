import os
import asyncio
import json
from datetime import datetime, timedelta
import pandas as pd
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from breeze_connect import BreezeConnect
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="NIFTY MACD Dashboard")

# Breeze init
breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
breeze.generate_session(
    api_secret=os.getenv("BREEZE_API_SECRET"),
    session_token=os.getenv("BREEZE_SESSION")
)

# Dashboard frontend
@app.get("/")
async def index():
    with open("index.html") as f:
        return HTMLResponse(f.read())

# Health check
@app.get("/health")
async def health():
    return {"status": "ok"}

# Helper: Get spot price and ATM
def get_atm_strike():
    spot = breeze.get_quotes(stock_code="NIFTY", exchange_code="NSE")["Success"][0]
    spot_price = float(spot.get("lastTradedPrice", spot.get("ltp", spot.get("close_price", 0))))
    atm = round(spot_price / 100) * 100
    return atm

# Helper: Get option historical data
def get_option_history(strike, right, expiry, interval="15minute", days=14):
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    from_str = from_date.strftime("%Y-%m-%dT09:15:00.000Z")
    to_str = to_date.strftime("%Y-%m-%dT15:30:00.000Z")
    expiry_iso = datetime.strptime(expiry, "%d-%b-%Y").strftime("%Y-%m-%dT07:00:00.000Z")

    res = breeze.get_historical_data(
        interval=interval,
        from_date=from_str,
        to_date=to_str,
        stock_code="NIFTY",
        exchange_code="NFO",
        product_type="options",
        expiry_date=expiry_iso,
        right=right,
        strike_price=str(strike)
    )

    if not res.get("Success"):
        return pd.DataFrame()
    df = pd.DataFrame(res["Success"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    for col in ['open','high','low','close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

# Helper: MACD calculation
def calculate_macd(df):
    if len(df) < 26:
        return None, None, None
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

# WebSocket: send live data to frontend
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    expiry = (datetime.now() + pd.DateOffset(months=1)).strftime("%d-%b-%Y")
    atm = get_atm_strike()
    call_strike = atm
    put_strike = atm

    while True:
        try:
            df_call = get_option_history(call_strike, "Call", expiry)
            df_put = get_option_history(put_strike, "Put", expiry)

            # Calculate MACD signals
            call_macd, _, _ = calculate_macd(df_call)
            put_macd, _, _ = calculate_macd(df_put)

            call_signal = "HOLD"
            put_signal = "HOLD"

            if call_macd is not None:
                latest = call_macd.iloc[-1]
                call_signal = "BUY" if latest > 0 else "SELL" if latest < 0 else "HOLD"

            if put_macd is not None:
                latest = put_macd.iloc[-1]
                put_signal = "BUY" if latest > 0 else "SELL" if latest < 0 else "HOLD"

            payload = {
                "call_strike": call_strike,
                "call_signal": call_signal,
                "call_macd": float(call_macd.iloc[-1]) if call_macd is not None else 0,
                "put_strike": put_strike,
                "put_signal": put_signal,
                "put_macd": float(put_macd.iloc[-1]) if put_macd is not None else 0,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }

            await ws.send_text(json.dumps(payload))
        except Exception as e:
            await ws.send_text(json.dumps({"error": str(e)}))

        await asyncio.sleep(300)  # refresh every 5 min
