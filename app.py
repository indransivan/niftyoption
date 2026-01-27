import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import os
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY Monthly MACD", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    div.stButton > button:first-child { background-color: #00ff88; color: black; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: AUTHENTICATION ---
st.sidebar.header("🔐 Authentication")
api_key = st.sidebar.text_input("API Key", value=os.getenv("BREEZE_API_KEY", "3194b6xL482162_16NkJ368y350336i&"))
api_secret = st.sidebar.text_input("API Secret", type="password", value=os.getenv("BREEZE_API_SECRET", "(7@1q7426%p614#fk015~J9%4_$3v6Wh"))
session_token = st.sidebar.text_input("Fresh Session Token", type="password")

st.sidebar.divider()
st.sidebar.header("⚙️ Strategy Settings")
target_price = st.sidebar.number_input("Target Premium (Rs)", value=100)

# --- UTILITY FUNCTIONS ---
def get_last_tuesday(date_obj):
    """Finds the last Tuesday of the month for a given date."""
    last_day = calendar.monthrange(date_obj.year, date_obj.month)[1]
    expiry = datetime(date_obj.year, date_obj.month, last_day)
    # 1 is Tuesday
    while expiry.weekday() != 1:
        expiry -= timedelta(days=1)
    return expiry

def get_monthly_expiry():
    """Returns the ISO string for the current month's last Tuesday (or next if passed)."""
    today = datetime.today()
    current_expiry = get_last_tuesday(today)
    
    # If today is past the monthly expiry, move to next month
    if today.date() > current_expiry.date():
        next_month = today.replace(day=28) + timedelta(days=7) # Safely move to next month
        current_expiry = get_last_tuesday(next_month)
        
    return current_expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd(df):
    if df is None or len(df) < 26: return None, None, None
    close_prices = pd.to_numeric(df['close'], errors='coerce').dropna()
    ema12 = close_prices.ewm(span=12, adjust=False).mean()
    ema26 = close_prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def resample_and_index(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    resampled = df.resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna()
    resampled = resampled.reset_index(drop=True)
    resampled.index += 1
    return resampled

# --- MAIN LOGIC ---
if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_monthly_expiry()
        
        # 1. Get Spot Price
        spot = breeze.get_quotes(stock_code="NIFTY", exchange_code="NSE")
        spot_price = float(spot['Success'][0]['ltp'])
        atm = round(spot_price / 100) * 100
        
        # 2. Strike Scanner (Finding ~100 Rs Premium)
        def find_strike(right):
            # Scan a range of 10 strikes around ATM
            strikes = [atm + (i * 100) for i in range(-5, 6)]
            best_strike = atm
            min_diff = float('inf')
            
            for s in strikes:
                q = breeze.get_quotes(stock_code="NIFTY", exchange_code="NFO", 
                                      expiry_date=expiry_iso, right=right, strike_price=str(s))
                if q.get("Success"):
                    ltp = float(q["Success"][0]["ltp"])
                    diff = abs(ltp - target_price)
                    if diff < min_diff:
                        min_diff = diff
                        best_strike = s
            return best_strike

        with st.spinner("Scanning for ₹100 strikes..."):
            call_strike = find_strike("Call")
            put_strike = find_strike("Put")

        # 3. Fetch Historical Data
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=10)
        
        def fetch_hist(strike, right):
            res = breeze.get_historical_data(
                interval="5minute", from_date=from_dt.strftime("%Y-%m-%dT09:15:00.000Z"),
                to_date=to_dt.strftime("%Y-%m-%dT15:30:00.000Z"),
                stock_code="NIFTY", exchange_code="NFO", product_type="options",
                expiry_date=expiry_iso, right=right, strike_price=str(strike)
            )
            return pd.DataFrame(res["Success"]) if res.get("Success") else pd.DataFrame()

        df_c = resample_and_index(fetch_hist(call_strike, "Call"))
        df_p = resample_and_index(fetch_hist(put_strike, "Put"))

        # 4. Plotting
        st.title(f"🚀 NIFTY Monthly: {expiry_iso[:10]}")
        col1, col2 = st.columns(2)
        col1.metric("Selected Call", f"{call_strike} CE")
        col2.metric("Selected Put", f"{put_strike} PE")

        plt.style.use('dark_background')
        fig, axes = plt.subplots(2, 2, figsize=(15, 10), facecolor='#0e1117')
        
        # Helper for plotting inside the loop
        def plot_pair(df, row, color, title):
            m, s, h = calculate_macd(df)
            axes[row, 0].plot(df.index, df['close'], color=color)
            axes[row, 0].set_title(f"{title} Price", color='white')
            if m is not None:
                axes[row, 1].plot(df.index, m, color=color, label='MACD')
                axes[row, 1].plot(df.index, s, color='orange', label='Signal')
                axes[row, 1].bar(df.index, h, color=['green' if x > 0 else 'red' for x in h], alpha=0.3)
                axes[row, 1].set_title(f"{title} MACD", color='white')

        plot_pair(df_c, 0, '#00ff88', f"Call {call_strike}")
        plot_pair(df_p, 1, '#ff4444', f"Put {put_strike}")

        for ax in axes.flat:
            ax.set_xlabel("Candle Index (15m)")
            ax.set_facecolor('#161a25')
            ax.grid(alpha=0.2)

        st.pyplot(fig)

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Input Session Token to scan for ₹100 monthly options.")
