"""
Live ORB signal detection — 5-min data, tight SL (retest candle extremity).

State machine each day:
  1. Fetch 5-min bars for today
  2. After 10:20 ET: compute OR (first 50 min)
  3. Watch for close outside OR (breakout)
  4. Watch for retest (bar overlaps OR boundary)
  5. Return entry setup with tight SL
"""

import logging
from datetime import time, datetime
import pandas as pd
import yfinance as yf
import pytz

from orb_config import SYMBOL, OR_MINUTES, RR

log = logging.getLogger("strategy")
ET = pytz.timezone("America/New_York")

OR_END = time(10, 20)       # 9:30 + 50 min
CUTOFF = time(15, 0)        # no new entries after 3 PM ET


def fetch_today(symbol: str = SYMBOL) -> pd.DataFrame:
    """Fetch today's 5-min bars in ET timezone."""
    df = yf.download(symbol, period="1d", interval="5m",
                     auto_adjust=True, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def compute_or(df: pd.DataFrame) -> tuple[float, float] | None:
    """Returns (OR_High, OR_Low) from the first 50 min, or None if not enough data."""
    or_bars = df[(df.index.time >= time(9, 30)) & (df.index.time < OR_END)]
    if len(or_bars) < 5:
        return None
    return float(or_bars["High"].max()), float(or_bars["Low"].min())


def check_breakout(df: pd.DataFrame, or_high: float, or_low: float) -> str | None:
    """
    Returns 'long', 'short', or None.
    Uses bars after OR closes, looking for a bar that closes outside the range.
    """
    post_or = df[df.index.time >= OR_END]
    if post_or.empty:
        return None
    last = post_or.iloc[-1]
    if float(last["Close"]) > or_high:
        return "long"
    if float(last["Close"]) < or_low:
        return "short"
    return None


def check_retest(
    df: pd.DataFrame,
    direction: str,
    or_high: float,
    or_low: float,
) -> dict | None:
    """
    After breakout, check if latest bar retests the OR boundary.
    Returns entry setup dict with tight SL, or None.

    Tight SL = retest candle extremity:
      - Long retest: bar low <= or_high → SL = bar_low - 0.01
      - Short retest: bar high >= or_low → SL = bar_high + 0.01
    """
    post_or = df[df.index.time >= OR_END]
    if post_or.empty:
        return None

    last = post_or.iloc[-1]
    bar_time = last.name.time()

    if bar_time >= CUTOFF:
        return None

    bar_high = float(last["High"])
    bar_low  = float(last["Low"])

    if direction == "long" and bar_low <= or_high:
        entry   = or_high
        stop    = bar_low - 0.01
        sl_dist = entry - stop
        if sl_dist <= 0:
            return None
        return {
            "symbol":    SYMBOL,
            "direction": "long",
            "entry":     round(entry, 4),
            "stop":      round(stop, 4),
            "target":    round(entry + RR * sl_dist, 4),
            "sl_dist":   round(sl_dist, 4),
            "rr":        RR,
            "or_high":   or_high,
            "or_low":    or_low,
            "bar_time":  str(last.name),
        }

    if direction == "short" and bar_high >= or_low:
        entry   = or_low
        stop    = bar_high + 0.01
        sl_dist = stop - entry
        if sl_dist <= 0:
            return None
        return {
            "symbol":    SYMBOL,
            "direction": "short",
            "entry":     round(entry, 4),
            "stop":      round(stop, 4),
            "target":    round(entry - RR * sl_dist, 4),
            "sl_dist":   round(sl_dist, 4),
            "rr":        RR,
            "or_high":   or_high,
            "or_low":    or_low,
            "bar_time":  str(last.name),
        }

    return None


def get_latest_bar(df: pd.DataFrame) -> dict | None:
    if df.empty:
        return None
    last = df.iloc[-1]
    return {
        "high":  float(last["High"]),
        "low":   float(last["Low"]),
        "close": float(last["Close"]),
        "time":  str(last.name),
    }


def is_market_open() -> bool:
    now = datetime.now(ET)
    return (
        now.weekday() < 5
        and time(9, 30) <= now.time() <= time(16, 5)
    )


def et_now_time() -> time:
    return datetime.now(ET).time()
