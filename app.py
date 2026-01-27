import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import os
from breeze_connect import BreezeConnect

# --- PAGE CONFIG ---
st.set_page_config(page_title="NIFTY Zero-Cross Strategy", layout="wide")

# --- UTILITY: NEXT MONTHLY EXPIRY ---
def get_next_monthly_expiry():
    today = datetime.today()
    if today.month == 12:
        next_month_date = datetime(today.year + 1, 1, 1)
    else:
        next_month_date = datetime(today.year, today.month + 1, 1)
    
    last_day_num = calendar.monthrange(next_month_date.year, next_month_date.month)[1]
    expiry = datetime(next_month_date.year, next_month_date.month, last_day_num)
    while expiry.weekday() != 1: # Last Tuesday
        expiry -= timedelta(days=1)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

# --- SIGNAL CALCULATION ---
def get_macd_and_signals(df):
    if df.empty or len(df) < 27: return None, None, None, "WAIT"
    
    close = pd.to_numeric(df['close']).dropna()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    # Buy/Sell Condition (Zero Cross)
    # Current value vs Previous value
    current_macd = macd_line.iloc[-1]
    prev_macd = macd_line.iloc[-2]
    
    status = "NEUTRAL"
    if prev_macd <= 0 and current_macd > 0:
        status = "BUY"
    elif prev_macd >= 0 and current_macd < 0:
        status = "SELL"
    elif current_macd > 0:
        status = "HOLD BUY"
    elif current_macd < 0:
        status = "HOLD SELL"
        
    return macd_line, signal_line, hist, status

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').resample('15min').agg({'close':'last'}).dropna()
    df = df.reset_index(drop=True)
    df.index += 1
    return df

# --- UI & LOGIC ---
st.sidebar.header("🔐 Breeze Login")
api_key = st.sidebar.text_input("API Key", value="3194b6xL482162_16NkJ368y350336i&")
api_secret = st.sidebar.text_input("API Secret", type="password", value="(7@1q7426%p614#fk015~J9%4_$3v6Wh")
session_token = st.sidebar.text_input("Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_next_monthly_expiry()
        
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

        with st.spinner("Analyzing Next Month's Chain..."):
            c_s, c_ltp = find_strike("call")
            p_s, p_ltp = find_strike("put")

        if c_s and p_s:
            to_d = datetime.now()
            from_d = to_d - timedelta(days=12)

            def fetch(s, r):
                res = breeze.get_historical_data(interval="5minute", 
                    from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"])) if res.get("Success") else pd.DataFrame()

            df_c = fetch(c_s, "call")
            df_p = fetch(p_s, "put")

            # GET DATA & SIGNALS
            m_c, s_c, h_c, stat_c = get_macd_and_signals(df_c)
            m_p, s_p, h_p, stat_p = get_macd_and_signals(df_p)

            # --- STATUS DASHBOARD ---
            st.title("🚦 Option Signal Status")
            col1, col2 = st.columns(2)
            
            def show_indicator(col, title, strike, ltp, status):
                color = "green" if "BUY" in status else "red" if "SELL" in status else "gray"
                col.markdown(f"""
                    <div style="background-color:{color}; padding:20px; border-radius:10px; text-align:center;">
                        <h2 style="color:white; margin:0;">{title} {strike}</h2>
                        <h1 style="color:white; margin:10px 0;">{status}</h1>
                        <p style="color:white; margin:0;">Current Price: ₹{ltp}</p>
                    </div>
                """, unsafe_allow_html=True)

            show_indicator(col1, "CALL", c_s, c_ltp, stat_c)
            show_indicator(col2, "PUT", p_s, p_ltp, stat_p)

            # --- PLOTTING ---
            plt.style.use('dark_background')
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), facecolor='#0e1117')
            
            def plot_signals(ax, df, m, s, h, title, line_color):
                if m is not None:
                    ax.axhline(0, color='white', linewidth=0.8, linestyle='-') # Zero Line
                    ax.plot(df.index, m, color=line_color, label='MACD', linewidth=2)
                    ax.plot(df.index, s, color='orange', label='Signal', linestyle='--', alpha=0.6)
                    ax.bar(df.index, h, color=['#00ff88' if x > 0 else '#ff4444' for x in h], alpha=0.3)
                    ax.set_title(f"{title} MACD", loc='left')
                    ax.legend(loc='upper left')
                    ax.grid(alpha=0.1)

            plot_signals(ax1, df_c, m_c, s_c, h_c, f"CALL {c_s}", "#00ff88")
            plot_signals(ax2, df_p, m_p, s_p, h_p, f"PUT {p_s}", "#ff4444")
            
            st.pyplot(fig)
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Input Session Token to scan next-month options.")
