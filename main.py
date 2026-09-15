import os
import json
import time
import asyncio
import logging
from pathlib import Path
from threading import Lock
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from breeze_connect import BreezeConnect


# ============================================================
# Configuration
# ============================================================

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
CSV_FILE = APP_DIR / os.getenv("STOCK_LIST_FILE", "ind_nifty500list.csv")
INDEX_FILE = APP_DIR / "index.html"
CACHE_FILE = APP_DIR / "screening_cache.json"

BETA_LIMIT = float(os.getenv("BETA_LIMIT", "0.7"))
SHARPE_LIMIT = float(os.getenv("SHARPE_LIMIT", "1.5"))
VOLATILITY_LIMIT = float(os.getenv("VOLATILITY_LIMIT", "30"))

# Annual risk-free rate. Example: 6% = 0.06
RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", "0.06"))

SCREENING_LOOKBACK_DAYS = int(
    os.getenv("SCREENING_LOOKBACK_DAYS", "550")
)

INTRADAY_LOOKBACK_DAYS = int(
    os.getenv("INTRADAY_LOOKBACK_DAYS", "30")
)

# Refresh charts every 5 minutes
CHART_REFRESH_SECONDS = int(
    os.getenv("CHART_REFRESH_SECONDS", "300")
)

# Screen the NIFTY 500 universe once every 24 hours by default
SCREENING_CACHE_HOURS = int(
    os.getenv("SCREENING_CACHE_HOURS", "24")
)

# Delay between API requests to remain below 100 calls/minute
API_REQUEST_DELAY_SECONDS = float(
    os.getenv("API_REQUEST_DELAY_SECONDS", "0.70")
)

# Avoid sending hundreds of charts to one browser.
# Set to 0 if you do not want a front-end limit.
MAX_DISPLAY_STOCKS = int(
    os.getenv("MAX_DISPLAY_STOCKS", "25")
)

# Breeze documents cash historical data with product_type="cash".
BENCHMARK_CODE = os.getenv("BENCHMARK_CODE", "NIFTY")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(title="NIFTY 500 Low-Risk MACD Dashboard")


# ============================================================
# Breeze initialisation
# ============================================================

BREEZE_API_KEY = os.getenv("3194b6xL482162_16NkJ368y350336i&")
BREEZE_API_SECRET = os.getenv("(7@1q7426%p614#fk015~J9%4_$3v6Wh")
BREEZE_SESSION = os.getenv("BREEZE_SESSION")

if not all([BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION]):
    raise RuntimeError(
        "Missing Breeze credentials. Set BREEZE_API_KEY, "
        "BREEZE_API_SECRET and BREEZE_SESSION."
    )

breeze = BreezeConnect(api_key=BREEZE_API_KEY)

breeze.generate_session(
    api_secret=BREEZE_API_SECRET,
    session_token=BREEZE_SESSION,
)

# Breeze calls are synchronous. Lock prevents simultaneous requests
# from multiple WebSocket clients using the same Breeze connection.
breeze_lock = Lock()


# ============================================================
# Shared application state
# ============================================================

state_lock = Lock()

dashboard_state: dict[str, Any] = {
    "status": "not_started",
    "screened_at": None,
    "total_symbols": 0,
    "processed_symbols": 0,
    "filtered_count": 0,
    "filtered_stocks": [],
    "failed_symbols": [],
    "error": None,
}

screening_task: asyncio.Task | None = None


# ============================================================
# General helpers
# ============================================================

def normalise_breeze_response(response: dict) -> list:
    """
    Return the Success list from a Breeze response.

    Breeze may return:
        {"Success": [...]}
        {"Success": None, "Error": "..."}
    """
    
    if not isinstance(response, dict):
        return []

    success = response.get("Success")

    if isinstance(success, list):
        return success

    return []


