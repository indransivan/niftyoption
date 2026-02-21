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
st.set_page_config(page_title="NIFTY Supertrend Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_supertrend")

# --- 2. CONFIG ---
TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "HTML"})
    except: pass

# --- 3. INDICATOR LOGIC (SUPERTREND) ---
def calculate_supertrend(df, period=5, multiplier=2):
    """Calculates Non-Repainting Supertrend."""
    high = df['high']
    low = df['low']
    close = df['close']
    
    # ATR Calculation
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2 = (high + low) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    
    # Initialize Supertrend arrays
    supertrend = [0.0] * len(df)
    direction = [1] * len(df) # 1 for Up, -1 for Down

    for i in range(1, len(df)):
        if close.iloc[i] > upperband.iloc[i-1]:
            direction[i] = 1
        elif close.iloc[i] < lowerband.iloc[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and lowerband.iloc[i] < lowerband.iloc[i-1]:
                lowerband.iloc[i] = lowerband.iloc[i-1]
            if direction[i] == -1 and upperband.iloc[i] > upperband.iloc[i-1]:
                upperband.iloc[i] = upperband.iloc[i-1]

        supertrend[i] = lowerband.iloc[i] if direction[i] == 1 else upperband.iloc[i]

    # Non-Repaint Signal Logic: Look at the last CLOSED candle
    # prev_dir = direction at -3, curr_dir = direction at -2
    prev_dir = direction[-3]
    curr_dir = direction[-2]
    
    if prev_dir == -1 and curr_dir == 1: status = "BUY"
    elif prev_dir == 1 and curr_dir == -1: status = "SELL"
    else: status = "HOLD BUY" if curr_dir == 1 else "HOLD SELL"

    # Map signals for plotting
    signals = []
    for i in range(period, len(direction)):
        if direction[i] == 1 and direction[i-1] == -1:
            signals.append({'idx': i, 'type': 'BUY'})
        elif direction[i] == -1 and direction[i-1] == 1:
            signals.append({'idx': i, 'type': 'SELL'})

    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index), status, signals

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
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').resample('15min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    return df.reset_index()

# --- 4. CHARTING ---
def draw_combined_chart(df, st_line, st_dir, m, s, h, signals, title):
    if df.empty or st_line is None: return

    # Focus on last 200 candles
    view_df = df.tail(200).reset_index(drop=True)
    view_st = st_line.tail(200).reset_index(drop=True)
    view_dir = st_dir.tail(200).reset_index(drop=True)
    view_m = m.tail(200).reset_index(drop=True)
    view_s = s.tail(200).reset_index(drop=True)
    view_h = h.tail(200).reset_index(drop=True)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                        subplot_titles=(f"{title} Price & Supertrend", "MACD"))

    # Candlestick
    fig.add_trace(go.Candlestick(x=view_df.index, open=view_df['open'], high=view_df['high'], 
                                 low=view_df['low'], close=view_df['close'], name='Price'), row=1, col=1)

    # Supertrend Line (Dynamic Color)
    st_colors = ['#00ff88' if d == 1 else '#ff4444' for d in view_dir]
    fig.add_trace(go.Scatter(x=view_df.index, y=view_st, mode='lines', 
                             line=dict(color='rgba(255,255,255,0.2)', width=1), name='ST Line'), row=1, col=1)

    # Buy/Sell Markers
    start_idx = len(df) - 200
    for sig in signals:
        if sig['idx'] >= start_idx:
            local_idx = sig['idx'] - start_idx
            color = "#00ff88" if sig['type'] == 'BUY' else "#ff4444"
            symbol = "triangle-up" if sig['type'] == 'BUY' else "triangle-down"
            y_pos = float(view_df['low'].iloc[local_idx]) * 0.99 if sig['type'] == 'BUY' else float(view_df['high'].iloc[local_idx]) * 1.01
            
            fig.add_trace(go.Scatter(x=[local_idx], y=[y_pos], mode="markers",
                                     marker=dict(color=color, size=15, symbol=symbol), showlegend=False), row=1, col=1)

    # MACD
    fig.add_trace(go.Scatter(x=view_df.index, y=view_m, line=dict(color='#3498db'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Bar(x=view_df.index, y=view_h, marker_color=['#00ff88' if v > 0 else '#ff4444' for v in view_h]), row=2, col=1)

    fig.update_layout(height=650, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

def show_indicator(col, title, status, ltp):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""<div style="background-color:{bg}; padding:15px; border-radius:10px; text-align:center;">
        <h5 style="margin:0; color:#ccc;">{title}</h5><h1 style="margin:10px 0;">{status}</h1><p>LTP: ₹{ltp}</p></div>""", unsafe_allow_html=True)

# --- 5. MAIN ---
st.sidebar.header("🔐 Login")
session_token = st.sidebar.text_input("Session Token", type="password")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key="3194b6xL482162_16NkJ368y350336i&")
        breeze.generate_session(api_secret="(7@1q7426%p614#fk015~J9%4_$3v6Wh", session_token=session_token)
        
        # Date Logic
        today = datetime.today()
        expiry = today + timedelta(days=((1 - today.weekday()) % 7) + 6)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        to_d = datetime.now()
        from_d = to_d - timedelta(days=35) # Extra buffer for ATR calculation

        def fetch_and_process(s, r):
            res = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=r, strike_price=s)
            return process_data(pd.DataFrame(res["Success"]))

        # Get ATM Strike (Approx)
        idx_raw = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NSE", product_type="cash")
        spot = float(idx_raw["Success"][-1]["close"])
        atm_strike = str(int(round(spot / 50) * 50))

        df_ce = fetch_and_process(atm_strike, "call")
        df_pe = fetch_and_process(atm_strike, "put")

        # Supertrend
        st_ce, dir_ce, stat_ce, sig_ce = calculate_supertrend(df_ce)
        st_pe, dir_pe, stat_pe, sig_pe = calculate_supertrend(df_pe)
        
        # MACD (Visuals only)
        m_ce, s_ce, h_ce = calculate_macd(df_ce)
        m_pe, s_pe, h_pe = calculate_macd(df_pe)

        # Telegram
        for key, stat, label in [("ce", stat_ce, f"CE {atm_strike}"), ("pe", stat_pe, f"PE {atm_strike}")]:
            if stat in ["BUY", "SELL"] and stat != st.session_state.last_signals[key]:
                send_telegram(f"⚡ <b>ST SIGNAL: {label} -> {stat}</b>")
                st.session_state.last_signals[key] = stat

        st.title("🏹 NIFTY Supertrend Terminal (ATR=5, F=2)")
        cols = st.columns(2)
        show_indicator(cols[0], f"CALL {atm_strike}", stat_ce, df_ce['close'].iloc[-1])
        show_indicator(cols[1], f"PUT {atm_strike}", stat_pe, df_pe['close'].iloc[-1])

        st.divider()
        draw_combined_chart(df_ce, st_ce, dir_ce, m_ce, s_ce, h_ce, sig_ce, "CALL")
        draw_combined_chart(df_pe, st_pe, dir_pe, m_pe, s_pe, h_pe, sig_pe, "PUT")

    except Exception as e: st.error(f"Error: {e}")
