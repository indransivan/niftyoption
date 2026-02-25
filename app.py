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
# Auto-refresh every 1 minute to catch the latest data, even though chart is 15min
st_autorefresh(interval=300000, key="refresh_st_macd") 

TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"
API_KEY = "3194b6xL482162_16NkJ368y350336i&"
API_SECRET = "(7@1q7426%p614#fk015~J9%4_$3v6Wh"

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        payload = {"chat_id": TELE_CHAT_ID, "text": message}
        requests.post(url, json=payload)
    except Exception as e:
        st.error(f"Telegram Error: {e}")

# --- 2. INDICATOR LOGIC ---
def calculate_macd(df):
    close = df['close']
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# MACD-based, non-repainting buy/sell signal generator
# Buy when MACD crosses from below 0 to above 0, Sell when MACD crosses from above 0 to below 0
def calculate_macd_signals(macd_series):
    directions = []
    signals = []

    prev = macd_series.iloc[0]
    directions.append(1 if prev > 0 else -1 if prev < 0 else 0)

    for i in range(1, len(macd_series)):
        cur = macd_series.iloc[i]
        cur_dir = 1 if cur > 0 else -1 if cur < 0 else 0
        directions.append(cur_dir)

        # Zero-line cross (closed candle) => non-repainting
        if cur_dir == 1 and directions[i-1] <= 0:
            signals.append({'idx': i, 'type': 'BUY'})
        elif cur_dir == -1 and directions[i-1] >= 0:
            signals.append({'idx': i, 'type': 'SELL'})

    last_dir = directions[-1]
    if last_dir > 0:
        status = "HOLD BUY"
    elif last_dir < 0:
        status = "HOLD SELL"
    else:
        status = "NEUTRAL"

    if len(directions) > 1:
        if directions[-1] == 1 and directions[-2] <= 0:
            status = "BUY"
        elif directions[-1] == -1 and directions[-2] >= 0:
            status = "SELL"

    return pd.Series(directions, index=macd_series.index), status, signals

