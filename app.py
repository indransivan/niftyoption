import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime, timedelta
import calendar
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & AUTO-REFRESH ---
st.set_page_config(page_title="NIFTY Non-Repaint Pro", layout="wide")
st_autorefresh(interval=300000, key="refresh_200")

# --- 2. CONFIGURATION ---
TELE_TOKEN = "8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU"
TELE_CHAT_ID = "7970248513"

def play_sound():
    sound_url = "https://www.soundjay.com/buttons/beep-07a.mp3"
    st.components.v1.html(f'<audio autoplay><source src="{sound_url}"></audio>', height=0, width=0)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=payload)
    except: pass

# --- 3. CORE LOGIC (NON-REPAINT) ---
def calculate_macd_and_signal(df):
    if df.empty or len(df) < 200: return None, None, None, "WAIT", []
    
    df_limited = df.tail(200).copy().reset_index(drop=True)
    close = pd.to_numeric(df_limited['close']).dropna()
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    # NON-REPAINT LOGIC:
    # We check iloc[-2] (last closed candle) vs iloc[-3] (previous closed candle)
    # This ensures that once a signal is generated, it stays on the chart.
    prev_m = macd_line.iloc[-3]
    curr_m = macd_line.iloc[-2] 
    
    if prev_m <= 0 and curr_m > 0: status = "BUY"
    elif prev_m >= 0 and curr_m < 0: status = "SELL"
    else: status = "HOLD BUY" if curr_m > 0 else "HOLD SELL"
    
    # Find all crossovers for Arrow Plotting
    arrows = []
    for i in range(1, len(macd_line) - 1): # Stop at -1 to avoid repainting live candle
        if macd_line.iloc[i-1] <= 0 and macd_line.iloc[i] > 0:
            arrows.append({'idx': i, 'val': macd_line.iloc[i], 'type': 'BUY'})
        elif macd_line.iloc[i-1] >= 0 and macd_line.iloc[i] < 0:
            arrows.append({'idx': i, 'val': macd_line.iloc[i], 'type': 'SELL'})
            
    return macd_line, signal_line, hist, status, arrows

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').resample('15min').agg({'close':'last'}).dropna()
    return df.reset_index(drop=True)

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

# --- 4. MAIN APP ---
st.sidebar.header("🔐 Breeze Login")
api_key = st.sidebar.text_input("API Key", value="3194b6xL482162_16NkJ368y350336i&")
api_secret = st.sidebar.text_input("API Secret", type="password", value="(7@1q7426%p614#fk015~J9%4_$3v6Wh")
session_token = st.sidebar.text_input("Session Token", type="password")

if st.sidebar.button("Test Alert & Sound"):
    play_sound()
    send_telegram("<b>🔔 Test Alert</b>: Non-repaint logic is active with Arrows!")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"idx": None, "ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        
        # Expiry logic
        today = datetime.today()
        year, month = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
        last_day = calendar.monthrange(year, month)[1]
        expiry = datetime(year, month, last_day)
        while expiry.weekday() != 1: expiry -= timedelta(days=1)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        to_d = datetime.now()
        from_d = to_d - timedelta(days=14)

        with st.spinner("Scanning Market..."):
            idx_res = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            
            # Find Strike Logic
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right="call")
            df_opt = pd.DataFrame(chain["Success"])
            df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
            df_opt = df_opt[df_opt['strike_price'] % 100 == 0]
            df_opt['diff'] = abs(pd.to_numeric(df_opt['ltp']) - 60)
            best_ce = df_opt.sort_values('diff').iloc[0]
            c_s, c_ltp = str(int(best_ce['strike_price'])), best_ce['ltp']

            # Option Data Fetching
            def fetch_opt(s, r):
                res = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"]))

            df_idx = process_data(pd.DataFrame(idx_res["Success"]))
            df_ce = fetch_opt(c_s, "call")

            # Calculate Signals
            m_idx, s_idx, h_idx, stat_idx, arr_idx = calculate_macd_and_signal(df_idx)
            m_ce, s_ce, h_ce, stat_ce, arr_ce = calculate_macd_and_signal(df_ce)

            # --- ALERT TRIGGER ---
            if stat_idx in ["BUY", "SELL"] and stat_idx != st.session_state.last_signals["idx"]:
                send_telegram(f"🏛 <b>INDEX {stat_idx}</b> confirmed at {datetime.now().strftime('%H:%M')}")
                play_sound()
                st.session_state.last_signals["idx"] = stat_idx

            # --- UI ---
            st.title("🏛 NIFTY Non-Repaint Terminal")
            c1, c2 = st.columns(2)
            show_indicator(c1, "NIFTY INDEX", "SPOT", df_idx['close'].iloc[-1], stat_idx)
            show_indicator(c2, "CALL OPTION", f"{c_s} CE", c_ltp, stat_ce)

            # --- PLOTTING WITH ARROWS ---
            plt.style.use('dark_background')
            fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(14, 10), facecolor='#0e1117', sharex=True)

            def plot_with_arrows(ax, m, s, h, arrows, title):
                if m is not None:
                    x = range(len(m))
                    ax.plot(x, m, color='#3498db', label='MACD', linewidth=2)
                    ax.plot(x, s, color='orange', linestyle='--', alpha=0.5)
                    ax.bar(x, h, color=['#00ff88' if val > 0 else '#ff4444' for val in h], alpha=0.2)
                    
                    # Add Arrows
                    for a in arrows:
                        color = 'green' if a['type'] == 'BUY' else 'red'
                        marker = '^' if a['type'] == 'BUY' else 'v'
                        ax.scatter(a['idx'], a['val'], color=color, marker=marker, s=100, zorder=5)
                    
                    ax.set_title(title, loc='left')
                    ax.axhline(0, color='white', linewidth=0.5, alpha=0.5)
                    ax.set_facecolor('#161a25')

            plot_with_arrows(ax0, m_idx, s_idx, h_idx, arr_idx, "NIFTY INDEX MACD")
            plot_with_arrows(ax1, m_ce, s_ce, h_ce, arr_ce, f"CALL {c_s} MACD")
            
            st.pyplot(fig)

    except Exception as e: st.error(f"Error: {e}")
