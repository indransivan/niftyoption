import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta
import calendar
import os
from breeze_connect import BreezeConnect

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="NIFTY MACD Dashboard", layout="wide")
st.title("🚀 Live NIFTY Options MACD Dashboard")

# --- AUTHENTICATION ---
# Use Render Environment Variables instead of hardcoding keys
API_KEY = os.getenv("BREEZE_API_KEY")
API_SECRET = os.getenv("BREEZE_API_SECRET")
# For a web app, you might need a way to input the session token manually or via URL
session_token = st.sidebar.text_input("Enter Session Token", type="password")

if not session_token:
    st.warning("Please enter your Breeze Session Token in the sidebar to begin.")
    st.stop()

@st.cache_resource
def get_breeze_client(api_key, api_secret, token):
    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=token)
    return breeze

try:
    breeze = get_breeze_client(API_KEY, API_SECRET, session_token)
except Exception as e:
    st.error(f"Login failed: {e}")
    st.stop()

# --- UTILITY FUNCTIONS ---
def get_next_month_expiry():
    today = datetime.today()
    year, month = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
    last_day = calendar.monthrange(year, month)[1]
    expiry = datetime(year, month, last_day)
    while expiry.weekday() != 3:  # 3 is Thursday
        expiry -= timedelta(days=1)
    return expiry.strftime("%d-%b-%Y"), expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd(df):
    if len(df) < 26: return None, None, None
    close_prices = pd.to_numeric(df['close']).dropna()
    ema12 = close_prices.ewm(span=12, adjust=False).mean()
    ema26 = close_prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

# --- DATA FETCHING ---
expiry_str, expiry_iso = get_next_month_expiry()

def fetch_data(symbol, strike, right, expiry):
    to_date = datetime.now()
    from_date = to_date - timedelta(days=10)
    res = breeze.get_historical_data(
        interval="5minute",
        from_date=from_date.strftime("%Y-%m-%dT09:15:00.000Z"),
        to_date=to_date.strftime("%Y-%m-%dT15:30:00.000Z"),
        stock_code="NIFTY", exchange_code="NFO", product_type="options",
        expiry_date=expiry, right=right, strike_price=str(strike)
    )
    if res.get("Success"):
        df = pd.DataFrame(res["Success"])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        return df
    return pd.DataFrame()

# --- UI LAYOUT ---
col1, col2 = st.columns(2)
call_strike = col1.number_input("Call Strike", value=26100)
put_strike = col2.number_input("Put Strike", value=24100)

if st.button("Refresh Data"):
    df_call = fetch_data("NIFTY", call_strike, "Call", expiry_iso)
    df_put = fetch_data("NIFTY", put_strike, "Put", expiry_iso)

    if not df_call.empty and not df_put.empty:
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        # (Insert your plotting logic here using the dataframes)
        # For brevity, I'm using a placeholder:
        st.pyplot(fig)
    else:
        st.error("Could not fetch data. Check if markets are open or token is valid.")
