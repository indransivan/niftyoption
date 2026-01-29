import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import calendar
import requests
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION & REFRESH ---
st.set_page_config(page_title="NIFTY Index & Options Live", layout="wide")
st_autorefresh(interval=300000, key="fivedash") # 5-minute refresh

# --- 2. TELEGRAM SETTINGS ---
TELE_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELE_CHAT_ID = "YOUR_CHAT_ID_HERE"

def send_telegram(msg):
    if "YOUR_BOT_TOKEN" in TELE_TOKEN: return 
    url = f"https://api.telegram.org/bot8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        st.error(f"Telegram failed: {e}")

# --- 3. LOGIC FUNCTIONS ---
def get_next_monthly_expiry():
    today = datetime.today()
    year, month = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
    last_day = calendar.monthrange(year, month)[1]
    expiry = datetime(year, month, last_day)
    while expiry.weekday() != 1: # Last Tuesday
        expiry -= timedelta(days=1)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd_and_signal(df):
    if df.empty or len(df) < 30: return None, None, None, "WAIT"
    close = pd.to_numeric(df['close']).dropna()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    curr, prev = macd_line.iloc[-1], macd_line.iloc[-2]
    if prev <= 0 and curr > 0: status = "BUY"
    elif prev >= 0 and curr < 0: status = "SELL"
    else: status = "HOLD BUY" if curr > 0 else "HOLD SELL"
    
    return macd_line, signal_line, hist, status

def process_data(df_raw, is_index=False):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    # Resample to 15min. Index data usually has 'close', Options usually have 'close'
    df = df.set_index('datetime').resample('15min').agg({'close':'last'}).dropna()
    df = df.reset_index(drop=True)
    df.index += 1
    return df

# --- 4. STREAMLIT UI ---
st.sidebar.header("🔐 Breeze Login")
api_key = st.sidebar.text_input("API Key", value="3194b6xL482162_16NkJ368y350336i&")
api_secret = st.sidebar.text_input("API Secret", type="password", value="(7@1q7426%p614#fk015~J9%4_$3v6Wh")
session_token = st.sidebar.text_input("Session Token", type="password")

# Session State for Alert Tracking
if 'ce_last_signal' not in st.session_state: st.session_state.ce_last_signal = None
if 'pe_last_signal' not in st.session_state: st.session_state.pe_last_signal = None
if 'idx_last_signal' not in st.session_state: st.session_state.idx_last_signal = None

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_next_monthly_expiry()
        
        # 1. FETCH NIFTY 50 INDEX DATA
        to_d = datetime.now()
        from_d = to_d - timedelta(days=12)
        
        with st.spinner("Fetching Index & Option Chain..."):
            # Index Spot Data
            idx_res = breeze.get_historical_data(interval="5minute", 
                from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"),
                to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"),
                stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            
            # Option Chain for ₹100 Strikes
            def find_strike(right):
                res = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", 
                                                     product_type="options", expiry_date=expiry_iso, right=right)
                if res.get("Success"):
                    df = pd.DataFrame(res["Success"])
                    df['ltp'] = pd.to_numeric(df['ltp'])
                    df['diff'] = abs(df['ltp'] - 100)
                    best = df.sort_values('diff').iloc[0]
                    return str(best['strike_price']), best['ltp']
                return None, None

            c_s, c_ltp = find_strike("call")
            p_s, p_ltp = find_strike("put")

        if idx_res.get("Success") and c_s and p_s:
            # Fetch Options History
            def fetch_opt(s, r):
                res = breeze.get_historical_data(interval="5minute", 
                    from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"])) if res.get("Success") else pd.DataFrame()

            df_idx = process_data(pd.DataFrame(idx_res["Success"]), is_index=True)
            df_c, df_p = fetch_opt(c_s, "call"), fetch_opt(p_s, "put")

            # Calculate MACD
            m_idx, s_idx, h_idx, stat_idx = calculate_macd_and_signal(df_idx)
            m_c, s_c, h_c, stat_c = calculate_macd_and_signal(df_c)
            m_p, s_p, h_p, stat_p = calculate_macd_and_signal(df_p)

            # --- TELEGRAM ALERTS ---
            time_now = datetime.now().strftime("%H:%M")
            if stat_idx in ["BUY", "SELL"] and stat_idx != st.session_state.idx_last_signal:
                send_telegram(f"🏛 *NIFTY 50 INDEX*: {stat_idx} Trend detected at {time_now}")
                st.session_state.idx_last_signal = stat_idx
            if stat_c in ["BUY", "SELL"] and stat_c != st.session_state.ce_last_signal:
                send_telegram(f"🚀 *NIFTY CALL {c_s}*: {stat_c} at ₹{c_ltp} ({time_now})")
                st.session_state.ce_last_signal = stat_c
            if stat_p in ["BUY", "SELL"] and stat_p != st.session_state.pe_last_signal:
                send_telegram(f"📉 *NIFTY PUT {p_s}*: {stat_p} at ₹{p_ltp} ({time_now})")
                st.session_state.pe_last_signal = stat_p

            # --- DASHBOARD ---
            st.title("🏛 NIFTY 50 Strategy Dashboard")
            st.write(f"Last Refresh: {time_now} | Next-Month Expiry: {expiry_iso[:10]}")
            
            # Status Indicators
            cols = st.columns(3)
            data_list = [("NIFTY 50 INDEX", "SPOT", df_idx['close'].iloc[-1] if not df_idx.empty else 0, stat_idx),
                         ("CALL OPTION", f"{c_s} CE", c_ltp, stat_c),
                         ("PUT OPTION", f"{p_s} PE", p_ltp, stat_p)]
            
            for i, (title, strike, price, stat) in enumerate(data_list):
                bg = "#006400" if stat=="BUY" else "#8B0000" if stat=="SELL" else "#1E1E1E"
                cols[i].markdown(f"<div style='background:{bg};padding:15px;border-radius:10px;text-align:center;border:1px solid #444'>"
                                 f"<h5>{title}</h5><h3>{strike}</h3><h1 style='font-size:2.5rem'>{stat}</h1><p>Value: ₹{price}</p></div>", unsafe_allow_html=True)

            # --- PLOTTING ---
            plt.style.use('dark_background')
            fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(14, 15), facecolor='#0e1117')
            
            def plot_macd_view(ax, df, m, s, h, title, color):
                if m is not None:
                    ax.axhline(0, color='white', linewidth=1, alpha=0.5)
                    ax.plot(df.index, m, color=color, label='MACD', linewidth=2)
                    ax.plot(df.index, s, color='orange', linestyle='--', alpha=0.6)
                    ax.bar(df.index, h, color=['#00ff88' if x > 0 else '#ff4444' for x in h], alpha=0.3)
                    ax.set_title(f"{title} MACD", loc='left', fontsize=12)
                    ax.set_facecolor('#161a25')
                    ax.grid(alpha=0.1)

            plot_macd_view(ax0, df_idx, m_idx, s_idx, h_idx, "NIFTY 50 INDEX", "#3498db") # Blue for Index
            plot_macd_view(ax1, df_c, m_c, s_c, h_c, f"CALL {c_s}", "#00ff88") # Green for Call
            plot_macd_view(ax2, df_p, m_p, s_p, h_p, f"PUT {p_s}", "#ff4444") # Red for Put
            
            plt.tight_layout()
            st.pyplot(fig)
            
    except Exception as e: st.error(f"Error: {e}")
else:
    st.info("👋 Enter Session Token to monitor Nifty Index and ₹100 Options.")
