import os
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
# ... your other imports

app = FastAPI(title="NIFTY MACD Dashboard")

# Global Breeze instance (lazy init)
breeze = None

async def get_breeze():
    """Initialize Breeze only when needed - won't crash startup"""
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
            print(f"⚠️ Breeze temp unavailable: {e} (will retry)")
            breeze = None
    return breeze

@app.get("/")
async def dashboard():
    """Main dashboard - Breeze connects on first request"""
    await get_breeze()  # Safe init
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head><title>NIFTY LIVE</title>
    <meta name="viewport" content="width=device-width">
    <style>body{font-family:sans-serif;background:#000;color:#0f0;padding:20px}</style>
    </head>
    <body>
        <h1>🚀 NIFTY Options MACD Dashboard</h1>
        <div id="status">Connecting to Breeze API...</div>
        <div id="signals">-</div>
        <script>
            const ws = new WebSocket('wss://' + location.host + '/ws');
            ws.onopen = () => document.getElementById('status').innerText = '🟢 LIVE - Updates every 5min';
            ws.onmessage = e => document.getElementById('signals').innerHTML = e.data;
        </script>
    </body>
    </html>
    """)

@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket.accept()
    while True:
        try:
            b = await get_breeze()
            if b:
                # Your NIFTY scanning + MACD logic here
                signals = {"call": "🟢 BUY", "put": "🔴 SELL", "time": datetime.now().strftime("%H:%M")}
                await websocket.send_text(str(signals))
            else:
                await websocket.send_text("🔄 Breeze retrying...")
        except:
            await websocket.send_text("⚠️ Temp unavailable")
        await asyncio.sleep(300)  # 5min updates

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
