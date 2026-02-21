import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & AUTO-REFRESH ---
st.set_page_config(page_title="NIFTY Next-Week (200) Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_200_next")

# --- 2. CONFIGURATION ---
TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=payload)
    except: pass

# --- 3. CORE LOGIC ---
def calculate_macd_and_signal(df):
    if df.empty or len(df) < 200: return None, None, None, "WAIT", []
    
    df_limited = df.tail(200).copy().reset_index(drop=True)
    close = pd.to_numeric(df_limited['close']).dropna()
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    # NON-REPAINT: Checking last closed candle (-2) vs previous (-3)
    prev_m = macd_line.iloc[-3]
    curr_m = macd_line.iloc[-2] 
    
    if prev_m <= 0 and curr_m > 0: status = "BUY"
    elif prev_m >= 0 and curr_m < 0: status = "SELL"
    else: status = "HOLD BUY" if curr_m > 0 else "HOLD SELL"
    
    arrows = []
    for i in range(1, len(macd_line) - 1):
        if macd_line.iloc[i-1] <= 0 and macd_line.iloc[i] > 0:
            arrows.append({'idx': i, 'val': macd_line.iloc[i], 'type': 'BUY'})
        elif macd_line.iloc[i-1] >= 0 and macd_line.iloc[i] < 0:
            arrows.append({'idx': i, 'val': macd_line.iloc[i], 'type': 'SELL'})
            
    return macd_line, signal_line, hist, status, arrows

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    # Resample to 15-minute intervals keeping OHLC for candles
    df = df.set_index('datetime').resample('15min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    return df.reset_index()

def draw_combined_chart(df, m, s, h, arrows, title):
    """Renders a Candlestick chart on top and MACD on bottom."""
    if m is None:
        st.warning(f"Not enough data for {title}")
        return

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        row_heights=[0.7, 0.3],
                        subplot_titles=(f"{title} Price", "MACD Indicator"))

    # 1. Candlestick Chart
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['open'], high=df['high'],
        low=df['low'], close=df['close'], name='Price',
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ), row=1, col=1)

    # 2. Add Buy/Sell Markers to Price Chart
    for a in arrows:
        color = "#00ff88" if a['type'] == 'BUY' else "#ff4444"
        symbol = "triangle-up" if a['type'] == 'BUY' else "triangle-down"
        y_val = df['low'].iloc[a['idx']] * 0.998 if a['type'] == 'BUY' else df['high'].iloc[a['idx']] * 1.002
        
        fig.add_trace(go.Scatter(
            x=[a['idx']], y=[y_val], mode="markers",
            marker=dict(color=color, size=15, symbol=symbol),
            name=a['type'], showlegend=False
        ), row=1, col=1)

    # 3. MACD Components
    fig.add_trace(go.Scatter(x=df.index, y=m, line=dict(color='#3498db', width=2), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=s, line=dict(color='orange', width=1, dash='dot'), name='Signal'), row=2, col=1)
    
    hist_colors = ['#26a69a' if val > 0 else '#ef5350' for val in h]
    fig.add_trace(go.Bar(x=df.index, y=h, marker_color=hist_colors, name='Histogram'), row=2, col=1)

    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

def show_indicator(col, title, strike, ltp, status):
    bg_color = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""
        <div style="background-color:{bg_color}; padding:15px; border-radius:10px; text-align:center; border: 1px solid #444;">
            <h5 style="color:#ccc; margin:0;">{title}</h5>
            <h3 style="color:white; margin:5px 0;">{strike}</h3>
            <h1 style="color:white; margin:10px 0; font-size: 2.2rem; font-weight: bold;">{status}</h1>
            <p style="color:white; margin:0; opacity: 0.8;">LTP: ₹{ltp}</p>
        </div>
    """, unsafe_allow_html=True)

# --- 4. EXPIRY LOGIC ---
def get_next_week_tuesday():
    today = datetime.today()
    days_to_tue = (1 - today.weekday()) % 7
    if days_to_tue == 0 and today.hour >= 15:
        days_to_tue = 7
    expiry = today + timedelta(days=days_to_tue + 6)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

# --- 5. MAIN APP ---
st.sidebar.header("🔐 Breeze Login")
session_token = st.sidebar.text_input("Session Token", type="password")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"idx": None, "ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key="3194b6xL482162_16NkJ368y350336i&")
        breeze.generate_session(api_secret="(7@1q7426%p614#fk015~J9%4_$3v6Wh", session_token=session_token)
        
        expiry_iso = get_next_week_tuesday()

        with st.spinner(f"Analyzing Next-Week Expiry: {expiry_iso[:10]}..."):
            to_d = datetime.now()
            from_d = to_d - timedelta(days=20) 
            
            idx_raw = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            
            def get_best_strike(right):
                chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=right)
                df_opt = pd.DataFrame(chain["Success"])
                df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
                df_opt = df_opt[df_opt['strike_price'] % 100 == 0]
                df_opt['diff'] = abs(pd.to_numeric(df_opt['ltp']) - 50) 
                best = df_opt.sort_values('diff').iloc[0]
                return str(int(best['strike_price'])), float(best['ltp'])

            c_s, c_ltp = get_best_strike("call")
            p_s, p_ltp = get_best_strike("put")

            def fetch_opt(s, r):
                res = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"]))

            df_idx = process_data(pd.DataFrame(idx_raw["Success"]))
            df_ce = fetch_opt(c_s, "call")
            df_pe = fetch_opt(p_s, "put")

            m_idx, s_idx, h_idx, stat_idx, arr_idx = calculate_macd_and_signal(df_idx)
            m_ce, s_ce, h_ce, stat_ce, arr_ce = calculate_macd_and_signal(df_ce)
            m_pe, s_pe, h_pe, stat_pe, arr_pe = calculate_macd_and_signal(df_pe)

            # Alerts
            t_now = datetime.now().strftime("%H:%M")
            for key, stat, label in [("idx", stat_idx, "INDEX"), ("ce", stat_ce, f"CALL {c_s}"), ("pe", stat_pe, f"PUT {p_s}")]:
                if stat in ["BUY", "SELL"] and stat != st.session_state.last_signals[key]:
                    send_telegram(f"🔔 <b>{label}: {stat}</b>\n(Next Week Expiry: {expiry_iso[:10]})\nTime: {t_now}")
                    st.session_state.last_signals[key] = stat

            # UI Rendering
            st.title("🏛 NIFTY Next-Week (200 Candles)")
            st.info(f"Scanning Following Tuesday: {expiry_iso[:10]} | Window: 200 Bars (15m)")
            
            cols = st.columns(3)
            show_indicator(cols[0], "NIFTY INDEX", "SPOT", df_idx['close'].iloc[-1], stat_idx)
            show_indicator(cols[1], f"CALL {c_s}", "₹50 TARGET", c_ltp, stat_ce)
            show_indicator(cols[2], f"PUT {p_s}", "₹50 TARGET", p_ltp, stat_pe)

            st.divider()
            draw_combined_chart(df_idx, m_idx, s_idx, h_idx, arr_idx, "NIFTY SPOT")
            draw_combined_chart(df_ce, m_ce, s_ce, h_ce, arr_ce, f"CALL {c_s}")
            draw_combined_chart(df_pe, m_pe, s_pe, h_pe, arr_pe, f"PUT {p_s}")

    except Exception as e: st.error(f"Error: {e}")
