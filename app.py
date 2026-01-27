import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import os
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY Next-Month ₹100 MACD", layout="wide")

# --- UTILITY: CALCULATE NEXT MONTH'S LAST TUESDAY ---
def get_next_monthly_expiry():
    today = datetime.today()
    # Move to the first day of next month
    if today.month == 12:
        next_month_date = datetime(today.year + 1, 1, 1)
    else:
        next_month_date = datetime(today.year, today.month + 1, 1)
    
    # Find the last day of that next month
    last_day_num = calendar.monthrange(next_month_date.year, next_month_date.month)[1]
    expiry = datetime(next_month_date.year, next_month_date.month, last_day_num)
    
    # Backtrack to the last Tuesday (weekday 1)
    while expiry.weekday() != 1:
        expiry -= timedelta(days=1)
        
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd(df):
    if df.empty or len(df) < 26: return None, None, None
    close = pd.to_numeric(df['close']).dropna()
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
    # Clean 15m resampling
    df = df.set_index('datetime').resample('15min').agg({'close':'last'}).dropna()
    df = df.reset_index(drop=True)
    df.index += 1 # Index as 1, 2, 3...
    return df

# --- SIDEBAR & AUTH ---
st.sidebar.header("🔐 Breeze Login")
api_key = st.sidebar.text_input("API Key", value="3194b6xL482162_16NkJ368y350336i&")
api_secret = st.sidebar.text_input("API Secret", type="password", value="(7@1q7426%p614#fk015~J9%4_$3v6Wh")
session_token = st.sidebar.text_input("Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        
        expiry_iso = get_next_monthly_expiry()
        expiry_display = datetime.strptime(expiry_iso, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%B %d, %Y")
        
        st.subheader(f"📅 Target Expiry: {expiry_display} (Last Tuesday of Next Month)")

        # 1. AUTO-SCAN FOR ₹100 STRIKES
        def find_strike(right):
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", 
                                                   product_type="options", expiry_date=expiry_iso, right=right)
            if chain.get("Success"):
                df_chain = pd.DataFrame(chain["Success"])
                df_chain['ltp'] = pd.to_numeric(df_chain['ltp'])
                df_chain['diff'] = abs(df_chain['ltp'] - 100)
                best = df_chain.sort_values('diff').iloc[0]
                return str(best['strike_price']), best['ltp']
            return None, None

        with st.spinner("Scanning next month's chain for ₹100 premiums..."):
            c_strike, c_ltp = find_strike("call")
            p_strike, p_ltp = find_strike("put")

        if c_strike and p_strike:
            st.success(f"CALL: {c_strike} (₹{c_ltp}) | PUT: {p_strike} (₹{p_ltp})")

            # 2. FETCH HISTORY
            to_date = datetime.now()
            from_date = to_date - timedelta(days=12) # Buffer for MACD calculation

            def get_hist(s, r):
                res = breeze.get_historical_data(interval="5minute", 
                    from_date=from_date.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_date.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"])) if res.get("Success") else pd.DataFrame()

            df_c = get_hist(c_strike, "call")
            df_p = get_hist(p_strike, "put")

            # 3. MACD ONLY PLOTTING
            plt.style.use('dark_background')
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), facecolor='#0e1117')
            
            def plot_macd_only(ax, df, title, color):
                m, s, h = calculate_macd(df)
                if m is not None:
                    ax.plot(df.index, m, color=color, label='MACD', linewidth=2)
                    ax.plot(df.index, s, color='white', label='Signal', linestyle='--', alpha=0.7)
                    ax.bar(df.index, h, color=['#00ff88' if x > 0 else '#ff4444' for x in h], alpha=0.4)
                    ax.set_title(f"{title} MACD Indicator", loc='left', fontsize=12)
                    ax.set_facecolor('#161a25')
                    ax.grid(alpha=0.1)
                    ax.legend(loc='upper left')

            plot_macd_only(ax1, df_c, f"CALL {c_strike}", "#00ff88")
            plot_macd_only(ax2, df_p, f"PUT {p_strike}", "#ff4444")

            plt.tight_layout()
            st.pyplot(fig)
        else:
            st.error("No data found for the next month's expiry. Please check if the series is active.")

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Please enter your Session Token to begin.")
