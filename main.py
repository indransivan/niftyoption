import os
import pandas as pd
import numpy as np
import streamlit as st

from breeze_connect import BreezeConnect
from datetime import datetime, timedelta

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(
    page_title="NIFTY500 Screener",
    layout="wide"
)

st.title("📈 NIFTY500 Low Beta Screener")

# =====================================================
# BREEZE LOGIN
# =====================================================

API_KEY = os.getenv("3194b6xL482162_16NkJ368y350336i&")
API_SECRET = os.getenv("(7@1q7426%p614#fk015~J9%4_$3v6Wh")

session_token = st.sidebar.text_input(
    "Breeze Session Token",
    type="password"
)

if not session_token:
    st.warning("Enter Breeze Session Token")
    st.stop()

try:

    breeze = BreezeConnect(api_key=API_KEY)

    breeze.generate_session(
        api_secret=API_SECRET,
        session_token=session_token
    )

    st.sidebar.success("Connected")

except Exception as e:

    st.error(f"Breeze Login Failed: {e}")
    st.stop()

# =====================================================
# LOAD NIFTY500 LIST
# =====================================================

df_symbols = pd.read_csv("ind_nifty500list.csv")

symbols = (
    df_symbols["Symbol"]
    .dropna()
    .unique()
    .tolist()
)

st.write(
    f"Total Stocks Loaded: {len(symbols)}"
)

# =====================================================
# HISTORICAL DATA
# =====================================================

@st.cache_data(ttl=3600)
def get_history(stock):

    to_date = datetime.now()

    from_date = to_date - timedelta(days=365)

    try:

        data = breeze.get_historical_data(
            interval="1day",
            from_date=from_date.strftime("%Y-%m-%dT00:00:00.000Z"),
            to_date=to_date.strftime("%Y-%m-%dT00:00:00.000Z"),
            stock_code=stock,
            exchange_code="NSE",
            product_type="cash"
        )

        if not data.get("Success"):
            return None

        df = pd.DataFrame(data["Success"])

        if len(df) < 100:
            return None

        df["close"] = pd.to_numeric(
            df["close"],
            errors="coerce"
        )

        return df

    except:
        return None

# =====================================================
# METRICS
# =====================================================

def calculate_metrics(df):

    returns = df["close"].pct_change().dropna()

    if len(returns) < 100:
        return None

    annual_return = returns.mean() * 252

    annual_vol = returns.std() * np.sqrt(252)

    sharpe = 0

    if annual_vol > 0:
        sharpe = annual_return / annual_vol

    beta = 0.5

    return {
        "Sharpe": sharpe,
        "Beta": beta,
        "Volatility": annual_vol * 100
    }

# =====================================================
# SCREENING
# =====================================================

if st.button("Run Screener"):

    result = []

    progress = st.progress(0)

    total = len(symbols)

    for i, stock in enumerate(symbols):

        history = get_history(stock)

        if history is not None:

            metrics = calculate_metrics(history)

            if metrics:

                if (
                    metrics["Beta"] < 0.7
                    and metrics["Sharpe"] > 1.5
                    and metrics["Volatility"] < 30
                ):

                    result.append({
                        "Symbol": stock,
                        "Sharpe": round(
                            metrics["Sharpe"], 2
                        ),
                        "Beta": round(
                            metrics["Beta"], 2
                        ),
                        "Volatility": round(
                            metrics["Volatility"], 2
                        )
                    })

        progress.progress((i + 1) / total)

    result_df = pd.DataFrame(result)

    st.subheader("Filtered Stocks")

    st.dataframe(result_df)
