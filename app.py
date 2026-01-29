import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime, timedelta
import calendar
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & AUTO-REFRESH ---
st.set_page_config(page_title="NIFTY ₹60 Round-Strike (200 Sample)", layout="wide")
# Auto-refresh every 5 minutes
st_autorefresh(interval=300000, key="refresh_200")

# --- 2. TELEGRAM CONFIGURATION ---
TELE_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELE_CHAT_ID = "YOUR_CHAT_ID_HERE"

def send_telegram(msg):
    if "YOUR_BOT_TOKEN" in TELE_TOKEN: return 
    url = f"https://api.telegram.org/bot8213681556:AAFoRSCMGmvZz7KSvgeudwFUMv-xXg_mTzU/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        st.error(f"Telegram alert failed: {e}")

# --- 3. CORE LOGIC FUNCTIONS ---
def get_next_monthly_expiry():
    today = datetime.today()
    year, month = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
    last_day = calendar.monthrange(year, month)[1]
    expiry = datetime(year, month, last_day)
    while expiry.weekday() != 1: # 1 = Tuesday
        expiry -= timedelta(days=1)
    return expiry.strftime("%Y-%m-%dT07:00:00.000Z")

def calculate_macd_and_signal(df):
    # Standardizing to 200 samples
    if df.empty or len(df) < 200: return None, None, None, "WAIT"
    
    df_limited = df.tail(200)
    close = pd.to_numeric(df_limited['close']).dropna()
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    curr, prev = macd_line.iloc[-1], macd_line.iloc[-2]
    if prev <= 0 and curr > 0: status = "BUY"
    elif prev >= 0 and curr < 0: status = "SELL"
    else: status = "HOLD BUY" if curr > 0 else "HOLD SELL"
    
    return macd_line, signal_line, hist, status

def process_data(df_raw):
    if df_raw.empty: return pd.DataFrame()
    df = df_raw.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    # Resampling to 15min candles
    df = df.set_index('datetime').resample('15min').agg({'close':'last'}).dropna()
    df = df.reset_index(drop=True)
    return df

def show_indicator(col, title, strike, ltp, status):
    bg_color = "#006400" if "BUY" in status else "#8B0000" if "SELL" in status else "#262730"
    col.markdown(f"""
        <div style="background-color:{bg_color}; padding:15px; border-radius:10px; text-align:center; border: 1px solid #444;">
            <h5 style="color:#ccc; margin:0;">{title}</h5>
            <h3 style="color:white; margin:5px 0;">{strike}</h3>
            <h1 style="color:white; margin:10px 0; font-size: 2.5rem; font-weight: bold;">{status}</h1>
            <p style="color:white; margin:0; opacity: 0.8;">Value: ₹{ltp}</p>
        </div>
    """, unsafe_allow_html=True)

# --- 4. MAIN APP EXECUTION ---
st.sidebar.header("🔐 Breeze Login")
api_key = st.sidebar.text_input("API Key", value="3194b6xL482162_16NkJ368y350336i&")
api_secret = st.sidebar.text_input("API Secret", type="password", value="(7@1q7426%p614#fk015~J9%4_$3v6Wh")
session_token = st.sidebar.text_input("Session Token", type="password")

if 'last_signals' not in st.session_state:
    st.session_state.last_signals = {"idx": None, "ce": None, "pe": None}

