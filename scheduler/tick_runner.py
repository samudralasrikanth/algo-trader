# =============================================================================
# scheduler/tick_runner.py — Tick-Level Event Loop (WebSocket-driven)
# =============================================================================
"""
Architecture:
    - WebSocket runs in a daemon thread (data/websocket.py)
    - Main loop wakes every second to check for newly completed candles
    - On a new bar: run full pipeline (indicators → signal → agent → execute/exit)
    - Falls back to polling kite_client if WebSocket is not connected

Replaces scheduler/runner.py's polling approach with tick-level precision.
"""

import time
import logging
from datetime import datetime
from collections import defaultdict

import pandas as pd

from config.settings import (
    SYMBOLS, TIMEFRAME,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)
from data.provider import get_broker
from data.websocket import (
    start_ticker, stop_ticker,
    get_completed_candles, get_live_bar, candles_ready,
)
from strategy.indicators import build_dataframe, calculate_rsi, vwap, average_volume, atr, ema
from strategy.intraday_momentum import generate_signal, check_exit, compute_trade_levels
from risk.risk_manager import calculate_position_size, can_open_position
from execution.paper_executor import (
    execute_trade, close_position, get_open_position,
    open_positions, summary,
)
from storage.db import log_trade, update_trade_exit, log_tick
from agent.decision_agent import filter_signal, estimate_confidence, record_trade_outcome

logger = logging.getLogger(__name__)

# Track last processed bar timestamp per symbol to avoid reprocessing
_last_bar_ts: dict[str, datetime] = defaultdict(lambda: datetime.min)


# ---------------------------------------------------------------------------
# Market hours guard
# ---------------------------------------------------------------------------

def _is_market_open() -> bool:
    now = datetime.now()
    open_t  = now.replace(hour=MARKET_OPEN_HOUR,  minute=MARKET_OPEN_MINUTE,  second=0, microsecond=0)
    close_t = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return open_t <= now <= close_t


# ---------------------------------------------------------------------------
# Per-symbol pipeline (called on each new completed bar)
# ---------------------------------------------------------------------------

def _run_pipeline(symbol: str, df: pd.DataFrame) -> None:
    """Full signal → risk → execute pipeline for one symbol on one new bar."""
    try:
        if len(df) < 20:
            logger.debug("%s — not enough bars (%d); skipping", symbol, len(df))
            return

        # Compute indicators
        df["rsi"]    = calculate_rsi(df)
        df["vwap"]   = vwap(df)
        df["avg_vol"]= average_volume(df)
        df["atr"]    = atr(df)
        df["ema_50"] = ema(df, period=50)

        latest    = df.iloc[-1]
        price     = latest["close"]          # use bar close as execution price
        rsi_val   = latest["rsi"]
        vwap_val  = latest["vwap"]
        vol_val   = int(latest["volume"])
        avg_vol   = latest["avg_vol"]
        atr_val   = latest["atr"]
        ema50_val = latest["ema_50"]
        now_str   = datetime.now().isoformat()

        if pd.isna(rsi_val) or pd.isna(vwap_val) or pd.isna(atr_val):
            logger.debug("%s — NaN in indicators; skipping", symbol)
            return

        # Signal
        raw_signal   = generate_signal(price, vwap_val, rsi_val, vol_val, avg_vol)
        vol_ratio    = vol_val / avg_vol if avg_vol else 1.0
        pvwap        = (price - vwap_val) / vwap_val if vwap_val else 0.0
        confidence   = estimate_confidence(rsi_val, vol_ratio, pvwap)
        signal       = filter_signal(raw_signal, symbol, confidence, price, ema50_val)

        logger.info(
            "%-10s  close=%.2f  vwap=%.2f  rsi=%.1f  vol=%d  signal=%s  conf=%.2f",
            symbol, price, vwap_val, rsi_val, vol_val, signal, confidence,
        )
        log_tick(symbol, now_str, price, vwap_val, rsi_val, vol_val, signal)

        # Exit check for open positions FIRST
        pos = get_open_position(symbol)
        if pos:
            should_exit, reason = check_exit(pos, price)
            if should_exit:
                closed = close_position(symbol, price, reason)
                update_trade_exit(symbol, closed)
                record_trade_outcome(symbol, closed["pnl"])
            return  # no new entry on same bar as exit check

        # Entry
        if signal != "HOLD" and can_open_position(open_positions):
            levels = compute_trade_levels(signal, price, atr_val)
            qty    = calculate_position_size(levels["entry_price"], levels["stop_loss"])
            if qty > 0:
                trade = execute_trade(
                    symbol=symbol,
                    side=signal,
                    price=price,
                    qty=qty,
                    stop_loss=levels["stop_loss"],
                    target=levels["target"],
                )
                log_trade(trade)

    except Exception as exc:
        logger.error("Pipeline error for %s: %s", symbol, exc, exc_info=True)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(symbols: list[str] = SYMBOLS) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("=" * 60)
    logger.info("algo-trader TICK RUNNER  |  symbols=%s  tf=%s", symbols, TIMEFRAME)
    logger.info("=" * 60)

    broker = get_broker()
    # Start WebSocket via adapter
    broker.start_ticker(symbols)
    logger.info("Waiting for initial candle history to build...")

    try:
        while True:
            if not _is_market_open():
                logger.info("Market closed — sleeping 60s...")
                time.sleep(60)
                continue

            for symbol in symbols:
                if not candles_ready(symbol, min_bars=20):
                    logger.debug("%s — waiting for min candles...", symbol)
                    continue

                bars     = get_completed_candles(symbol)
                last_bar = bars[-1] if bars else None
                if last_bar is None:
                    continue

                bar_ts = last_bar["date"]
                if bar_ts <= _last_bar_ts[symbol]:
                    continue  # already processed this bar

                _last_bar_ts[symbol] = bar_ts

                df = build_dataframe(bars)
                _run_pipeline(symbol, df)

            # Print session summary every check cycle
            s = summary()
            logger.info(
                "── Session ── open=%d closed=%d wins=%d losses=%d pnl=₹%.2f win_rate=%.1f%%",
                s["open"], s["closed"], s["wins"], s["losses"],
                s["total_pnl"], s["win_rate"],
            )

            time.sleep(1)  # tight loop — only acts on new bars

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        stop_ticker()
        s = summary()
        logger.info(
            "Final: closed=%d  pnl=₹%.2f  win_rate=%.1f%%",
            s["closed"], s["total_pnl"], s["win_rate"],
        )
