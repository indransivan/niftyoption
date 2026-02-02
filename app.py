import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime, timedelta
import calendar
from breeze_connect import BreezeConnect
from streamlit_autorefresh import st_autorefresh

# --- 1. SETTINGS & AUTO-REFRESH ---
st.set_page_config(page_title="NIFTY Next-Week Terminal", layout="wide")
st_autorefresh(interval=300000, key="refresh_next_week")

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

# --- 3. CORE LOGIC (300 CANDLE NON-REPAINT) ---
def calculate_macd_and_signal(df):
    if df.empty or len(df) < 300: return None, None, None, "WAIT", []
    
    df_limited = df.tail(300).copy().reset_index(drop=True)
    close = pd.to_numeric(df_limited['close']).dropna()
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    # NON-REPAINT: Checking last closed candle (-2)
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

# --- 4. "NEXT WEEK" TUESDAY EXPIRY LOGIC ---
def get_next_week_tuesday():
    today = datetime.today()
    # Find days until the very next Tuesday
    days_to_first_tue = (1 - today.weekday()) % 7
    if days_to_first_tue == 0 and today.hour >= 15: # If today is Tuesday post-market
        days_to_first_tue = 7
    
    # Add 7 days to the first Tuesday to get the "Next Week" Tuesday
    next_week_tue = today + timedelta(days=days_to_first_tue + 7)
    return next_week_tue.strftime("%Y-%m-%dT07:00:00.000Z")

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

        with st.spinner(f"Loading Next-Week Expiry: {expiry_iso[:10]}..."):
            to_d = datetime.now()
            from_d = to_d - timedelta(days=25) # Slightly more buffer for 300 15m candles
            
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

            # Calculations
            m_idx, s_idx, h_idx, stat_idx, arr_idx = calculate_macd_and_signal(df_idx)
            m_ce, s_ce, h_ce, stat_ce, arr_ce = calculate_macd_and_signal(df_ce)
            m_pe, s_pe, h_pe, stat_pe, arr_pe = calculate_macd_and_signal(df_pe)

            # --- ALERT TRIGGER ---
            t_now = datetime.now().strftime("%H:%M")
            alert_active = False
            for key, stat, label in [("idx", stat_idx, "INDEX"), ("ce", stat_ce, f"CALL {c_s}"), ("pe", stat_pe, f"PUT {p_s}")]:
                if stat in ["BUY", "SELL"] and stat != st.session_state.last_signals[key]:
                    send_telegram(f"⚡ <b>NEXT-WEEK ALERT</b>\n<b>{label}: {stat}</b>\nExpiry: {expiry_iso[:10]}\nTime: {t_now}")
                    st.session_state.last_signals[key] = stat
                    alert_active = True
            if alert_active: play_sound()

            # --- UI LAYOUT ---
            st.title("🚦 NIFTY Next-Week Strategy")
            st.warning(f"Active Expiry: {expiry_iso[:10]} (Following Tuesday) | Lookback: 300 Candles")
            
            c1, c2, c3 = st.columns(3)
            show_indicator(c1, "NIFTY INDEX", "SPOT", df_idx['close'].iloc[-1], stat_idx)
            show_indicator(c2, f"{c_s} CE", "NEXT WEEK", c_ltp, stat_ce)
            show_indicator(c3, f"{p_s} PE", "NEXT WEEK", p_ltp, stat_pe)

            plt.style.use('dark_background')
            fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(14, 18), facecolor='#0e1117', sharex=True)

            def plot_styled(ax, m, s, h, arrows, title):
                if m is not None:
                    idx_range = range(len(m))
                    ax.plot(idx_range, m, color='#3498db', linewidth=2, label='MACD')
                    ax.plot(idx_range, s, color='orange', linestyle='--', alpha=0.5)
                    ax.bar(idx_range, h, color=['#00ff88' if v > 0 else '#ff4444' for v in h], alpha=0.2)
                    for a in arrows:
                        ax.scatter(a['idx'], a['val'], color='green' if a['type'] == 'BUY' else 'red', 
                                   marker='^' if a['type'] == 'BUY' else 'v', s=120, zorder=10)
                    ax.set_title(title, loc='left', fontsize=12)
                    ax.axhline(0, color='white', linewidth=0.5, alpha=0.5)
                    ax.set_facecolor('#161a25')

            plot_styled(ax0, m_idx, s_idx, h_idx, arr_idx, "NIFTY INDEX MACD")
            plot_styled(ax1, m_ce, s_ce, h_ce, arr_ce, f"NEXT WEEK CALL {c_s} MACD")
            plot_styled(ax2, m_pe, s_pe, h_pe, arr_pe, f"NEXT WEEK PUT {p_s} MACD")
            
            st.pyplot(fig)

    except Exception as e: st.error(f"Error: {e}")