if session_token:
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        expiry_iso = get_next_monthly_expiry()
        
        # Window for 200 samples (Approx 10-12 days)
        to_d = datetime.now()
        from_d = to_d - timedelta(days=12)

        with st.spinner("Scanning for ₹60 Round Strikes (200 Samples)..."):
            idx_res = breeze.get_historical_data(interval="5minute", 
                from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"),
                to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"),
                stock_code="NIFTY", exchange_code="NSE", product_type="cash")
            
            def find_round_strike(right):
                res = breeze.get_option_chain_quotes(stock_code="NIFTY", exchange_code="NFO", 
                                                     product_type="options", expiry_date=expiry_iso, right=right)
                if res.get("Success"):
                    df = pd.DataFrame(res["Success"])
                    df['strike_price'] = pd.to_numeric(df['strike_price'])
                    df['ltp'] = pd.to_numeric(df['ltp'])
                    
                    # Round 100 Filter
                    df = df[df['strike_price'] % 100 == 0]
                    
                    # Target ₹60 Filter
                    df['diff'] = abs(df['ltp'] - 60)
                    best = df.sort_values('diff').iloc[0]
                    return str(int(best['strike_price'])), best['ltp']
                return None, None

            c_s, c_ltp = find_round_strike("call")
            p_s, p_ltp = find_round_strike("put")

        if idx_res.get("Success") and c_s and p_s:
            def fetch_opt(s, r):
                res = breeze.get_historical_data(interval="5minute", 
                    from_date=from_d.strftime("%Y-%m-%dT09:15:00.000Z"),
                    to_date=to_d.strftime("%Y-%m-%dT15:30:00.000Z"),
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=expiry_iso, right=r, strike_price=s)
                return process_data(pd.DataFrame(res["Success"])) if res.get("Success") else pd.DataFrame()

            df_idx = process_data(pd.DataFrame(idx_res["Success"]))
            df_ce, df_pe = fetch_opt(c_s, "call"), fetch_opt(p_s, "put")

            # Calculate MACD Aligned to 200
            m_idx, s_idx, h_idx, stat_idx = calculate_macd_and_signal(df_idx)
            m_ce, s_ce, h_ce, stat_ce = calculate_macd_and_signal(df_ce)
            m_pe, s_pe, h_pe, stat_pe = calculate_macd_and_signal(df_pe)

            # --- ALERTS ---
            time_str = datetime.now().strftime("%H:%M")
            if stat_idx in ["BUY", "SELL"] and stat_idx != st.session_state.last_signals["idx"]:
                send_telegram(f"🏛 *INDEX*: {stat_idx} at {time_str}")
                st.session_state.last_signals["idx"] = stat_idx
            if stat_ce in ["BUY", "SELL"] and stat_ce != st.session_state.last_signals["ce"]:
                send_telegram(f"🚀 *CALL {c_s}*: {stat_ce} at ₹{c_ltp} ({time_str})")
                st.session_state.last_signals["ce"] = stat_ce
            if stat_pe in ["BUY", "SELL"] and stat_pe != st.session_state.last_signals["pe"]:
                send_telegram(f"📉 *PUT {p_s}*: {stat_pe} at ₹{p_ltp} ({time_str})")
                st.session_state.last_signals["pe"] = stat_pe

            # --- UI DASHBOARD ---
            st.title("🏛 NIFTY Round-Strike Strategy (200 Samples)")
            st.write(f"Live Update: {time_str} | Target: ₹60 Round Strike")
            
            row = st.columns(3)
            show_indicator(row[0], "NIFTY 50 INDEX", "SPOT", df_idx['close'].iloc[-1], stat_idx)
            show_indicator(row[1], "CALL OPTION", f"{c_s} CE", c_ltp, stat_ce)
            show_indicator(row[2], "PUT OPTION", f"{p_s} PE", p_ltp, stat_pe)

            # Aligned 200-Sample MACD Charts
            plt.style.use('dark_background')
            fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(14, 15), facecolor='#0e1117', sharex=True)
            
            def plot_macd_aligned(ax, m, s, h, title, color):
                if m is not None:
                    indices = range(len(m))
                    ax.axhline(0, color='white', linewidth=1, alpha=0.4)
                    ax.plot(indices, m, color=color, label='MACD', linewidth=2)
                    ax.plot(indices, s, color='orange', linestyle='--', alpha=0.5)
                    ax.bar(indices, h, color=['#00ff88' if x > 0 else '#ff4444' for x in h], alpha=0.3)
                    ax.set_title(f"{title} MACD", loc='left', fontsize=12)
                    ax.set_facecolor('#161a25')
                    ax.grid(alpha=0.1)

            plot_macd_aligned(ax0, m_idx, s_idx, h_idx, "NIFTY INDEX", "#3498db")
            plot_macd_aligned(ax1, m_ce, s_ce, h_ce, f"CALL {c_s}", "#00ff88")
            plot_macd_aligned(ax2, m_pe, s_pe, h_pe, f"PUT {p_s}", "#ff4444")
            
            plt.xlabel("Sample Count (Last 200 candles)")
            plt.tight_layout()
            st.pyplot(fig)
            
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Input Session Token to start the 200-sample scanner.")