def process_data(df_raw):
    if df_raw.empty:
        return pd.DataFrame()
    df = df_raw.copy()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    df = df[
        ((df['datetime'].dt.hour > 9) | 
         ((df['datetime'].dt.hour == 9) & (df['datetime'].dt.minute >= 15))) &
        ((df['datetime'].dt.hour < 15) | 
         ((df['datetime'].dt.hour == 15) & (df['datetime'].dt.minute <= 30)))
    ]
    
    # --- AGGREGATING 1m DATA BACK TO 15m FOR CHARTING ---
    df = df.set_index('datetime').resample('15min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    
    df = df.tail(100)
    
    return df.reset_index(drop=True)

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

def draw_combined_chart(df, macd_line, signal_line, hist, macd_signals, title):
    if df.empty or macd_line is None:
        return

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
    
    # MACD, Signal, Histogram
    fig.add_trace(
        go.Scatter(x=x_vals, y=macd_line, line=dict(color='#3498db'), name='MACD'),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(x=x_vals, y=signal_line, line=dict(color='orange', dash='dot'), name='Signal'),
        row=2, col=1
    )
    h_colors = ['#26a69a' if val > 0 else '#ef5350' for val in hist]
    fig.add_trace(
        go.Bar(x=x_vals, y=hist, marker_color=h_colors, name='Hist'),
        row=2, col=1
    )

    # Mark buy/sell points on MACD sub-plot
    buy_x = [s['idx'] for s in macd_signals if s['type'] == 'BUY']
    buy_y = [macd_line.iloc[s['idx']] for s in macd_signals if s['type'] == 'BUY']
    sell_x = [s['idx'] for s in macd_signals if s['type'] == 'SELL']
    sell_y = [macd_line.iloc[s['idx']] for s in macd_signals if s['type'] == 'SELL']

    if buy_x:
        fig.add_trace(
            go.Scatter(
                x=buy_x,
                y=buy_y,
                mode='markers',
                marker=dict(color='#00ff88', size=10, symbol='triangle-up'),
                name='BUY'
            ),
            row=2, col=1
        )

    if sell_x:
        fig.add_trace(
            go.Scatter(
                x=sell_x,
                y=sell_y,
                mode='markers',
                marker=dict(color='#ff4444', size=10, symbol='triangle-down'),
                name='SELL'
            ),
            row=2, col=1
        )

    fig.update_layout(
        height=600, 
        template="plotly_dark",
        xaxis_rangeslider_visible=False, 
        title=title,
        xaxis_title="Candle (1-100 x 15min)"
    )
    st.plotly_chart(fig, use_container_width=True)

# --- 4. MAIN ---
session_token = st.sidebar.text_input("Breeze Session Token", type="password")

if session_token:
    try:
        breeze = BreezeConnect(api_key=API_KEY)
        breeze.generate_session(api_secret=API_SECRET, session_token=session_token)
        
        expiry = datetime.today() + timedelta(days=((1 - datetime.today().weekday()) % 7) + 7)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")
        expiry_readable = expiry.strftime("%d-%b-%Y")

        def get_strike_at_60(right):
            chain = breeze.get_option_chain_quotes(
                stock_code="NIFTY",
                exchange_code="NFO",
                product_type="options",
                expiry_date=expiry_iso,
                right=right
            )
            df_opt = pd.DataFrame(chain["Success"])
            df_opt['ltp'] = pd.to_numeric(df_opt['ltp'])
            df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
            df_opt = df_opt[df_opt['strike_price'] % 100 == 0]
            best = df_opt.iloc[(df_opt['ltp'] - 60).abs().argsort()[:1]]
            return str(int(float(best['strike_price'].values[0])))

        c_s = get_strike_at_60("call")
        p_s = get_strike_at_60("put")

        def fetch_data(s, r):
            # Fetching 1-minute data
            res = breeze.get_historical_data(
                interval="1minute", 
                from_date=(datetime.now()-timedelta(days=10)).strftime("%Y-%m-%dT09:15:00.000Z"), 
                to_date=datetime.now().strftime("%Y-%m-%dT15:30:00.000Z"), 
                stock_code="NIFTY", 
                exchange_code="NFO", 
                product_type="options", 
                expiry_date=expiry_iso, 
                right=r, 
                strike_price=s
            )
            # process_data converts the 1m rows into 15m candles
            df = process_data(pd.DataFrame(res["Success"]))
            macd_line, signal_line, hist = calculate_macd(df)
            directions, stat, sigs = calculate_macd_signals(macd_line)
            
            if stat in ["BUY", "SELL"]:
                msg = f"🚀 {stat} SIGNAL: NIFTY {s} {r.upper()}\\nLTP: ₹{df['close'].iloc[-1]}"
                send_telegram(msg)
                
            return df, macd_line, signal_line, hist, stat, sigs

        df_ce, m_ce, sl_ce, h_ce, stat_ce, sig_ce = fetch_data(c_s, "call")
        df_pe, m_pe, sl_pe, h_pe, stat_pe, sig_pe = fetch_data(p_s, "put")

        st.title("🏛 NIFTY 100-Step Options Terminal")
        st.markdown(f"### 🗓 Target Expiry: **{expiry_readable}** | 📊 View: **15 Minute Candles**")
        st.divider()

        cols = st.columns(2)
        show_indicator(cols[0], f"CALL {c_s}", stat_ce, df_ce['close'].iloc[-1])
        show_indicator(cols[1], f"PUT {p_s}", stat_pe, df_pe['close'].iloc[-1])

        draw_combined_chart(df_ce, m_ce, sl_ce, h_ce, sig_ce, "NIFTY CALL (15m Candles)")
        draw_combined_chart(df_pe, m_pe, sl_pe, h_pe, sig_pe, "NIFTY PUT (15m Candles)")

    except Exception as e: 
        st.error(f"Error: {e}")
