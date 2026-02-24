import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS ---
st.set_page_config(page_title="NIFTY 150-Candle Terminal", layout="wide")

# Set to 300,000ms (5 minutes) as per your requirement for chart updates
st_autorefresh(interval=300000, key="refresh_sync") 

# Security - Replace with st.secrets in production
TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"
API_KEY = "3194b6xL482162_16NkJ368y350336i&"
API_SECRET = "(7@1q7426%p614#fk015~J9%4_$3v6Wh"

# --- 2. INDICATORS ---
def calculate_supertrend(df, period=10, multiplier=3):
    if df.empty: return None, None, "DATA MISSING"
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

    status = "HOLD BUY" if direction[-1] == 1 else "HOLD SELL"
    if direction[-1] == 1 and direction[-2] == -1: status = "BUY SIGNAL"
    if direction[-1] == -1 and direction[-2] == 1: status = "SELL SIGNAL"
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
    # Aggregate to 15min as per your previous base
    df = df.set_index('datetime').resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    return df.reset_index()

# --- 3. UI ---
def show_indicator(col, title, status, ltp):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""<div style="background-color:{bg}; padding:20px; border-radius:12px; text-align:center; border: 1px solid #444;">
        <p style="margin:0; color: white; font-size: 1rem; opacity: 0.8;">{title}</p>
        <h1 style="margin:10px 0; color: white; font-size: 2.2rem; font-weight: bold;">{status}</h1>
        <p style="margin:0; color: white; font-size: 1.2rem;">Current LTP: ₹{ltp}</p></div>""", unsafe_allow_html=True)

def draw_combined_chart(df, st_line, st_dir, m, s, h, title):
    if df.empty: return
    # Slicing exactly 150 candles for the plot
    v_df = df.tail(150).reset_index(drop=True)
    v_st = st_line.tail(150).reset_index(drop=True)
    v_dir = st_dir.tail(150).reset_index(drop=True)
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=v_df.index, open=v_df['open'], high=v_df['high'], low=v_df['low'], close=v_df['close'], name='Price'), row=1, col=1)
    
    for i in range(1, len(v_st)):
        color = "#00ff88" if v_dir[i] == 1 else "#ff4444"
        fig.add_trace(go.Scatter(x=[i-1, i], y=[v_st[i-1], v_st[i]], mode='lines', line=dict(color=color, width=3), showlegend=False), row=1, col=1)

    fig.add_trace(go.Scatter(x=v_df.index, y=m.tail(150), line=dict(color='#3498db'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=v_df.index, y=s.tail(150), line=dict(color='orange', dash='dot'), name='Signal'), row=2, col=1)
    h_colors = ['#26a69a' if val > 0 else '#ef5350' for val in h.tail(150)]
    fig.add_trace(go.Bar(x=v_df.index, y=h.tail(150), marker_color=h_colors, name='Hist'), row=2, col=1)

    fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, title=title)
    st.plotly_chart(fig, use_container_width=True)

# --- 4. EXECUTION ---
session_token = st.sidebar.text_input("Breeze Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=API_KEY)
        breeze.generate_session(api_secret=API_SECRET, session_token=session_token)
        
        # Calculate Expiry
        expiry = (datetime.today() + timedelta(days=((1 - datetime.today().weekday()) % 7) + 6)).strftime("%Y-%m-%dT07:00:00.000Z")

        def get_full_sync(right):
            # 1. Get Chain & Strike (100-interval, target 60)
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry, right=right)
            df_opt = pd.DataFrame(chain["Success"])
            df_opt = df_opt[pd.to_numeric(df_opt['strike_price']) % 100 == 0]
            df_opt['diff'] = (pd.to_numeric(df_opt['ltp']) - 60).abs()
            strike = str(int(df_opt.sort_values('diff').iloc[0]['strike_price']))

            # 2. Get Real-Time Price for status box
            live = breeze.get_quotes(stock_code="NIFTY", exchange_code="NFO", expiry_date=expiry, product_type="options", right=right, strike_price=strike)
            live_price = live['Success'][0]['ltp']

            # 3. Get History (Fetched 10 days to ensure 150 candles of 15-min bars exist)
            hist = breeze.get_historical_data(interval="5minute", from_date=(datetime.now()-timedelta(days=12)).strftime("%Y-%m-%dT09:15:00.000Z"), 
                                              to_date=datetime.now().strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", 
                                              product_type="options", expiry_date=expiry, right=right, strike_price=strike)
            df = process_data(pd.DataFrame(hist["Success"]))
            
            # Indicators
            stl, std, stat = calculate_supertrend(df)
            m, sl, h = calculate_macd(df)
            return strike, live_price, df, stl, std, m, sl, h, stat

        with st.spinner("Updating 150-Candle Charts..."):
            c_s, c_ltp, c_df, c_stl, c_std, c_m, c_sl, c_h, c_stat = get_full_sync("call")
            p_s, p_ltp, p_df, p_stl, p_std, p_m, p_sl, p_h, p_stat = get_full_sync("put")

        st.title("🏛 NIFTY 15m Options Terminal")
        st.info(f"📅 Expiry: {expiry[:10]} | 🔄 Next Refresh: 5 Minutes | 🎯 Window: 150 Candles")

        col1, col2 = st.columns(2)
        show_indicator(col1, f"CALL {c_s}", c_stat, c_ltp)
        show_indicator(col2, f"PUT {p_s}", p_stat, p_ltp)

        draw_combined_chart(c_df, c_stl, c_std, c_m, c_sl, c_h, "CALL CHART (150 Candles)")
        draw_combined_chart(p_df, p_stl, p_std, p_m, p_sl, p_h, "PUT CHART (150 Candles)")

    except Exception as e: st.error(f"Sync Error: {e}")
