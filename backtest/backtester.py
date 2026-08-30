# =============================================================================
# backtest/backtester.py — Historical Replay Engine
# =============================================================================
"""
Replays historical OHLCV candles bar-by-bar through the full live pipeline:
    indicators → momentum signal → agent gate → paper executor → DB

Produces a BacktestResult with:
    trades          — all closed trade dicts
    total_pnl       — net PnL after brokerage
    win_rate        — % of winning trades
    max_drawdown    — peak-to-trough equity drawdown
    sharpe_ratio    — annualised Sharpe (risk-free = 6% INR)
    equity_curve    — list of cumulative PnL values per bar

Usage:
    from backtest.backtester import Backtester
    from data.kite_client import get_historical_candles
    from strategy.indicators import build_dataframe

    candles = get_historical_candles("RELIANCE", "minute", lookback_days=30)
    df = build_dataframe(candles)

    bt = Backtester(symbol="RELIANCE", df=df)
    result = bt.run()
    result.print_summary()
    result.plot()              # opens matplotlib chart
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import CAPITAL, RISK_PER_TRADE, SLIPPAGE, BROKERAGE, TRAILING_SL_PCT, TARGET_MULTIPLIER
from strategy.indicators import calculate_rsi, vwap, average_volume, atr, ema
from strategy.intraday_momentum import generate_signal, compute_trade_levels
from agent.decision_agent import estimate_confidence, filter_signal, record_trade_outcome
from risk.risk_manager import calculate_position_size

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.06  # 6% annual (RBI rate proxy)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    symbol: str
    total_bars: int
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    # Computed metrics
    total_pnl: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_trade: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    def print_summary(self) -> None:
        wins   = sum(1 for t in self.trades if t.get("pnl", 0) > 0)
        losses = len(self.trades) - wins
        print(f"""
╔══════════════════════════════════════════════════════╗
║           BACKTEST RESULTS — {self.symbol:<20}   ║
╠══════════════════════════════════════════════════════╣
║  Bars processed : {self.total_bars:<6}                            ║
║  Total trades   : {len(self.trades):<6}  (W:{wins} / L:{losses})           ║
║  Win rate       : {self.win_rate:>6.1f}%                           ║
║  Total PnL      : ₹{self.total_pnl:>10,.2f}                      ║
║  Avg trade      : ₹{self.avg_trade:>10,.2f}                      ║
║  Best trade     : ₹{self.best_trade:>10,.2f}                      ║
║  Worst trade    : ₹{self.worst_trade:>10,.2f}                      ║
║  Max drawdown   : {self.max_drawdown:>6.1f}%                           ║
║  Sharpe ratio   : {self.sharpe_ratio:>6.2f}                            ║
║  Profit factor  : {self.profit_factor:>6.2f}                            ║
╚══════════════════════════════════════════════════════╝""")

    def plot(self) -> None:
        """Plot equity curve and trade markers using matplotlib."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates

            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=False)
            fig.suptitle(f"Backtest — {self.symbol}", fontsize=14, fontweight="bold")

            # --- Equity curve ---
            ax1 = axes[0]
            ax1.plot(self.equity_curve, color="#00d4aa", linewidth=1.5, label="Equity (₹)")
            ax1.axhline(0, color="#555", linewidth=0.5, linestyle="--")
            ax1.fill_between(range(len(self.equity_curve)), self.equity_curve, 0,
                             where=[v >= 0 for v in self.equity_curve],
                             alpha=0.15, color="#00d4aa")
            ax1.fill_between(range(len(self.equity_curve)), self.equity_curve, 0,
                             where=[v < 0 for v in self.equity_curve],
                             alpha=0.15, color="#ff4d6d")
            ax1.set_ylabel("Cumulative PnL (₹)")
            ax1.set_title("Equity Curve")
            ax1.legend()

            # --- Trade PnL bars ---
            ax2 = axes[1]
            pnls   = [t["pnl"] for t in self.trades if "pnl" in t]
            colors = ["#00d4aa" if p > 0 else "#ff4d6d" for p in pnls]
            ax2.bar(range(len(pnls)), pnls, color=colors, edgecolor="none", alpha=0.8)
            ax2.axhline(0, color="#555", linewidth=0.5)
            ax2.set_xlabel("Trade #")
            ax2.set_ylabel("PnL per trade (₹)")
            ax2.set_title("Trade PnL Distribution")

            plt.tight_layout()
            plt.savefig(f"backtest_{self.symbol}.png", dpi=150)
            logger.info("Chart saved → backtest_%s.png", self.symbol)
            plt.show()
        except ImportError:
            logger.warning("matplotlib not installed — skipping plot (pip install matplotlib)")

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades)