def parse_datetime_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect and parse the datetime/date column returned by Breeze.
    """

    possible_columns = [
        "datetime",
        "date",
        "timestamp",
        "time",
    ]

    datetime_column = next(
        (column for column in possible_columns if column in df.columns),
        None,
    )

    if datetime_column is None:
        raise ValueError("Historical response has no datetime column.")

    df[datetime_column] = pd.to_datetime(
        df[datetime_column],
        errors="coerce",
        utc=True,
    )

    df = df.dropna(subset=[datetime_column])
    df = df.sort_values(datetime_column)
    df = df.set_index(datetime_column)

    return df


def make_json_safe(value):
    """
    Convert NumPy and Pandas values into JSON-compatible values.
    """

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    return value


def load_symbol_mapping() -> dict[str, str]:
    """
    Optional mapping from NSE symbols to Breeze-specific stock codes.

    Example environment variable:

    BREEZE_STOCK_MAP_JSON={
        "M&M": "MAHMAH",
        "M&MFIN": "MAHFIN"
    }
    """

    mapping_text = os.getenv("BREEZE_STOCK_MAP_JSON", "{}")

    try:
        mapping = json.loads(mapping_text)

        if not isinstance(mapping, dict):
            return {}

        return {
            str(key).strip().upper(): str(value).strip()
            for key, value in mapping.items()
        }

    except json.JSONDecodeError:
        logger.warning("BREEZE_STOCK_MAP_JSON is not valid JSON.")
        return {}


BREEZE_SYMBOL_MAPPING = load_symbol_mapping()


def to_breeze_stock_code(nse_symbol: str) -> str:
    """
    Return an explicitly mapped Breeze stock code when available.
    Otherwise use the NSE symbol from the uploaded CSV.
    """

    cleaned_symbol = str(nse_symbol).strip().upper()
    return BREEZE_SYMBOL_MAPPING.get(cleaned_symbol, cleaned_symbol)


def load_stock_universe() -> pd.DataFrame:
    """
    Load symbols from ind_nifty500list.csv.
    """

    if not CSV_FILE.exists():
        raise FileNotFoundError(
            f"Stock list was not found: {CSV_FILE.name}"
        )

    df = pd.read_csv(CSV_FILE)

    required_columns = {
        "Company Name",
        "Industry",
        "Symbol",
        "Series",
    }

    missing_columns = required_columns.difference(df.columns)

    if missing_columns:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    df["Company Name"] = df["Company Name"].astype(str).str.strip()
    df["Industry"] = df["Industry"].astype(str).str.strip()
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    df["Series"] = df["Series"].astype(str).str.strip().str.upper()

    # Keep normal equity records only.
    df = df[df["Series"] == "EQ"].copy()

    # Remove empty symbols and duplicates.
    df = df[df["Symbol"].ne("")]
    df = df.drop_duplicates(subset=["Symbol"])

    return df.reset_index(drop=True)


# ============================================================
# Breeze historical-data functions
# ============================================================

def call_breeze_historical_data(
    stock_code: str,
    interval: str,
    from_date: datetime,
    to_date: datetime,
) -> pd.DataFrame:
    """
    Download cash-market historical data from Breeze.
    """

    from_iso = from_date.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    to_iso = to_date.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    with breeze_lock:
        response = breeze.get_historical_data(
            interval=interval,
            from_date=from_iso,
            to_date=to_iso,
            stock_code=stock_code,
            exchange_code="NSE",
            product_type="cash",
        )

    rows = normalise_breeze_response(response)

    if not rows:
        error_message = (
            response.get("Error")
            if isinstance(response, dict)
            else "Unknown Breeze response"
        )

        raise ValueError(
            f"No historical data for {stock_code}. "
            f"Breeze message: {error_message}"
        )

    df = pd.DataFrame(rows)
    df.columns = [str(column).strip().lower() for column in df.columns]

    df = parse_datetime_column(df)

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    if "close" not in df.columns:
        raise ValueError(
            f"Historical data for {stock_code} has no close column."
        )

    df = df.dropna(subset=["close"])
    df = df[~df.index.duplicated(keep="last")]

    return df


def get_daily_history(
    stock_code: str,
    lookback_days: int = SCREENING_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """
    Get daily history used for Beta, Sharpe and volatility.
    """

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=lookback_days)

    return call_breeze_historical_data(
        stock_code=stock_code,
        interval="1day",
        from_date=start_date,
        to_date=end_date,
    )


def get_thirty_minute_history(
    stock_code: str,
    lookback_days: int = INTRADAY_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """
    Get 30-minute candles.

    The primary request uses Breeze's 30minute interval.
    If it is unavailable for the current SDK/API response, the function
    requests 5-minute candles and resamples them to 30 minutes.
    """

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=lookback_days)

    try:
        return call_breeze_historical_data(
            stock_code=stock_code,
            interval="30minute",
            from_date=start_date,
            to_date=end_date,
        )

    except Exception as direct_error:
        logger.warning(
            "%s: direct 30-minute request failed. "
            "Trying 5-minute resampling. Error: %s",
            stock_code,
            direct_error,
        )

        five_minute_df = call_breeze_historical_data(
            stock_code=stock_code,
            interval="5minute",
            from_date=start_date,
            to_date=end_date,
        )

        aggregation = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }

        if "volume" in five_minute_df.columns:
            aggregation["volume"] = "sum"

        # origin="start_day" aligns candles to the trading day.
        thirty_minute_df = (
            five_minute_df
            .resample(
                "30min",
                origin="start_day",
                offset="15min",
            )
            .agg(aggregation)
        )

        return thirty_minute_df.dropna(subset=["close"])


# ============================================================
# Risk metric calculations
# ============================================================

def calculate_risk_metrics(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
) -> dict[str, float] | None:
    """
    Calculate:
      Beta = covariance(stock returns, benchmark returns)
             / variance(benchmark returns)

      Annualised Sharpe =
          mean(daily excess return) / std(daily return) * sqrt(252)

      Annualised volatility =
          std(daily return) * sqrt(252) * 100
    """

    stock_returns = (
        stock_df["close"]
        .pct_change(fill_method=None)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .rename("stock_return")
    )

    benchmark_returns = (
        benchmark_df["close"]
        .pct_change(fill_method=None)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .rename("benchmark_return")
    )

    aligned = pd.concat(
        [stock_returns, benchmark_returns],
        axis=1,
        join="inner",
    ).dropna()

    # Require enough common observations for a more meaningful result.
    if len(aligned) < 120:
        return None

    benchmark_variance = aligned["benchmark_return"].var(ddof=1)

    if benchmark_variance == 0 or pd.isna(benchmark_variance):
        return None

    beta = (
        aligned["stock_return"].cov(
            aligned["benchmark_return"]
        )
        / benchmark_variance
    )

    daily_std = aligned["stock_return"].std(ddof=1)

    if daily_std == 0 or pd.isna(daily_std):
        return None

    daily_risk_free_rate = (
        (1 + RISK_FREE_RATE) ** (1 / 252)
    ) - 1

    daily_excess_returns = (
        aligned["stock_return"] - daily_risk_free_rate
    )

    sharpe_ratio = (
        daily_excess_returns.mean()
        / daily_std
        * np.sqrt(252)
    )

    volatility_percent = daily_std * np.sqrt(252) * 100

    metrics = {
        "beta": float(beta),
        "sharpe": float(sharpe_ratio),
        "volatility": float(volatility_percent),
        "observations": int(len(aligned)),
    }

    if not all(
        np.isfinite([
            metrics["beta"],
            metrics["sharpe"],
            metrics["volatility"],
        ])
    ):
        return None

    return metrics


def passes_filter(metrics: dict[str, float]) -> bool:
    """
    Apply the requested screening criteria.
    """

    return (
        metrics["beta"] < BETA_LIMIT
        and metrics["sharpe"] > SHARPE_LIMIT
        and metrics["volatility"] < VOLATILITY_LIMIT
    )


# ============================================================
# MACD and signal
# ============================================================

def calculate_macd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add EMA12, EMA26, MACD, signal line and histogram.
    """

    output = df.copy()

    output["ema12"] = (
        output["close"]
        .ewm(span=12, adjust=False)
        .mean()
    )

    output["ema26"] = (
        output["close"]
        .ewm(span=26, adjust=False)
        .mean()
    )

    output["macd"] = output["ema12"] - output["ema26"]

    output["macd_signal_line"] = (
        output["macd"]
        .ewm(span=9, adjust=False)
        .mean()
    )

    output["macd_histogram"] = (
        output["macd"] - output["macd_signal_line"]
    )

    return output.dropna(
        subset=[
            "close",
            "macd",
            "macd_signal_line",
            "macd_histogram",
        ]
    )


