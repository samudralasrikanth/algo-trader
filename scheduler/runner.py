# =============================================================================
# scheduler/runner.py — Main Event Loop
# =============================================================================
"""
Tick loop flow per symbol, per interval:

    1. Fetch real candle data (historical API)
    2. Compute VWAP, RSI, ATR, EMA from candle DataFrame
    3. Generate momentum signal
    4. Run AI decision gate (confidence + regime + cooldown)
    5a. If signal != HOLD and no open position → enter trade
    5b. If position is open → check exit (SL / target / time)
    6. Log everything to SQLite
    7. Print session summary
"""

import time
import logging
from datetime import datetime

import pandas as pd

from config.settings import (
    SYMBOLS, TIMEFRAME, LOOP_INTERVAL_SECONDS,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)
from data.kite_client import get_ltp, get_historical_candles
from strategy.indicators import build_dataframe, calculate_rsi, vwap, average_volume, atr, ema
from strategy.intraday_momentum import generate_signal, check_exit, compute_trade_levels
from risk.risk_manager import calculate_position_size, can_open_position
from execution.paper_executor import (
    execute_trade, close_position, get_open_position, open_positions, summary
)
from storage.db import log_trade, update_trade_exit, log_tick
from agent.decision_agent import filter_signal, estimate_confidence, record_trade_outcome

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Market hours guard
# ---------------------------------------------------------------------------

def _is_market_open() -> bool:
    now = datetime.now()
    open_time = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)
    close_time = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0)
    return open_time <= now <= close_time


# ---------------------------------------------------------------------------
# Per-symbol processing
# ---------------------------------------------------------------------------

def _process_symbol(symbol: str) -> None:
    try:
        # 1. Fetch candles (last 2 days covers session start to now)
        candles = get_historical_candles(symbol, interval=TIMEFRAME, lookback_days=2)
        if len(candles) < 20:
            logger.warning("%s — not enough candles (%d); skipping", symbol, len(candles))
            return

        df = build_dataframe(candles)

        # 2. Compute indicators on full history
        df["rsi"]        = calculate_rsi(df)
        df["vwap"]       = vwap(df)
        df["avg_vol"]    = average_volume(df)
        df["atr"]        = atr(df)
        df["ema_50"]     = ema(df, period=50)

        # 3. Latest bar values
        latest           = df.iloc[-1]
        price            = get_ltp(symbol)          # real-time LTP for execution
        rsi_val          = latest["rsi"]
        vwap_val         = latest["vwap"]
        vol_val          = int(latest["volume"])
        avg_vol_val      = latest["avg_vol"]
        atr_val          = latest["atr"]
        ema50_val        = latest["ema_50"]
        now_str          = datetime.now().isoformat()

        # Guard NaN (first few bars)
        if pd.isna(rsi_val) or pd.isna(vwap_val) or pd.isna(atr_val):
            logger.debug("%s — indicator NaN on latest bar; skipping", symbol)
            return

        # 4. Entry signal
        raw_signal = generate_signal(price, vwap_val, rsi_val, vol_val, avg_vol_val)

        vol_ratio       = vol_val / avg_vol_val if avg_vol_val else 1.0
        price_vs_vwap   = (price - vwap_val) / vwap_val if vwap_val else 0.0
        confidence      = estimate_confidence(rsi_val, vol_ratio, price_vs_vwap)
        signal          = filter_signal(raw_signal, symbol, confidence, price, ema50_val)

        logger.info(
            "%-10s  price=%.2f  vwap=%.2f  rsi=%.1f  vol=%d  raw=%s  signal=%s  conf=%.2f",
            symbol, price, vwap_val, rsi_val, vol_val, raw_signal, signal, confidence,
        )

        # Audit log
        log_tick(symbol, now_str, price, vwap_val, rsi_val, vol_val, signal)

        # 5a. Exit check for open positions
        pos = get_open_position(symbol)
        if pos:
            should_exit, reason = check_exit(pos, price)
            if should_exit:
                closed = close_position(symbol, price, reason)
                update_trade_exit(symbol, closed)
                record_trade_outcome(symbol, closed["pnl"])
            return  # don't enter a new position on same bar as exit

        # 5b. Entry
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
        logger.error("Error processing %s: %s", symbol, exc, exc_info=True)


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
    logger.info("algo-trader STARTED  |  symbols=%s", symbols)
    logger.info("=" * 60)

    while True:
        if not _is_market_open():
            logger.info("Market closed — waiting for next open...")
            time.sleep(60)
            continue

        tick_start = time.time()

        for symbol in symbols:
            _process_symbol(symbol)

        # Session summary every tick
        s = summary()
        logger.info(
            "── Session ── open=%d closed=%d wins=%d losses=%d pnl=₹%.2f win_rate=%.1f%%",
            s["open"], s["closed"], s["wins"], s["losses"], s["total_pnl"], s["win_rate"],
        )

        elapsed = time.time() - tick_start
        sleep_for = max(0, LOOP_INTERVAL_SECONDS - elapsed)
        logger.debug("Tick done in %.1fs — sleeping %.1fs", elapsed, sleep_for)
        time.sleep(sleep_for)