# ---------------------------------------------------------------------------
# Backtester core
# ---------------------------------------------------------------------------

class Backtester:
    """
    Bar-by-bar replay engine.

    Args:
        symbol   : Ticker string (for logging)
        df       : Full OHLCV DataFrame from build_dataframe()
        warmup   : Number of bars consumed before trading starts (indicator warmup)
    """

    def __init__(self, symbol: str, df: pd.DataFrame, warmup: int = 50):
        self.symbol  = symbol
        self.df      = df.copy()
        self.warmup  = warmup

        # Internal paper state (isolated from live executor)
        self._open_pos: Optional[dict] = None
        self._closed_trades: list[dict] = []
        self._equity: float = CAPITAL

    def run(self) -> BacktestResult:
        df = self.df
        total_bars = len(df)
        equity_curve: list[float] = []
        cumulative_pnl = 0.0

        # Pre-compute indicators on full history (look-ahead safe — each bar
        # only uses data up to itself because rolling/ewm are causal)
        df["rsi"]     = calculate_rsi(df)
        df["vwap"]    = vwap(df)
        df["avg_vol"] = average_volume(df)
        df["atr"]     = atr(df)
        df["ema_50"]  = ema(df, period=50)

        logger.info("Backtesting %s — %d bars", self.symbol, total_bars)

        for i in range(self.warmup, total_bars):
            bar     = df.iloc[i]
            price   = bar["close"]
            rsi_v   = bar["rsi"]
            vwap_v  = bar["vwap"]
            vol_v   = int(bar["volume"])
            avg_v   = bar["avg_vol"]
            atr_v   = bar["atr"]
            ema50_v = bar["ema_50"]
            bar_ts  = bar.name  # DatetimeIndex

            if any(pd.isna(v) for v in [rsi_v, vwap_v, atr_v, avg_v]):
                equity_curve.append(cumulative_pnl)
                continue

            # --- Exit check ---
            if self._open_pos:
                should_exit, reason = self._check_exit_backtest(price, bar_ts)
                if should_exit:
                    trade = self._close_position_backtest(price, reason)
                    cumulative_pnl += trade["pnl"]
                    record_trade_outcome(self.symbol, trade["pnl"])
                    equity_curve.append(cumulative_pnl)
                    continue

            equity_curve.append(cumulative_pnl)

            # --- Entry ---
            if self._open_pos:
                continue  # already in a position

            raw_signal = generate_signal(price, vwap_v, rsi_v, vol_v, avg_v)
            vol_ratio  = vol_v / avg_v if avg_v else 1.0
            pvwap      = (price - vwap_v) / vwap_v if vwap_v else 0.0
            confidence = estimate_confidence(rsi_v, vol_ratio, pvwap)
            signal     = filter_signal(raw_signal, self.symbol, confidence, price, ema50_v)

            if signal != "HOLD":
                levels = compute_trade_levels(signal, price, atr_v)
                qty    = calculate_position_size(levels["entry_price"], levels["stop_loss"])
                if qty > 0:
                    slippage = 1 + SLIPPAGE if signal == "BUY" else 1 - SLIPPAGE
                    self._open_pos = {
                        "symbol":      self.symbol,
                        "side":        signal,
                        "entry_price": round(price * slippage, 2),
                        "stop_loss":   levels["stop_loss"],
                        "target":      levels["target"],
                        "qty":         qty,
                        "opened_at":   str(bar_ts),
                        "initial_sl":  levels["stop_loss"],
                    }

        result = self._compute_metrics(equity_curve, total_bars)
        result.print_summary()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_exit_backtest(self, price: float, ts) -> tuple[bool, str]:
        pos  = self._open_pos
        side = pos["side"]

        # Time exit: close 5 min before market close
        if hasattr(ts, "hour") and (
            ts.hour > MARKET_CLOSE_HOUR or
            (ts.hour == MARKET_CLOSE_HOUR and ts.minute >= MARKET_CLOSE_MINUTE - 5)
        ):
            return True, "TIME_EXIT"

        if side == "BUY":
            trailing = price * (1 - TRAILING_SL_PCT)
            if trailing > pos["stop_loss"]:
                pos["stop_loss"] = trailing
            if price <= pos["stop_loss"]: return True, "STOP_LOSS"
            if price >= pos["target"]:    return True, "TARGET_HIT"
        else:
            trailing = price * (1 + TRAILING_SL_PCT)
            if trailing < pos["stop_loss"]:
                pos["stop_loss"] = trailing
            if price >= pos["stop_loss"]: return True, "STOP_LOSS"
            if price <= pos["target"]:    return True, "TARGET_HIT"

        return False, ""

    def _close_position_backtest(self, price: float, reason: str) -> dict:
        pos = self._open_pos
        slip = 1 - SLIPPAGE if pos["side"] == "BUY" else 1 + SLIPPAGE
        exit_p = round(price * slip, 2)

        gross = (
            (exit_p - pos["entry_price"]) * pos["qty"]
            if pos["side"] == "BUY"
            else (pos["entry_price"] - exit_p) * pos["qty"]
        )
        net = round(gross - 2 * BROKERAGE, 2)
        pos.update(exit_price=exit_p, exit_reason=reason, pnl=net)
        self._closed_trades.append(dict(pos))
        self._open_pos = None
        logger.debug("CLOSE %-10s %-4s @ ₹%.2f  PnL=₹%.2f  [%s]",
                     self.symbol, pos["side"], exit_p, net, reason)
        return pos

    def _compute_metrics(self, equity_curve: list[float], total_bars: int) -> BacktestResult:
        trades = self._closed_trades
        pnls   = [t["pnl"] for t in trades]

        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_pnl    = round(sum(pnls), 2)
        win_rate     = round(len(wins) / max(len(pnls), 1) * 100, 1)
        avg_trade    = round(sum(pnls) / max(len(pnls), 1), 2)
        best_trade   = round(max(pnls, default=0), 2)
        worst_trade  = round(min(pnls, default=0), 2)

        # Profit factor
        gross_wins   = sum(wins) if wins else 0
        gross_losses = abs(sum(losses)) if losses else 1e-9
        profit_factor = round(gross_wins / gross_losses, 2)

        # Max drawdown (on equity curve)
        peak = -math.inf
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / max(abs(peak), 1) * 100
            if dd > max_dd:
                max_dd = dd
        max_dd = round(max_dd, 2)

        # Sharpe ratio (annualised, daily PnL series)
        if len(pnls) > 1:
            arr    = np.array(pnls)
            mu     = arr.mean()
            sigma  = arr.std(ddof=1) + 1e-9
            # Assume 252 trading days, scale trade-level to daily proxy
            sharpe = round((mu - RISK_FREE_RATE / 252) / sigma * math.sqrt(252), 2)
        else:
            sharpe = 0.0

        return BacktestResult(
            symbol       = self.symbol,
            total_bars   = total_bars,
            trades       = trades,
            equity_curve = equity_curve,
            total_pnl    = total_pnl,
            win_rate     = win_rate,
            max_drawdown = max_dd,
            sharpe_ratio = sharpe,
            profit_factor= profit_factor,
            avg_trade    = avg_trade,
            best_trade   = best_trade,
            worst_trade  = worst_trade,
        )
