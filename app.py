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
st.set_page_config(page_title="NIFTY ST + MACD Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_st_macd")

# --- 2. CONFIG ---
TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "HTML"})
    except: pass

# --- 3. INDICATOR LOGIC ---
def calculate_supertrend(df, period=10, multiplier=3):
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2 = (high + low) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    
    supertrend = [0.0] * len(df)
    direction = [1] * len(df)

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

    prev_dir, curr_dir = direction[-3], direction[-2]
    status = "BUY" if (prev_dir == -1 and curr_dir == 1) else "SELL" if (prev_dir == 1 and curr_dir == -1) else ("HOLD BUY" if curr_dir == 1 else "HOLD SELL")
    
    signals = []
    for i in range(period, len(direction)):
        if direction[i] == 1 and direction[i-1] == -1: signals.append({'idx': i, 'type': 'BUY'})
        elif direction[i] == -1 and direction[i-1] == 1: signals.append({'idx': i, 'type': 'SELL'})

    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index), status, signals

def calculate_macd(df):
    close = df['close']
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    return df.reset_index()

# --- 4. CHARTING ---
def draw_combined_chart(df, st_line, st_dir, m, s, h, signals, title):
    if df.empty or st_line is None: return

    v_df = df.tail(200).reset_index(drop=True)
    v_st = st_line.tail(200).reset_index(drop=True)
    v_dir = st_dir.tail(200).reset_index(drop=True)
    v_m = m.tail(200).reset_index(drop=True)
    v_s = s.tail(200).reset_index(drop=True)
    v_h = h.tail(200).reset_index(drop=True)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, row_heights=[0.7, 0.3],
                        subplot_titles=(f"{title} - Price & Supertrend", "MACD Indicator"))

    # Candlestick
    fig.add_trace(go.Candlestick(x=v_df.index, open=v_df['open'], high=v_df['high'], low=v_df['low'], close=v_df['close'], name='Price'), row=1, col=1)

    # Visible Supertrend Line Segments
    for i in range(1, len(v_st)):
        color = "#00ff88" if v_dir[i] == 1 else "#ff4444"
        fig.add_trace(go.Scatter(x=[i-1, i], y=[v_st[i-1], v_st[i]], mode='lines', 
                                 line=dict(color=color, width=3), showlegend=False, hoverinfo='skip'), row=1, col=1)

    # Buy/Sell Markers (Supertrend Based)
    start_idx = len(df) - 200
    for sig in signals:
        if sig['idx'] >= start_idx:
            loc = sig['idx'] - start_idx
            color, sym = ("#00ff88", "triangle-up") if sig['type'] == 'BUY' else ("#ff4444", "triangle-down")
            y_pos = float(v_df['low'].iloc[loc]) * 0.98 if sig['type'] == 'BUY' else float(v_df['high'].iloc[loc]) * 1.02
            fig.add_trace(go.Scatter(x=[loc], y=[y_pos], mode="markers", marker=dict(color=color, size=16, symbol=sym), name=sig['type']), row=1, col=1)

    # MACD Pane
    fig.add_trace(go.Scatter(x=v_df.index, y=v_m, line=dict(color='#3498db', width=2), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=v_df.index, y=v_s, line=dict(color='orange', width=1, dash='dot'), name='Signal'), row=2, col=1)
    h_colors = ['#26a69a' if val > 0 else '#ef5350' for val in v_h]
    fig.add_trace(go.Bar(x=v_df.index, y=v_h, marker_color=h_colors, name='Hist'), row=2, col=1)

    fig.update_layout(height=800, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

def show_indicator(col, title, status, ltp):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""<div style="background-color:{bg}; padding:15px; border-radius:10px; text-align:center; border: 1px solid #555;">
        <h5 style="margin:0; color:#ccc;">{title}</h5><h1 style="margin:10px 0; font-size: 2.2rem;">{status}</h1><p>LTP: ₹{ltp}</p></div>""", unsafe_allow_html=True)

# --- 5. MAIN ---
st.sidebar.header("🔐 Breeze Login")
session_token = st.sidebar.text_input("Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key="3194b6xL482162_16NkJ368y350336i&")
        breeze.generate_session(api_secret="(7@1q7426%p614#fk015~J9%4_$3v6Wh", session_token=session_token)
        
        today = datetime.today()
        expiry = today + timedelta(days=((1 - today.weekday()) % 7) + 6)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        with st.spinner("Analyzing Option Chains (Target: ₹60)..."):
            def get_strike_at_60(right):
                chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=right)
                df_opt = pd.DataFrame(chain["Success"])
                df_opt['ltp'] = pd.to_numeric(df_opt['ltp'])
                best = df_opt.iloc[(df_opt['ltp'] - 60).abs().argsort()[:1]]
                return str(int(float(best['strike_price'].values[0]))), float(best['ltp'].values[0])

            c_s, c_ltp = get_strike_at_60("call")
            p_s, p_ltp = get_strike_at_60("put")

            from_d_str = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%dT09:15:00.000Z")
            to_d_str = datetime.now().strftime("%Y-%m-%dT15:30:00.000Z")

            def get_full_data(s, r):
                res = breeze.get_historical_data(interval="5minute", from_date=from_d_str, to_date=to_d_str, stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=r, strike_price=s)
                df = process_data(pd.DataFrame(res["Success"]))
                st_l, st_d, stat, sigs = calculate_supertrend(df)
                m, s_l, h = calculate_macd(df)
                return df, st_l, st_d, m, s_l, h, stat, sigs

            df_ce, stl_ce, std_ce, m_ce, sl_ce, h_ce, stat_ce, sig_ce = get_full_data(c_s, "call")
            df_pe, stl_pe, std_pe, m_pe, sl_pe, h_pe, stat_pe, sig_pe = get_full_data(p_s, "put")

            st.title("🏛 NIFTY Options Terminal (ST + MACD)")
            st.info(f"Expiry: {expiry_iso[:10]} | Strike Target: ₹60 | ST(5,2) + MACD(12,26,9)")

            cols = st.columns(2)
            show_indicator(cols[0], f"CALL {c_s}", stat_ce, df_ce['close'].iloc[-1])
            show_indicator(cols[1], f"PUT {p_s}", stat_pe, df_pe['close'].iloc[-1])

            draw_combined_chart(df_ce, stl_ce, std_ce, m_ce, sl_ce, h_ce, sig_ce, "CALL OPTION")
            draw_combined_chart(df_pe, stl_pe, std_pe, m_pe, sl_pe, h_pe, sig_pe, "PUT OPTION")

    except Exception as e: st.error(f"Error: {e}")
