import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & SECURITY ---
st.set_page_config(page_title="NIFTY ST + MACD Terminal", layout="wide")
# Auto-refresh every 60 seconds for more frequent updates
st_autorefresh(interval=60000, key="refresh_st_macd")

TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"
API_KEY = "3194b6xL482162_16NkJ368y350336i&"
API_SECRET = "(7@1q7426%p614#fk015~J9%4_$3v6Wh"

# --- 2. LOGIC FUNCTIONS ---
def calculate_supertrend(df, period=10, multiplier=3):
    df = df.copy()
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    hl2 = (high + low) / 2
    upperband = (hl2 + (multiplier * atr)).to_numpy()
    lowerband = (hl2 - (multiplier * atr)).to_numpy()
    close_np = close.to_numpy()
    supertrend = [0.0] * len(df)
    direction = [1] * len(df)

    for i in range(1, len(df)):
        if close_np[i] > upperband[i-1]: direction[i] = 1
        elif close_np[i] < lowerband[i-1]: direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and lowerband[i] < lowerband[i-1]: lowerband[i] = lowerband[i-1]
            if direction[i] == -1 and upperband[i] > upperband[i-1]: upperband[i] = upperband[i-1]
        supertrend[i] = lowerband[i] if direction[i] == 1 else upperband[i]

    prev_dir, curr_dir = direction[-3], direction[-2]
    status = "BUY" if (prev_dir == -1 and curr_dir == 1) else "SELL" if (prev_dir == 1 and curr_dir == -1) else ("HOLD BUY" if curr_dir == 1 else "HOLD SELL")
    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index), status

def calculate_macd(df):
    close = df['close']
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    for col in ['open', 'high', 'low', 'close']: df[col] = pd.to_numeric(df[col], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df.set_index('datetime').resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna().reset_index()

def show_indicator(col, title, status, ltp):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""<div style="background-color:{bg}; padding:20px; border-radius:12px; text-align:center; border: 1px solid #444;">
        <p style="margin:0; color: white; font-size: 1rem; opacity: 0.8;">{title}</p>
        <h1 style="margin:10px 0; color: white; font-size: 2.2rem; font-weight: bold;">{status}</h1>
        <p style="margin:0; color: white; font-size: 1.2rem;">LTP: ₹{ltp}</p></div>""", unsafe_allow_html=True)

# --- 3. MAIN TERMINAL ---
st.sidebar.header("🔐 Breeze Login")
session_token = st.sidebar.text_input("Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=API_KEY)
        breeze.generate_session(api_secret=API_SECRET, session_token=session_token)
        
        # Calculate Expiry
        today = datetime.today()
        expiry = today + timedelta(days=((1 - today.weekday()) % 7) + 6)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        def get_live_data_and_strike(right):
            # Fetch full chain
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=right)
            df_opt = pd.DataFrame(chain["Success"])
            df_opt['ltp'] = pd.to_numeric(df_opt['ltp'])
            df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
            
            # Filter 100-step strikes and find closest to 60
            df_opt = df_opt[df_opt['strike_price'] % 100 == 0]
            df_opt['diff'] = (df_opt['ltp'] - 60).abs()
            best_row = df_opt.sort_values('diff').iloc[0]
            strike = str(int(best_row['strike_price']))
            
            # Get actual LIVE QUOTE for this specific strike to ensure it's up to date
            quote = breeze.get_quotes(stock_code="NIFTY", exchange_code="NFO", expiry_date=expiry_iso, product_type="options", right=right, strike_price=strike)
            live_ltp = quote['Success'][0]['ltp']
            
            return strike, live_ltp

        with st.spinner("Fetching Live Quotes..."):
            c_s, c_ltp_live = get_live_data_and_strike("call")
            p_s, p_ltp_live = get_live_data_and_strike("put")

            def get_hist_analysis(strike, right):
                from_d = (datetime.now()-timedelta(days=15)).strftime("%Y-%m-%dT09:15:00.000Z")
                to_d = datetime.now().strftime("%Y-%m-%dT15:30:00.000Z")
                res = breeze.get_historical_data(interval="5minute", from_date=from_d, to_date=to_d, stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=right, strike_price=strike)
                df = process_data(pd.DataFrame(res["Success"]))
                st_l, st_d, stat = calculate_supertrend(df)
                m, sl, h = calculate_macd(df)
                return df, st_l, st_d, m, sl, h, stat

            # Analysis based on history
            df_ce, stl_ce, std_ce, m_ce, sl_ce, h_ce, stat_ce = get_hist_analysis(c_s, "call")
            df_pe, stl_pe, std_pe, m_pe, sl_pe, h_pe, stat_pe = get_hist_analysis(p_s, "put")

            # UI Header
            st.title("🏛 NIFTY Real-Time Terminal")
            st.info(f"📅 Expiry: {expiry_iso[:10]} | 🔄 Last Sync: {datetime.now().strftime('%H:%M:%S')} | 🎯 Target: ₹60 (100-Step)")

            # Indicator boxes with LIVE LTP
            cols = st.columns(2)
            show_indicator(cols[0], f"CALL {c_s}", stat_ce, c_ltp_live)
            show_indicator(cols[1], f"PUT {p_s}", stat_pe, p_ltp_live)

    except Exception as e:
        st.error(f"Error fetching data: {e}. Check if market is open or session is valid.")
else:
    st.info("Waiting for Session Token...")