def signal_from_macd(macd_value: float) -> str:
    """
    Requested rule:
      MACD > 0  -> BUY
      MACD < 0  -> SELL
      MACD == 0 -> HOLD
    """

    if macd_value > 0:
        return "BUY"

    if macd_value < 0:
        return "SELL"

    return "HOLD"


def build_chart_payload(
    stock: dict[str, Any],
) -> dict[str, Any]:
    """
    Download a filtered stock's 30-minute history and create
    browser-ready chart data.
    """

    breeze_code = stock["breeze_code"]

    intraday_df = get_thirty_minute_history(breeze_code)
    intraday_df = calculate_macd(intraday_df)

    if len(intraday_df) < 26:
        raise ValueError(
            f"Not enough 30-minute candles for {stock['symbol']}."
        )

    # Keep the latest 120 candles in the WebSocket payload.
    display_df = intraday_df.tail(120)

    latest_macd = float(display_df["macd"].iloc[-1])
    latest_close = float(display_df["close"].iloc[-1])

    return {
        "company_name": stock["company_name"],
        "industry": stock["industry"],
        "symbol": stock["symbol"],
        "breeze_code": breeze_code,
        "beta": round(stock["beta"], 4),
        "sharpe": round(stock["sharpe"], 4),
        "volatility": round(stock["volatility"], 2),
        "observations": stock["observations"],
        "latest_close": round(latest_close, 2),
        "latest_macd": round(latest_macd, 4),
        "signal": signal_from_macd(latest_macd),
        "chart": {
            "datetime": [
                timestamp.isoformat()
                for timestamp in display_df.index
            ],
            "close": [
                round(float(value), 2)
                for value in display_df["close"]
            ],
            "macd": [
                round(float(value), 4)
                for value in display_df["macd"]
            ],
            "macd_signal_line": [
                round(float(value), 4)
                for value in display_df["macd_signal_line"]
            ],
            "macd_histogram": [
                round(float(value), 4)
                for value in display_df["macd_histogram"]
            ],
        },
    }


