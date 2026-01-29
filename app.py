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
st.set_page_config(page_title="NIFTY Zero-Cross Live", layout="wide")
# Auto-refresh every 5 minutes (300,000 ms)
st_autorefresh(interval=300000, key="fivedash")

# --- 2. TELEGRAM SETTINGS ---
# Replace these with your actual details from @BotFather and @userinfobot
TELE_TOKEN = "AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "8213681556"

def send_telegram(msg):
    if "YOUR_BOT_TOKEN" in TELE_TOKEN: return # Skip if not configured
    url = f"https://api.telegram.org/bot8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        st.error(f"Telegram failed: {e}")

# --- 3. LOGIC FUNCTIONS ---
def get_next_monthly_expiry():
    today = datetime.today()
    # If currently Jan, look at Feb. If Dec, look at Jan next year.
    year, month = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
    last_day = calendar.monthrange(year, month)[1]
    expiry = datetime(year, month, last_day)
    while expiry.weekday() != 1: # 1 = Tuesday
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
    
    # Logic: Crossover of Zero Line
    curr, prev = macd_line.iloc[-1], macd_line.iloc[-2]
    if prev <= 0 and curr > 0: status = "BUY"
    elif prev >= 0 and curr < 0: status = "SELL"
    else: status = "HOLD BUY" if curr > 0 else "HOLD SELL"
    
    return macd_line, signal_line, hist, status

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
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

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_next_monthly_expiry()
        
        # FIND STRIKES
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

        with st.spinner("Syncing Live Data..."):
            c_s, c_ltp = find_strike("call")
            p_s, p_ltp = find_strike("put")

        if c_s and p_s:
            # FETCH HISTORY
            to_d = datetime.now()
            from_d = to_d - timedelta(days=12)
            
            def fetch(s, r):
                res = breeze.get_historical_data(interval="5minute", 
                    from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"])) if res.get("Success") else pd.DataFrame()

            df_c, df_p = fetch(c_s, "call"), fetch(p_s, "put")
            m_c, s_c, h_c, stat_c = calculate_macd_and_signal(df_c)
            m_p, s_p, h_p, stat_p = calculate_macd_and_signal(df_p)

            # --- TELEGRAM ALERTS ---
            time_now = datetime.now().strftime("%H:%M")
            if stat_c in ["BUY", "SELL"] and stat_c != st.session_state.ce_last_signal:
                send_telegram(f"🚀 *NIFTY CALL {c_s}*: {stat_c} at ₹{c_ltp} ({time_now})")
                st.session_state.ce_last_signal = stat_c
            if stat_p in ["BUY", "SELL"] and stat_p != st.session_state.pe_last_signal:
                send_telegram(f"📉 *NIFTY PUT {p_s}*: {stat_p} at ₹{p_ltp} ({time_now})")
                st.session_state.pe_last_signal = stat_p

            # --- DASHBOARD ---
            st.title("📊 NIFTY Zero-Cross Strategy")
            st.write(f"Refreshed: {time_now} | Target Expiry: {expiry_iso[:10]}")
            
            c1, c2 = st.columns(2)
            for col, title, strike, ltp, stat in [(c1,"CALL",c_s,c_ltp,stat_c), (c2,"PUT",p_s,p_ltp,stat_p)]:
                color = "#006400" if stat=="BUY" else "#8B0000" if stat=="SELL" else "#262730"
                col.markdown(f"<div style='background:{color};padding:20px;border-radius:10px;text-align:center;border:1px solid #444'>"
                             f"<h3>{title} {strike}</h3><h1 style='font-size:3rem'>{stat}</h1><p>Price: ₹{ltp}</p></div>", unsafe_allow_html=True)

            # --- PLOTTING ---
            plt.style.use('dark_background')
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), facecolor='#0e1117')
            
            def plot_macd(ax, df, m, s, h, title, color):
                if m is not None:
                    ax.axhline(0, color='white', linewidth=1, alpha=0.5)
                    ax.plot(df.index, m, color=color, label='MACD', linewidth=2)
                    ax.plot(df.index, s, color='orange', linestyle='--', alpha=0.6)
                    ax.bar(df.index, h, color=['#00ff88' if x > 0 else '#ff4444' for x in h], alpha=0.3)
                    ax.set_title(f"{title} MACD Indicator", loc='left')
                    ax.set_facecolor('#161a25')
            
            plot_macd(ax1, df_c, m_c, s_c, h_c, f"CALL {c_s}", "#00ff88")
            plot_macd(ax2, df_p, m_p, s_p, h_p, f"PUT {p_s}", "#ff4444")
            plt.tight_layout()
            st.pyplot(fig)
            
    except Exception as e: st.error(f"Error: {e}")
else:
    st.info("👋 Enter Session Token to start 5-minute live tracking.")
