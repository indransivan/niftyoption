import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import os
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY ₹100 Scanner", layout="wide")

# --- UTILITY: MONTHLY EXPIRY (LAST TUESDAY) ---
def get_last_tuesday(date_obj):
    last_day = calendar.monthrange(date_obj.year, date_obj.month)[1]
    expiry = datetime(date_obj.year, date_obj.month, last_day)
    while expiry.weekday() != 1: # 1 = Tuesday
        expiry -= timedelta(days=1)
    return expiry

def get_monthly_expiry():
    today = datetime.today()
    expiry = get_last_tuesday(today)
    # If today is past the last Tuesday, get next month's
    if today.date() > expiry.date():
        next_month = (today.replace(day=28) + timedelta(days=7))
        expiry = get_last_tuesday(next_month)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

# --- DATA PROCESSING ---
def calculate_macd(df):
    if df.empty or len(df) < 26: return None, None, None
    close = pd.to_numeric(df['close']).dropna()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def process_for_plotting(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna()
    df = df.reset_index(drop=True)
    df.index += 1 # Candle 1, 2, 3...
    return df

# --- MAIN APP ---
st.sidebar.header("🔐 Breeze Login")
api_key = st.sidebar.text_input("API Key", value="3194b6xL482162_16NkJ368y350336i&")
api_secret = st.sidebar.text_input("API Secret", type="password", value="(7@1q7426%p614#fk015~J9%4_$3v6Wh")
session_token = st.sidebar.text_input("Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_monthly_expiry()
        
        st.info(f"Scanning for ₹100 options for Expiry: {expiry_iso[:10]}")

        # 1. SCAN OPTION CHAIN FOR ₹100 PREMIUM
        def find_strike_by_price(right):
            # Fetch entire chain for this expiry
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", 
                                                   product_type="options", expiry_date=expiry_iso, right=right)
            if chain.get("Success"):
                df_chain = pd.DataFrame(chain["Success"])
                df_chain['ltp'] = pd.to_numeric(df_chain['ltp'])
                # Find strike where ltp is closest to 100
                df_chain['diff'] = abs(df_chain['ltp'] - 100)
                best_match = df_chain.sort_values('diff').iloc[0]
                return str(best_match['strike_price']), best_match['ltp']
            return None, None

        call_strike, call_ltp = find_strike_by_price("call")
        put_strike, put_ltp = find_strike_by_price("put")

        if call_strike and put_strike:
            st.success(f"Selected Call: {call_strike} (LTP: ₹{call_ltp}) | Selected Put: {put_strike} (LTP: ₹{put_ltp})")

            # 2. FETCH HISTORICAL DATA
            to_date = datetime.now()
            from_date = to_date - timedelta(days=10)

            def get_hist(s, r):
                res = breeze.get_historical_data(interval="5minute", 
                    from_date=from_date.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_date.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=r, strike_price=s)
                return process_for_plotting(pd.DataFrame(res["Success"])) if res.get("Success") else pd.DataFrame()

            df_c = get_hist(call_strike, "call")
            df_p = get_hist(put_strike, "put")

            # 3. PLOTTING
            plt.style.use('dark_background')
            fig, axes = plt.subplots(2, 2, figsize=(15, 10), facecolor='#0e1117')
            
            for i, (df, title, color) in enumerate([(df_c, f"Call {call_strike}", "#00ff88"), (df_p, f"Put {put_strike}", "#ff4444")]):
                m, s, h = calculate_macd(df)
                # Price Plot
                axes[i,0].plot(df.index, df['close'], color=color, linewidth=2)
                axes[i,0].set_title(f"{title} Price (15m)", color='white')
                # MACD Plot
                if m is not None:
                    axes[i,1].plot(df.index, m, color=color, label='MACD')
                    axes[i,1].plot(df.index, s, color='orange', label='Signal')
                    axes[i,1].bar(df.index, h, color=['green' if x > 0 else 'red' for x in h], alpha=0.3)
                    axes[i,1].set_title(f"{title} MACD", color='white')

            for ax in axes.flat:
                ax.set_facecolor('#161a25')
                ax.set_xlabel("Candle Index")
                ax.grid(alpha=0.2)
            
            st.pyplot(fig)
        else:
            st.error("Could not find suitable ₹100 strikes. Check if market is open or expiry is valid.")

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Please enter your Session Token to automatically find ₹100 options.")
