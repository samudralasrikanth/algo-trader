# =============================================================================
# strategy/indicators.py — Technical Indicator Library
# =============================================================================

import pandas as pd
import numpy as np


def build_dataframe(candles: list[dict]) -> pd.DataFrame:
    """
    Convert Kite historical_data response into a clean OHLCV DataFrame.
    Expects each candle dict to have keys: date, open, high, low, close, volume.
    """
    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df["volume"] = df["volume"].astype(int)
    return df


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's RSI using exponential weighted mean (more accurate than SMA).
    Returns a Series aligned to df.index.
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.rename("rsi")


# ---------------------------------------------------------------------------
# VWAP (intraday, resets per session)
# ---------------------------------------------------------------------------

def vwap(df: pd.DataFrame) -> pd.Series:
    """
    Cumulative VWAP anchored to the start of each calendar date.
    Uses typical price = (high + low + close) / 3.
    """
    df = df.copy()
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["typical_price"] * df["volume"]
    df["date_only"] = df.index.normalize()  # group by calendar day

    df["cum_tp_vol"] = df.groupby("date_only")["tp_vol"].cumsum()
    df["cum_vol"] = df.groupby("date_only")["volume"].cumsum()

    vwap_series = (df["cum_tp_vol"] / df["cum_vol"]).rename("vwap")
    return vwap_series


# ---------------------------------------------------------------------------
# Average Volume (rolling)
# ---------------------------------------------------------------------------

def average_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Rolling average volume over `period` bars."""
    return df["volume"].rolling(period).mean().rename("avg_volume")


# ---------------------------------------------------------------------------
# EMA (bonus — useful for trend filter)
# ---------------------------------------------------------------------------

def ema(df: pd.DataFrame, period: int = 20, col: str = "close") -> pd.Series:
    return df[col].ewm(span=period, adjust=False).mean().rename(f"ema_{period}")


# ---------------------------------------------------------------------------
# ATR (Average True Range) — used for dynamic stop-loss sizing
# ---------------------------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Standard ATR using Wilder smoothing.
    Returns ATR values aligned to df.index.
    """
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(com=period - 1, min_periods=period).mean().rename("atr")
