import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS ---
st.set_page_config(page_title="NIFTY Next-Week Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_terminal")

# --- 2. CONFIG ---
TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "HTML"})
    except: pass

# --- 3. LOGIC ---
def calculate_macd_and_signal(df):
    if df.empty or len(df) < 200: return None, None, None, "WAIT", []
    df_limited = df.tail(200).reset_index(drop=True)
    close = df_limited['close']
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    prev_m, curr_m = macd_line.iloc[-3], macd_line.iloc[-2]
    status = "BUY" if (prev_m <= 0 and curr_m > 0) else "SELL" if (prev_m >= 0 and curr_m < 0) else ("HOLD BUY" if curr_m > 0 else "HOLD SELL")
    
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
    # Convert all price columns to numeric immediately
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').resample('15min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    return df.reset_index()

def draw_combined_chart(df, m, s, h, arrows, title):
    if m is None or df.empty: return
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, 
                        row_heights=[0.7, 0.3], subplot_titles=(title, "MACD"))

    # Candlestick
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)

    # Markers (Fixed type error by ensuring float conversion)
    for a in arrows:
        color = "#00ff88" if a['type'] == 'BUY' else "#ff4444"
        symbol = "triangle-up" if a['type'] == 'BUY' else "triangle-down"
        
        # Ensure we get a single float value for the Y position
        ref_price = float(df['low'].iloc[a['idx']]) if a['type'] == 'BUY' else float(df['high'].iloc[a['idx']])
        y_pos = ref_price * 0.995 if a['type'] == 'BUY' else ref_price * 1.005
        
        fig.add_trace(go.Scatter(x=[a['idx']], y=[y_pos], mode="markers", 
                                 marker=dict(color=color, size=12, symbol=symbol), showlegend=False), row=1, col=1)

    # MACD
    fig.add_trace(go.Scatter(x=df.index, y=m, line=dict(color='#3498db', width=2), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=s, line=dict(color='orange', width=1, dash='dot'), name='Signal'), row=2, col=1)
    fig.add_trace(go.Bar(x=df.index, y=h, marker_color=['#26a69a' if v > 0 else '#ef5350' for v in h], name='Hist'), row=2, col=1)

    fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

def show_indicator(col, title, strike, ltp, status):
    bg = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""<div style="background-color:{bg}; padding:15px; border-radius:10px; text-align:center;">
        <h5 style="margin:0;">{title}</h5><h3>{strike}</h3><h1>{status}</h1><p>LTP: ₹{ltp}</p></div>""", unsafe_allow_html=True)

# --- 4. APP MAIN ---
st.sidebar.header("🔐 Breeze Login")
session_token = st.sidebar.text_input("Session Token", type="password")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"idx": None, "ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key="3194b6xL482162_16NkJ368y350336i&")
        breeze.generate_session(api_secret="(7@1q7426%p614#fk015~J9%4_$3v6Wh", session_token=session_token)
        
        # Expiry Calculation (Next Tuesday)
        today = datetime.today()
        expiry = today + timedelta(days=((1 - today.weekday()) % 7) + 6)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        with st.spinner("Fetching Data..."):
            to_d = datetime.now()
            from_d = to_d - timedelta(days=20)
            
            # Index Data
            idx_raw = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            df_idx = process_data(pd.DataFrame(idx_raw["Success"]))

            # Options Selection
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right="call")
            df_opt = pd.DataFrame(chain["Success"])
            df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
            c_s = str(int(df_opt.iloc[(pd.to_numeric(df_opt['ltp'])-50).abs().argsort()[:1]]['strike_price'].values[0]))
            
            # Simplified Fetch for CE/PE
            def get_opt_df(s, r):
                res = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"]))

            df_ce = get_opt_df(c_s, "call")
            df_pe = get_opt_df(c_s, "put") # Using same strike for ATM comparison

            # MACD
            m_idx, s_idx, h_idx, stat_idx, arr_idx = calculate_macd_and_signal(df_idx)
            m_ce, s_ce, h_ce, stat_ce, arr_ce = calculate_macd_and_signal(df_ce)
            m_pe, s_pe, h_pe, stat_pe, arr_pe = calculate_macd_and_signal(df_pe)

            # UI
            st.title("🏛 NIFTY Terminal")
            cols = st.columns(3)
            show_indicator(cols[0], "INDEX", "SPOT", df_idx['close'].iloc[-1], stat_idx)
            show_indicator(cols[1], f"CALL {c_s}", "ATM", df_ce['close'].iloc[-1], stat_ce)
            show_indicator(cols[2], f"PUT {c_s}", "ATM", df_pe['close'].iloc[-1], stat_pe)

            draw_combined_chart(df_idx, m_idx, s_idx, h_idx, arr_idx, "NIFTY SPOT")
            draw_combined_chart(df_ce, m_ce, s_ce, h_ce, arr_ce, "CALL OPTION")
            draw_combined_chart(df_pe, m_pe, s_pe, h_pe, arr_pe, "PUT OPTION")

    except Exception as e: st.error(f"Live Error: {e}")
