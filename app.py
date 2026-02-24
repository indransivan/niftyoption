import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
import pytz # Added for timezone handling
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS ---
st.set_page_config(page_title="NIFTY IST Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_st_macd")

# Timezone for India
IST = pytz.timezone('Asia/Kolkata')

API_KEY = "3194b6xL482162_16NkJ368y350336i&"
API_SECRET = "(7@1q7426%p614#fk015~J9%4_$3v6Wh"

# --- 2. DATA PROCESSING (THE FIX) ---
def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    
    df = df_raw.copy()
    # Convert columns to numeric
    for col in ['open', 'high', 'low', 'close']: 
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Convert to Datetime and ensure it's treated as IST
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    # --- CRITICAL FIX FOR ACTUAL CANDLES ---
    # We use 'origin=start_day' and 'offset' to align with 09:15 AM Market Open
    df = df.set_index('datetime').resample('15min', origin='start_day', offset='15min').agg({
        'open': 'first', 
        'high': 'max', 
        'low': 'min', 
        'close': 'last'
    }).dropna()
    
    return df.reset_index()

# --- 3. INDICATORS ---
def calculate_supertrend(df, period=10, multiplier=3):
    if df.empty: return None, None, "N/A"
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

    status = "HOLD BUY" if direction[-1] == 1 else "HOLD SELL"
    if direction[-1] == 1 and direction[-2] == -1: status = "BUY"
    if direction[-1] == -1 and direction[-2] == 1: status = "SELL"
    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index), status

def calculate_macd(df):
    close = df['close']
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

# --- 4. UI & MAIN ---
def show_indicator(col, title, status, ltp):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""<div style="background-color:{bg}; padding:20px; border-radius:12px; text-align:center; color:white;">
        <p style="margin:0; opacity: 0.8;">{title}</p>
        <h1 style="margin:10px 0; font-size: 2.2rem;">{status}</h1>
        <p style="margin:0; font-size: 1.2rem;">LTP: ₹{ltp}</p></div>""", unsafe_allow_html=True)

def draw_chart(df, stl, std, m, sl, h, title):
    v_df = df.tail(150).reset_index(drop=True)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=v_df['datetime'], open=v_df['open'], high=v_df['high'], low=v_df['low'], close=v_df['close'], name='Price'), row=1, col=1)
    
    # Add Supertrend
    v_stl = stl.tail(150).reset_index(drop=True)
    v_std = std.tail(150).reset_index(drop=True)
    for i in range(1, len(v_stl)):
        color = "#00ff88" if v_std[i] == 1 else "#ff4444"
        fig.add_trace(go.Scatter(x=[v_df['datetime'][i-1], v_df['datetime'][i]], y=[v_stl[i-1], v_stl[i]], mode='lines', line=dict(color=color, width=2), showlegend=False), row=1, col=1)

    fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, title=title)
    st.plotly_chart(fig, use_container_width=True)

# Main Login Logic
session_token = st.sidebar.text_input("Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=API_KEY)
        breeze.generate_session(api_secret=API_SECRET, session_token=session_token)
        
        # Indian Expiry Logic
        expiry = (datetime.now(IST) + timedelta(days=((1 - datetime.now(IST).weekday()) % 7) + 6)).strftime("%Y-%m-%dT07:00:00.000Z")

        def get_data(right):
            # Strike Selection
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry, right=right)
            df_opt = pd.DataFrame(chain["Success"])
            df_opt = df_opt[pd.to_numeric(df_opt['strike_price']) % 100 == 0]
            df_opt['diff'] = (pd.to_numeric(df_opt['ltp']) - 60).abs()
            strike = str(int(df_opt.sort_values('diff').iloc[0]['strike_price']))

            # Live Price (The 'Actual' now price)
            live = breeze.get_quotes(stock_code="NIFTY", exchange_code="NFO", expiry_date=expiry, product_type="options", right=right, strike_price=strike)
            live_ltp = live['Success'][0]['ltp']

            # History
            hist = breeze.get_historical_data(interval="5minute", from_date=(datetime.now(IST)-timedelta(days=15)).strftime("%Y-%m-%dT09:15:00.000Z"), to_date=datetime.now(IST).strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry, right=right, strike_price=strike)
            df = process_data(pd.DataFrame(hist["Success"]))
            stl, std, stat = calculate_supertrend(df)
            m, sl, h = calculate_macd(df)
            return strike, live_ltp, df, stl, std, m, sl, h, stat

        c_s, c_ltp, c_df, c_stl, c_std, c_m, c_sl, c_h, c_stat = get_data("call")
        p_s, p_ltp, p_df, p_stl, p_std, p_m, p_sl, p_h, p_stat = get_data("put")

        st.title("🏛 NIFTY Options Terminal (IST Aligned)")
        st.info(f"Market Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST")

        col1, col2 = st.columns(2)
        show_indicator(col1, f"CALL {c_s}", c_stat, c_ltp)
        show_indicator(col2, f"PUT {p_s}", p_stat, p_ltp)

        draw_chart(c_df, c_stl, c_std, c_m, c_sl, c_h, "CALL")
        draw_chart(p_df, p_stl, p_std, p_m, p_sl, p_h, "PUT")

    except Exception as e: st.error(f"Error: {e}")