# ============================================================
# Cache
# ============================================================

def load_valid_cache() -> bool:
    """
    Load cached screening results if they are still valid.
    """

    if not CACHE_FILE.exists():
        return False

    try:
        cache_age_seconds = (
            time.time() - CACHE_FILE.stat().st_mtime
        )

        max_age_seconds = SCREENING_CACHE_HOURS * 3600

        if cache_age_seconds > max_age_seconds:
            return False

        with CACHE_FILE.open("r", encoding="utf-8") as file:
            cached_data = json.load(file)

        with state_lock:
            dashboard_state.update(cached_data)
            dashboard_state["status"] = "complete"
            dashboard_state["error"] = None

        logger.info("Loaded screening results from cache.")
        return True

    except Exception:
        logger.exception("Could not load screening cache.")
        return False


def save_cache():
    """
    Save only the reusable screening state.
    """

    with state_lock:
        cache_data = {
            "status": "complete",
            "screened_at": dashboard_state["screened_at"],
            "total_symbols": dashboard_state["total_symbols"],
            "processed_symbols": dashboard_state["processed_symbols"],
            "filtered_count": dashboard_state["filtered_count"],
            "filtered_stocks": dashboard_state["filtered_stocks"],
            "failed_symbols": dashboard_state["failed_symbols"],
            "error": None,
        }

    with CACHE_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            cache_data,
            file,
            ensure_ascii=False,
            indent=2,
            default=make_json_safe,
        )


# ============================================================
# NIFTY 500 screening
# ============================================================

def run_screening_sync():
    """
    Screen the NIFTY 500 list using daily closing prices.
    """

    try:
        universe = load_stock_universe()

        with state_lock:
            dashboard_state.update({
                "status": "screening",
                "screened_at": None,
                "total_symbols": int(len(universe)),
                "processed_symbols": 0,
                "filtered_count": 0,
                "filtered_stocks": [],
                "failed_symbols": [],
                "error": None,
            })

        logger.info(
            "Downloading benchmark history for %s.",
            BENCHMARK_CODE,
        )

        benchmark_df = get_daily_history(BENCHMARK_CODE)
        time.sleep(API_REQUEST_DELAY_SECONDS)

        filtered_stocks = []
        failed_symbols = []

        for row_number, row in universe.iterrows():
            symbol = row["Symbol"]
            breeze_code = to_breeze_stock_code(symbol)

            try:
                stock_df = get_daily_history(breeze_code)

                metrics = calculate_risk_metrics(
                    stock_df=stock_df,
                    benchmark_df=benchmark_df,
                )

                if metrics is None:
                    raise ValueError(
                        "Insufficient aligned daily observations."
                    )

                if passes_filter(metrics):
                    filtered_stocks.append({
                        "company_name": row["Company Name"],
                        "industry": row["Industry"],
                        "symbol": symbol,
                        "breeze_code": breeze_code,
                        "beta": round(metrics["beta"], 4),
                        "sharpe": round(metrics["sharpe"], 4),
                        "volatility": round(
                            metrics["volatility"], 2
                        ),
                        "observations": metrics["observations"],
                    })

            except Exception as error:
                logger.warning(
                    "Screening failed for %s: %s",
                    symbol,
                    error,
                )

                failed_symbols.append({
                    "symbol": symbol,
                    "breeze_code": breeze_code,
                    "error": str(error),
                })

            finally:
                with state_lock:
                    dashboard_state["processed_symbols"] = (
                        row_number + 1
                    )

                time.sleep(API_REQUEST_DELAY_SECONDS)

        # Highest Sharpe first, then lowest volatility.
        filtered_stocks.sort(
            key=lambda item: (
                -item["sharpe"],
                item["volatility"],
                item["beta"],
            )
        )

        with state_lock:
            dashboard_state.update({
                "status": "complete",
                "screened_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "filtered_count": len(filtered_stocks),
                "filtered_stocks": filtered_stocks,
                "failed_symbols": failed_symbols,
                "error": None,
            })

        save_cache()

        logger.info(
            "Screening complete. %s stocks qualified.",
            len(filtered_stocks),
        )

    except Exception as error:
        logger.exception("Screening failed.")

        with state_lock:
            dashboard_state["status"] = "error"
            dashboard_state["error"] = str(error)


