import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import os
import time
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY Live MACD", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    div.stButton > button:first-child { background-color: #00ff88; color: black; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: AUTHENTICATION ---
st.sidebar.header("🔐 Authentication")
# It's better to set these in Render Environment Variables
api_key = st.sidebar.text_input("API Key", value=os.getenv("BREEZE_API_KEY", "3194b6xL482162_16NkJ368y350336i&"))
api_secret = st.sidebar.text_input("API Secret", type="password", value=os.getenv("BREEZE_API_SECRET", "(7@1q7426%p614#fk015~J9%4_$3v6Wh"))
session_token = st.sidebar.text_input("Fresh Session Token", type="password")

st.sidebar.divider()
st.sidebar.header("⚙️ Settings")
target_premium = st.sidebar.slider("Target Premium", 50, 500, 100)
# Manual Expiry Override if the calculation fails
manual_expiry = st.sidebar.text_input("Manual Expiry (Optional)", placeholder="YYYY-MM-DDT07:00:00.000Z")

# --- UTILITY FUNCTIONS ---
def get_next_month_expiry():
    today = datetime.today()
    year = today.year
    month = today.month + 1
    if month > 12:
        month = 1; year += 1
    last_day = calendar.monthrange(year, month)[1]
    expiry = datetime(year, month, last_day)
    while expiry.weekday() != 1:  # Thursday
        expiry -= timedelta(days=1)
    # Returns (Display Format, API Format)
    return expiry.strftime("%d-%b-%Y"), expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd(df):
    if df is None or len(df) < 26: return None, None, None
    close_prices = pd.to_numeric(df['close'], errors='coerce').dropna()
    ema12 = close_prices.ewm(span=12, adjust=False).mean()
    ema26 = close_prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def resample_to_15min(df_5min):
    if df_5min is None or df_5min.empty: return pd.DataFrame()
    df = df_5min.copy()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['close'])
    return df.resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna()

# --- APP EXECUTION ---
if session_token:
    try:
        # 1. Connect
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        
        # 2. Get Expiry & Spot
        calc_expiry_str, calc_expiry_iso = get_next_month_expiry()
        expiry_iso = manual_expiry if manual_expiry else calc_expiry_iso
        
        spot = breeze.get_quotes(stock_code="NIFTY", exchange_code="NSE")
        if not spot.get("Success"):
            st.error("Could not fetch NIFTY Spot. Check API Connection.")
            st.stop()
            
        spot_price = float(spot['Success'][0]['ltp'])
        atm = round(spot_price / 100) * 100
        
        st.sidebar.success(f"Connected! Spot: {spot_price}")
        
        # 3. Data Fetching
        with st.spinner(f"Fetching data for {expiry_iso}..."):
            # Set time window (Handling weekends by looking back 10 days)
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=10)
            
            def get_data(strike, right):
                res = breeze.get_historical_data(
                    interval="5minute",
                    from_date=from_dt.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_dt.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=right, strike_price=str(strike)
                )
                if res and res.get("Success"):
                    df = pd.DataFrame(res["Success"])
                    if not df.empty:
                        df["datetime"] = pd.to_datetime(df["datetime"])
                        return df.set_index("datetime")
                return pd.DataFrame()

            # For now, using ATM +/- 200 for stability
            df_call_5 = get_data(atm + 200, "Call")
            df_put_5 = get_data(atm - 200, "Put")

        # 4. Display Results
        if not df_call_5.empty and not df_put_5.empty:
            df_c15 = resample_to_15min(df_call_5)
            df_p15 = resample_to_15min(df_put_5)

            st.header(f"🚀 NIFTY Dashboard (ATM: {atm})")
            
            fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor='#0e1117')
            plt.subplots_adjust(hspace=0.4)

            # --- PLOTTING LOGIC ---
            # Call Price & MACD
            m_c, s_c, h_c = calculate_macd(df_c15)
            axes[0,0].plot(df_c15.index, df_c15['close'], color='#00ff88')
            axes[0,0].set_title(f"Call {atm+200} CE Price", color='white')
            
            if m_c is not None:
                axes[0,1].plot(m_c.index, m_c, color='#00ff88', label='MACD')
                axes[0,1].plot(s_c.index, s_c, color='orange', label='Signal')
                axes[0,1].bar(h_c.index, h_c, color=['green' if x > 0 else 'red' for x in h_c], alpha=0.3)
                axes[0,1].set_title("Call MACD", color='white')

            # Put Price & MACD
            m_p, s_p, h_p = calculate_macd(df_p15)
            axes[1,0].plot(df_p15.index, df_p15['close'], color='#ff4444')
            axes[1,0].set_title(f"Put {atm-200} PE Price", color='white')

            if m_p is not None:
                axes[1,1].plot(m_p.index, m_p, color='#ff4444', label='MACD')
                axes[1,1].plot(s_p.index, s_p, color='orange', label='Signal')
                axes[1,1].bar(h_p.index, h_p, color=['green' if x > 0 else 'red' for x in h_p], alpha=0.3)
                axes[1,1].set_title("Put MACD", color='white')

            for ax in axes.flat:
                ax.set_facecolor('#1e2129')
                ax.tick_params(colors='white')
                ax.grid(alpha=0.1)
            
            st.pyplot(fig)
        else:
            st.warning(f"No data found for Expiry: {expiry_iso}")
            st.info("If today is a weekend or market is closed, the API might return empty results.")
            
            with st.expander("🔍 Debug API Response"):
                st.write("Call API Test Response:", get_data(atm + 200, "Call"))

    except Exception as e:
        st.error(f"Handshake Error: {e}")
else:
    st.info("Please enter your **Session Token** in the sidebar to begin.")
