import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import os
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY Monthly ₹100 Strategy", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    div.stButton > button:first-child { background-color: #00ff88; color: black; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: AUTHENTICATION & SETTINGS ---
st.sidebar.header("🔐 Authentication")
api_key = st.sidebar.text_input("API Key", value=os.getenv("BREEZE_API_KEY", "3194b6xL482162_16NkJ368y350336i&"))
api_secret = st.sidebar.text_input("API Secret", type="password", value=os.getenv("BREEZE_API_SECRET", "(7@1q7426%p614#fk015~J9%4_$3v6Wh"))
session_token = st.sidebar.text_input("Fresh Session Token", type="password")

st.sidebar.divider()
st.sidebar.header("⚙️ Target Range")
# Restricting input range between 80 and 120 as requested
target_price = st.sidebar.number_input("Target Premium (₹)", min_value=80, max_value=120, value=100, step=1)

# --- UTILITY FUNCTIONS ---
def get_last_tuesday(date_obj):
    """Finds the last Tuesday of the month."""
    last_day = calendar.monthrange(date_obj.year, date_obj.month)[1]
    expiry = datetime(date_obj.year, date_obj.month, last_day)
    while expiry.weekday() != 1: # 1 is Tuesday
        expiry -= timedelta(days=1)
    return expiry

def get_monthly_expiry():
    """Calculates the current or next monthly expiry (Last Tuesday)."""
    today = datetime.today()
    expiry = get_last_tuesday(today)
    if today.date() > expiry.date():
        # Move to next month if current monthly has passed
        next_month = (today.replace(day=28) + timedelta(days=7))
        expiry = get_last_tuesday(next_month)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd(df):
    if df is None or len(df) < 26: return None, None, None
    close = pd.to_numeric(df['close'], errors='coerce').dropna()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Resample to 15min and use integer indexing (1, 2, 3...)
    resampled = df.resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna()
    resampled = resampled.reset_index(drop=True)
    resampled.index += 1
    return resampled

# --- MAIN APP LOGIC ---
if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_monthly_expiry()
        
        # 1. Get Nifty Spot
        spot = breeze.get_quotes(stock_code="NIFTY", exchange_code="NSE")
        spot_price = float(spot['Success'][0]['ltp'])
        atm = round(spot_price / 100) * 100
        
        # 2. Scanner for Strikes within 80-120 range
        def find_best_strike(right):
            # Check 15 strikes around ATM to find premium closest to target
            strikes = [atm + (i * 50) for i in range(-15, 16)]
            best_s, min_diff = atm, float('inf')
            
            for s in strikes:
                q = breeze.get_quotes(stock_code="NIFTY", exchange_code="NFO", 
                                      expiry_date=expiry_iso, right=right, strike_price=str(s))
                if q.get("Success"):
                    ltp = float(q["Success"][0]["ltp"])
                    # Enforce the 80-120 range strictly
                    if 80 <= ltp <= 120:
                        diff = abs(ltp - target_price)
                        if diff < min_diff:
                            min_diff = diff
                            best_s = s
            return best_s

        with st.spinner(f"Scanning ₹80-₹120 monthly strikes..."):
            call_strike = find_best_strike("Call")
            put_strike = find_best_strike("Put")

        # 3. Fetch & Plot
        to_date = datetime.now()
        from_date = to_date - timedelta(days=8)
        
        def get_hist(s, r):
            res = breeze.get_historical_data(interval="5minute", 
                from_date=from_date.strftime("%Y-%m-%dT09:15:00.000Z"),
                to_date=to_date.strftime("%Y-%m-%dT15:30:00.000Z"),
                stock_code="NIFTY", exchange_code="NFO", product_type="options",
                expiry_date=expiry_iso, right=r, strike_price=str(s))
            return pd.DataFrame(res["Success"]) if res.get("Success") else pd.DataFrame()

        df_c = process_data(get_hist(call_strike, "Call"))
        df_p = process_data(get_hist(put_strike, "Put"))

        st.title(f"📈 NIFTY Monthly (Expiry: {expiry_iso[:10]})")
        st.subheader(f"Selected: {call_strike} CE & {put_strike} PE")

        plt.style.use('dark_background')
        fig, axes = plt.subplots(2, 2, figsize=(15, 10), facecolor='#0e1117')
        
        def plot_macd_view(df, row, color, title):
            m, s, h = calculate_macd(df)
            axes[row,0].plot(df.index, df['close'], color=color, linewidth=1.5)
            axes[row,0].set_title(f"{title} Price", color='white')
            if m is not None:
                axes[row,1].plot(df.index, m, color=color, label='MACD')
                axes[row,1].plot(df.index, s, color='orange', label='Signal')
                axes[row,1].bar(df.index, h, color=['#00ff88' if x > 0 else '#ff4444' for x in h], alpha=0.3)
                axes[row,1].set_title(f"{title} MACD", color='white')

        plot_macd_view(df_c, 0, '#00ff88', f"Call {call_strike}")
        plot_macd_view(df_p, 1, '#ff4444', f"Put {put_strike}")

        for ax in axes.flat:
            ax.set_xlabel("Candle Index")
            ax.set_facecolor('#161a25')
            ax.grid(color='#2d3446', alpha=0.3)
            ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

        st.pyplot(fig)

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Input a fresh Session Token in the sidebar to scan for monthly options.")