async def ensure_screening_started(force: bool = False):
    """
    Start screening without blocking the FastAPI event loop.
    """

    global screening_task

    if not force and load_valid_cache():
        return

    if screening_task and not screening_task.done():
        return

    screening_task = asyncio.create_task(
        asyncio.to_thread(run_screening_sync)
    )


# ============================================================
# FastAPI lifecycle and REST endpoints
# ============================================================

@app.on_event("startup")
async def startup_event():
    await ensure_screening_started(force=False)


@app.get("/")
async def index():
    if not INDEX_FILE.exists():
        return HTMLResponse(
            "<h1>index.html not found</h1>",
            status_code=500,
        )

    return HTMLResponse(
        INDEX_FILE.read_text(encoding="utf-8")
    )


@app.get("/health")
async def health():
    with state_lock:
        status = dashboard_state["status"]

    return {
        "status": "ok",
        "screening_status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status")
async def api_status():
    with state_lock:
        snapshot = dict(dashboard_state)

    return JSONResponse(snapshot)


@app.post("/api/rescreen")
async def rescreen():
    """
    Manually run the complete daily screening again.
    """

    await ensure_screening_started(force=True)

    return {
        "message": "Screening started.",
        "status": "screening",
    }


# ============================================================
# WebSocket dashboard
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            with state_lock:
                current_status = dashboard_state["status"]
                processed = dashboard_state["processed_symbols"]
                total = dashboard_state["total_symbols"]
                filtered_stocks = list(
                    dashboard_state["filtered_stocks"]
                )
                screening_error = dashboard_state["error"]
                screened_at = dashboard_state["screened_at"]

            if current_status != "complete":
                await websocket.send_json({
                    "type": "status",
                    "status": current_status,
                    "processed_symbols": processed,
                    "total_symbols": total,
                    "error": screening_error,
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat(),
                })

                await asyncio.sleep(5)
                continue

            selected_stocks = filtered_stocks

            if MAX_DISPLAY_STOCKS > 0:
                selected_stocks = filtered_stocks[
                    :MAX_DISPLAY_STOCKS
                ]

            stock_payloads = []
            chart_errors = []

            for stock in selected_stocks:
                try:
                    payload = await asyncio.to_thread(
                        build_chart_payload,
                        stock,
                    )

                    stock_payloads.append(payload)

                except Exception as error:
                    chart_errors.append({
                        "symbol": stock["symbol"],
                        "error": str(error),
                    })

                    logger.warning(
                        "Chart update failed for %s: %s",
                        stock["symbol"],
                        error,
                    )

                await asyncio.sleep(
                    API_REQUEST_DELAY_SECONDS
                )

            await websocket.send_json({
                "type": "dashboard",
                "screened_at": screened_at,
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "criteria": {
                    "beta_less_than": BETA_LIMIT,
                    "sharpe_greater_than": SHARPE_LIMIT,
                    "volatility_less_than_percent":
                        VOLATILITY_LIMIT,
                    "risk_free_rate_percent":
                        RISK_FREE_RATE * 100,
                },
                "total_filtered_stocks":
                    len(filtered_stocks),
                "displayed_stocks":
                    len(stock_payloads),
                "stocks": stock_payloads,
                "chart_errors": chart_errors,
            })

            await asyncio.sleep(CHART_REFRESH_SECONDS)

    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected.")

    except Exception as error:
        logger.exception("WebSocket error.")

        try:
            await websocket.send_json({
                "type": "error",
                "error": str(error),
            })
        except Exception:
            pass
