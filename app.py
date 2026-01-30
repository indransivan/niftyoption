import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime, timedelta
import calendar
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & AUTO-REFRESH ---
st.set_page_config(page_title="NIFTY Non-Repaint Terminal", layout="wide")
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

# --- 3. NON-REPAINT LOGIC ---
def calculate_macd_and_signal(df):
    if df.empty or len(df) < 200: return None, None, None, "WAIT", []
    
    df_limited = df.tail(200).copy().reset_index(drop=True)
    close = pd.to_numeric(df_limited['close']).dropna()
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    # NON-REPAINT LOGIC: Check the last CLOSED candle (index -2) against its predecessor (-3)
    # This ensures the signal doesn't disappear if the current price fluctuates
    prev_macd = macd_line.iloc[-3]
    curr_macd = macd_line.iloc[-2] # Confirmed closed candle
    
    if prev_macd <= 0 and curr_macd > 0: status = "BUY"
    elif prev_macd >= 0 and curr_macd < 0: status = "SELL"
    else: status = "HOLD BUY" if curr_macd > 0 else "HOLD SELL"
    
    # Identify all crossover points for arrows
    arrows = []
    for i in range(1, len(macd_line)):
        if macd_line.iloc[i-1] <= 0 and macd_line.iloc[i] > 0:
            arrows.append((i, macd_line.iloc[i], 'green', '^')) # Buy Arrow
        elif macd_line.iloc[i-1] >= 0 and macd_line.iloc[i] < 0:
            arrows.append((i, macd_line.iloc[i], 'red', 'v')) # Sell Arrow
            
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
session_token = st.sidebar.text_input("Session Token", type="password")

if st.sidebar.button("Test Alert & Sound"):
    play_sound()
    send_telegram("<b>🔔 Test Alert</b>: Signals are now Non-Repainting.")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"idx": None, "ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key="3194b6xL482162_16NkJ368y350336i&")
        breeze.generate_session(api_secret="(7@1q7426%p614#fk015~J9%4_$3v6Wh", session_token=session_token)
        
        # Expiry Calculation
        today = datetime.today()
        year, month = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
        last_day = calendar.monthrange(year, month)[1]
        expiry = datetime(year, month, last_day)
        while expiry.weekday() != 1: expiry -= timedelta(days=1)
        expiry_iso = expiry.strftime("%Y-%m-%dT07:00:00.000Z")

        with st.spinner("Calculating Non-Repaint Signals..."):
            # Data Fetching
            to_d = datetime.now()
            from_d = to_d - timedelta(days=15)
            idx_raw = breeze.get_historical_data(interval="5minute", from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"), to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"), stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            
            # Strike Search
            chain = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date=expiry_iso, right="call")
            df_opt = pd.DataFrame(chain["Success"])
            df_opt['strike_price'] = pd.to_numeric(df_opt['strike_price'])
            df_opt = df_opt[df_opt['strike_price'] % 100 == 0]
            df_opt['diff'] = abs(pd.to_numeric(df_opt['ltp']) - 60)
            best_ce = df_opt.sort_values('diff').iloc[0]
            c_s, c_ltp = str(int(best_ce['strike_price'])), best_ce['ltp']

            # Process & MACD
            df_idx = process_data(pd.DataFrame(idx_raw["Success"]))
            m_idx, s_idx, h_idx, stat_idx, arrows_idx = calculate_macd_and_signal(df_idx)

            # --- Dashboard UI ---
            st.title("🏛 NIFTY Non-Repaint Terminal")
            col1, col2, col3 = st.columns(3)
            show_indicator(col1, "NIFTY INDEX", "SPOT", df_idx['close'].iloc[-1], stat_idx)
            
            # Alert & Sound Trigger
            if stat_idx in ["BUY", "SELL"] and stat_idx != st.session_state.last_signals["idx"]:
                send_telegram(f"🏛 <b>NIFTY {stat_idx}</b> (Confirmed Closed Candle)")
                play_sound()
                st.session_state.last_signals["idx"] = stat_idx

            # Chart with Arrows
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(14, 6), facecolor='#0e1117')
            idx_range = range(len(m_idx))
            ax.plot(idx_range, m_idx, color='#3498db', label='MACD', linewidth=2)
            ax.plot(idx_range, s_idx, color='orange', linestyle='--', alpha=0.5)
            ax.bar(idx_range, h_idx, color=['#00ff88' if x > 0 else '#ff4444' for x in h_idx], alpha=0.2)
            
            # Plot arrows at crossover points
            for x, y, color, marker in arrows_idx:
                ax.scatter(x, y, color=color, marker=marker, s=150, zorder=5)

            ax.set_facecolor('#161a25')
            ax.set_title("NIFTY Index MACD (Arrows = Confirmed Crossovers)")
            st.pyplot(fig)

    except Exception as e: st.error(f"Error: {e}")
