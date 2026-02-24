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
st.set_page_config(page_title="NIFTY 100-Interval Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_st_macd")

TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"
API_KEY = "3194b6xL482162_16NkJ368y350336i&"
API_SECRET = "(7@1q7426%p614#fk015~J9%4_$3v6Wh"

# --- 2. INDICATOR LOGIC ---
def calculate_supertrend(df, period=10, multiplier=3):
    df = df.copy()
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2 = (high + low) / 2
    upperband = (hl2 + (multiplier * atr)).to_numpy()
    lowerband = (hl2 - (multiplier * atr)).to_numpy()
    close_np = close.to_numpy()
    
    supertrend = [0.0] * len(df)
    direction = [1] * len(df)

    for i in range(1, len(df)):
        if close_np[i] > upperband[i-1]:
            direction[i] = 1
        elif close_np[i] < lowerband[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and lowerband[i] < lowerband[i-1]:
                lowerband[i] = lowerband[i-1]
            if direction[i] == -1 and upperband[i] > upperband[i-1]:
                upperband[i] = upperband[i-1]
        supertrend[i] = lowerband[i] if direction[i] == 1 else upperband[i]

    status = "HOLD BUY" if direction[-1] == 1 else "HOLD SELL"
    if len(direction) > 1:
        if direction[-1] == 1 and direction[-2] == -1: status = "BUY"
        if direction[-1] == -1 and direction[-2] == 1: status = "SELL"
    
    signals = []
    for i in range(1, len(direction)):
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
    if df_raw.empty:
        return pd.DataFrame()
    df = df_raw.copy()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    # Filter only trading hours 09:15-15:30 IST
    df = df[
        ((df['datetime'].dt.hour > 9) | 
         ((df['datetime'].dt.hour == 9) & (df['datetime'].dt.minute >= 15))) &
        ((df['datetime'].dt.hour < 15) | 
         ((df['datetime'].dt.hour == 15) & (df['datetime'].dt.minute <= 30)))
    ]
    
    df = df.set_index('datetime').resample('15min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    
    # Keep last 100 actual 15-min trading candles
    df = df.tail(100)
    
    return df.reset_index(drop=True)  # drop=True removes datetime column

# --- 3. UI COMPONENTS ---
def show_indicator(col, title, status, ltp):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""
        <div style="background-color:{bg}; padding:20px; border-radius:12px; text-align:center; border: 1px solid #444;">
            <p style="margin:0; color: white; font-size: 1rem; opacity: 0.8;">{title}</p>
            <h1 style="margin:10px 0; color: white; font-size: 2.5rem; letter-spacing: 2px;">{status}</h1>
            <p style="margin:0; color: white; font-size: 1.2rem;">LTP: ₹{ltp:.2f}</p>
        </div>
        """, unsafe_allow_html=True)

def draw_combined_chart(df, st_line, st_dir, m, s, h, signals, title):
    if df.empty or st_line is None:
        return

    # Use index 0-99 as x-axis (1-100 candles)
    x_vals = list(range(len(df)))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    fig.add_trace(
        go.Candlestick(
            x=x_vals,
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='Price'
        ),
        row=1, col=1
    )
    
    for i in range(1, len(st_line)):
        color = "#00ff88" if st_dir.iloc[i] == 1 else "#ff4444"
        fig.add_trace(
            go.Scatter(
                x=[i-1, i],
                y=[st_line.iloc[i-1], st_line.iloc[i]],
                mode='lines',
                line=dict(color=color, width=2.5),
                showlegend=False
            ),
            row=1, col=1
        )

    fig.add_trace(
        go.Scatter(x=x_vals, y=m, line=dict(color='#3498db'), name='MACD'),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(x=x_vals, y=s, line=dict(color='orange', dash='dot'), name='Signal'),
        row=2, col=1
    )
    h_colors = ['#26a69a' if val > 0 else '#ef5350' for val in h]
    fig.add_trace(
        go.Bar(x=x_vals, y=h, marker_color=h_colors, name='Hist'),
        row=2, col=1
    )

    fig.update_layout(
        height=600, 
        template="plotly_dark",
        xaxis_rangeslider_visible=False, 
        title=title,
        xaxis_title="Candle (1-100)"
    )
    st.plotly_chart(fig, use_container_width=True)

# --- 4. MAIN ---
session_token = st.sidebar.text_input("Breeze Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=API_KEY)
        breeze.generate_session(api_secret=API_SECRET, session_token=session_token)
        
        expiry = datetime.today() + timedelta(days=((1 - datetime.today().weekday()) % 7) + 6)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        def get_strike_at_60(right):
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=right)
            df_opt = pd.DataFrame(chain["Success"])
            df_opt['ltp'] = pd.to_numeric(df_opt['ltp'])
            df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
            df_opt = df_opt[df_opt['strike_price'] % 100 == 0]
            best = df_opt.iloc[(df_opt['ltp'] - 60).abs().argsort()[:1]]
            return str(int(float(best['strike_price'].values[0])))

        c_s = get_strike_at_60("call")
        p_s = get_strike_at_60("put")

        def fetch_data(s, r):
            res = breeze.get_historical_data(
                interval="5minute", 
                from_date=(datetime.now()-timedelta(days=15)).strftime("%Y-%m-%dT09:15:00.000Z"), 
                to_date=datetime.now().strftime("%Y-%m-%dT15:30:00.000Z"), 
                stock_code="NIFTY", 
                exchange_code="NFO", 
                product_type="options", 
                expiry_date=expiry_iso, 
                right=r, 
                strike_price=s
            )
            df = process_data(pd.DataFrame(res["Success"]))
            st_l, st_d, stat, sigs = calculate_supertrend(df)
            m, sl, h = calculate_macd(df)
            return df, st_l, st_d, m, sl, h, stat, sigs

        df_ce, stl_ce, std_ce, m_ce, sl_ce, h_ce, stat_ce, sig_ce = fetch_data(c_s, "call")
        df_pe, stl_pe, std_pe, m_pe, sl_pe, h_pe, stat_pe, sig_pe = fetch_data(p_s, "put")

        st.title("🏛 NIFTY 100-Step Options Terminal")
        cols = st.columns(2)
        show_indicator(cols[0], f"CALL {c_s}", stat_ce, df_ce['close'].iloc[-1])
        show_indicator(cols[1], f"PUT {p_s}", stat_pe, df_pe['close'].iloc[-1])

        draw_combined_chart(df_ce, stl_ce, std_ce, m_ce, sl_ce, h_ce, sig_ce, "NIFTY CALL (Candles 1-100)")
        draw_combined_chart(df_pe, stl_pe, std_pe, m_pe, sl_pe, h_pe, sig_pe, "NIFTY PUT (Candles 1-100)")

    except Exception as e: 
        st.error(f"Error: {e}")
