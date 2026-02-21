import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & AUTO-REFRESH ---
st.set_page_config(page_title="NIFTY Next-Week Options Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_options_only")

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
    # Ensure we have enough data to calculate EMA and still show 200 bars
    if df.empty or len(df) < 26: return None, None, None, "WAIT", []
    
    close = df['close']
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    # Non-repaint logic (checking last confirmed closed candle)
    prev_m = macd_line.iloc[-3]
    curr_m = macd_line.iloc[-2] 
    
    if prev_m <= 0 and curr_m > 0: status = "BUY"
    elif prev_m >= 0 and curr_m < 0: status = "SELL"
    else: status = "HOLD BUY" if curr_m > 0 else "HOLD SELL"
    
    arrows = []
    for i in range(1, len(macd_line) - 1):
        if macd_line.iloc[i-1] <= 0 and macd_line.iloc[i] > 0:
            arrows.append({'idx': i, 'type': 'BUY'})
        elif macd_line.iloc[i-1] >= 0 and macd_line.iloc[i] < 0:
            arrows.append({'idx': i, 'type': 'SELL'})
            
    return macd_line, signal_line, hist, status, arrows

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

def draw_combined_chart(df, m, s, h, arrows, title):
    """Renders a 200-candle view for Price and MACD."""
    if df.empty or m is None: return

    # Slice the last 200 candles for the visualization
    view_df = df.tail(200).reset_index(drop=True)
    view_m = m.tail(200).reset_index(drop=True)
    view_s = s.tail(200).reset_index(drop=True)
    view_h = h.tail(200).reset_index(drop=True)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                        subplot_titles=(f"{title} (200 Candles)", "MACD"))

    # 1. Candlestick
    fig.add_trace(go.Candlestick(
        x=view_df.index, open=view_df['open'], high=view_df['high'],
        low=view_df['low'], close=view_df['close'], name='Price'
    ), row=1, col=1)

    # 2. Buy/Sell Arrows (relative to the 200-count window)
    # We find arrows that fall within the last 200 indices of the original dataframe
    start_idx = len(df) - 200
    for a in arrows:
        if a['idx'] >= start_idx:
            local_idx = a['idx'] - start_idx
            color = "#00ff88" if a['type'] == 'BUY' else "#ff4444"
            symbol = "triangle-up" if a['type'] == 'BUY' else "triangle-down"
            
            ref_price = float(view_df['low'].iloc[local_idx]) if a['type'] == 'BUY' else float(view_df['high'].iloc[local_idx])
            y_pos = ref_price * 0.995 if a['type'] == 'BUY' else ref_price * 1.005
            
            fig.add_trace(go.Scatter(
                x=[local_idx], y=[y_pos], mode="markers",
                marker=dict(color=color, size=14, symbol=symbol),
                showlegend=False
            ), row=1, col=1)

    # 3. MACD Components
    fig.add_trace(go.Scatter(x=view_df.index, y=view_m, line=dict(color='#3498db', width=2), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=view_df.index, y=view_s, line=dict(color='orange', width=1, dash='dot'), name='Signal'), row=2, col=1)
    
    h_colors = ['#26a69a' if v > 0 else '#ef5350' for v in view_h]
    fig.add_trace(go.Bar(x=view_df.index, y=view_h, marker_color=h_colors, name='Hist'), row=2, col=1)

    fig.update_layout(height=650, template="plotly_dark", xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

def show_indicator(col, title, strike, ltp, status):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""
        <div style="background-color:{bg}; padding:15px; border-radius:10px; text-align:center; border: 1px solid #444;">
            <h5 style="color:#ccc; margin:0;">{title}</h5>
            <h3 style="color:white; margin:5px 0;">{strike}</h3>
            <h1 style="color:white; margin:10px 0; font-size: 2rem; font-weight: bold;">{status}</h1>
            <p style="color:white; margin:0; opacity: 0.8;">LTP: ₹{ltp}</p>
        </div>
    """, unsafe_allow_html=True)

# --- 4. DATE LOGIC ---
def get_next_week_tuesday():
    today = datetime.today()
    days_to_tue = (1 - today.weekday()) % 7
    if days_to_tue == 0 and today.hour >= 15: days_to_tue = 7
    expiry = today + timedelta(days=days_to_tue + 6)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

# --- 5. MAIN APP ---
st.sidebar.header("🔐 Breeze Login")
session_token = st.sidebar.text_input("Session Token", type="password")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key="3194b6xL482162_16NkJ368y350336i&")
        breeze.generate_session(api_secret="(7@1q7426%p614#fk015~J9%4_$3v6Wh", session_token=session_token)
        
        expiry_iso = get_next_week_tuesday()

        with st.spinner("Analyzing Next-Week Contracts..."):
            to_d = datetime.now()
            # Requesting 30 days to ensure we have enough data to calculate EMA for the first of the 200 candles
            from_d = to_d - timedelta(days=30) 
            
            # Fetch Index just for Strike Selection
            idx_raw = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            curr_spot = float(idx_raw["Success"][-1]["close"])

            def get_strike(right):
                chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=right)
                df_opt = pd.DataFrame(chain["Success"])
                df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
                # Filter for ₹50 target price
                df_opt['diff'] = (pd.to_numeric(df_opt['ltp']) - 50).abs()
                best = df_opt.sort_values('diff').iloc[0]
                return str(int(best['strike_price'])), float(best['ltp'])

            c_s, c_ltp = get_strike("call")
            p_s, p_ltp = get_strike("put")

            def fetch_opt(s, r):
                res = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"]))

            df_ce = fetch_opt(c_s, "call")
            df_pe = fetch_opt(p_s, "put")

            m_ce, s_ce, h_ce, stat_ce, arr_ce = calculate_macd_and_signal(df_ce)
            m_pe, s_pe, h_pe, stat_pe, arr_pe = calculate_macd_and_signal(df_pe)

            # Alerts
            t_now = datetime.now().strftime("%H:%M")
            for key, stat, label in [("ce", stat_ce, f"CALL {c_s}"), ("pe", stat_pe, f"PUT {p_s}")]:
                if stat in ["BUY", "SELL"] and stat != st.session_state.last_signals[key]:
                    send_telegram(f"🔔 <b>{label}: {stat}</b>\nExpiry: {expiry_iso[:10]}\nTime: {t_now}")
                    st.session_state.last_signals[key] = stat

            # UI
            st.title("🏹 NIFTY Option Terminal")
            st.caption(f"Next-Week Expiry: {expiry_iso[:10]} | 15m Intervals")
            
            top_cols = st.columns(2)
            show_indicator(top_cols[0], f"CALL {c_s}", "Target ₹50", c_ltp, stat_ce)
            show_indicator(top_cols[1], f"PUT {p_s}", "Target ₹50", p_ltp, stat_pe)

            st.divider()
            
            # Chart Section
            draw_combined_chart(df_ce, m_ce, s_ce, h_ce, arr_ce, f"CALL {c_s}")
            st.markdown("<br>", unsafe_allow_html=True)
            draw_combined_chart(df_pe, m_pe, s_pe, h_pe, arr_pe, f"PUT {p_s}")

    except Exception as e: st.error(f"Error fetching data: {e}")
