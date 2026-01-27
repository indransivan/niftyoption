import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta
import calendar
import os
import time
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY Live MACD", layout="wide")

# --- CUSTOM CSS FOR DARK THEME DASHBOARD ---
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    div.stButton > button:first-child { background-color: #00ff88; color: black; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: AUTHENTICATION ---
st.sidebar.header("🔐 Authentication")
api_key = st.sidebar.text_input("API Key", value=os.getenv("BREEZE_API_KEY", "3194b6xL482162_16NkJ368y350336i&"))
api_secret = st.sidebar.text_input("API Secret", type="password", value=os.getenv("BREEZE_API_SECRET", "(7@1q7426%p614#fk015~J9%4_$3v6Wh"))
session_token = st.sidebar.text_input("Fresh Session Token", type="password", help="Get this from the ICICI Login URL daily")

# --- UTILITY FUNCTIONS ---
def get_next_month_expiry():
    today = datetime.today()
    year = today.year
    month = today.month + 1
    if month > 12:
        month = 1; year += 1
    last_day = calendar.monthrange(year, month)[1]
    expiry = datetime(year, month, last_day)
    while expiry.weekday() != 3:  # Thursday
        expiry -= timedelta(days=1)
    return expiry.strftime("%d-%b-%Y"), expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd(df):
    if len(df) < 26: return None, None, None
    close_prices = pd.to_numeric(df['close']).dropna()
    ema12 = close_prices.ewm(span=12, adjust=False).mean()
    ema26 = close_prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def resample_to_15min(df_5min):
    if df_5min.empty: return pd.DataFrame()
    df = df_5min.copy()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['close'])
    return df.resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna()

# --- MAIN LOGIC ---
if session_token:
    try:
        # Initialize Breeze
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        
        st.sidebar.success("✅ Connected to Breeze")
        
        # 1. Setup Parameters
        expiry_str, expiry_iso = get_next_month_expiry()
        target_premium = st.sidebar.slider("Target Premium", 50, 500, 100)
        
        # 2. Fetch Spot & Strikes
        spot = breeze.get_quotes(stock_code="NIFTY", exchange_code="NSE")
        spot_price = float(spot['Success'][0]['ltp'])
        atm = round(spot_price / 100) * 100
        
        st.header(f"📊 NIFTY Spot: {spot_price} (ATM: {atm})")
        
        # 3. Data Fetching Container
        with st.spinner("Fetching Historical Data..."):
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)
            
            # For deployment simplicity, we use fixed offsets for demonstration
            # You can re-implement the 'Scan' loop here if needed
            call_strike = atm + 200
            put_strike = atm - 200

            def get_data(strike, right):
                res = breeze.get_historical_data(
                    interval="5minute",
                    from_date=from_date.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_date.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=right, strike_price=str(strike)
                )
                if res.get("Success"):
                    df = pd.DataFrame(res["Success"])
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    return df.set_index("datetime")
                return pd.DataFrame()

            df_call_5 = get_data(call_strike, "Call")
            df_put_5 = get_data(put_strike, "Put")

        # 4. Plotting
        if not df_call_5.empty and not df_put_5.empty:
            df_c15 = resample_to_15min(df_call_5)
            df_p15 = resample_to_15min(df_put_5)

            fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor='#0e1117')
            plt.subplots_adjust(hspace=0.4)

            # --- CALL CHART (Top Left) ---
            ax1, ax2 = axes[0,0], axes[0,1]
            ax1.plot(df_c15.index, df_c15['close'], color='#00ff88', label='CE Price')
            ax1.set_title(f"Call {call_strike} CE", color='white')
            
            # --- CALL MACD (Top Right) ---
            m, s, h = calculate_macd(df_c15)
            if m is not None:
                ax2.plot(m.index, m, label='MACD', color='#00ff88')
                ax2.plot(s.index, s, label='Signal', color='orange')
                ax2.bar(h.index, h, color=['green' if val > 0 else 'red' for val in h], alpha=0.3)
                ax2.axhline(0, color='white', lw=0.5)
                sig = "🟢 BUY" if m.iloc[-1] > 0 else "🔴 SELL"
                ax2.set_title(f"Call MACD: {sig}", color='white')

            # --- PUT CHART (Bottom Left) ---
            ax3, ax4 = axes[1,0], axes[1,1]
            ax3.plot(df_p15.index, df_p15['close'], color='#ff4444', label='PE Price')
            ax3.set_title(f"Put {put_strike} PE", color='white')

            # --- PUT MACD (Bottom Right) ---
            m, s, h = calculate_macd(df_p15)
            if m is not None:
                ax4.plot(m.index, m, label='MACD', color='#ff4444')
                ax4.plot(s.index, s, label='Signal', color='orange')
                ax4.bar(h.index, h, color=['green' if val > 0 else 'red' for val in h], alpha=0.3)
                ax4.axhline(0, color='white', lw=0.5)
                sig = "🟢 BUY" if m.iloc[-1] > 0 else "🔴 SELL"
                ax4.set_title(f"Put MACD: {sig}", color='white')

            for ax in axes.flat:
                ax.set_facecolor('#1e2129')
                ax.tick_params(colors='white')
                ax.grid(alpha=0.1)

            st.pyplot(fig)
            
            # Auto-refresh logic
            time.sleep(1)
            if st.button("Manual Refresh"):
                st.rerun()
        else:
            st.error("No historical data found. Are the strikes/expiry correct?")

    except Exception as e:
        st.error(f"Error: {e}")
        st.info("Check if your Session Token is fresh (consumed tokens don't work).")

else:
    st.info("👋 Welcome! Please enter a **Fresh Session Token** in the sidebar to start the live dashboard.")
