# =============================================================================
# event_agent/research/baseline_models.py — 5 Benchmark Baseline Models
# =============================================================================
"""
Implements 5 benchmark models to ensure every predictive signal proves itself
against both trivial heuristics and passive indexing:

    Baseline 0: RandomBaseline (Deterministic SHA-256 seed)
    Baseline 1: PreviousDayBaseline (Yesterday return direction)
    Baseline 2: MomentumBaseline (5-day return sign)
    Baseline 3: MeanReversionBaseline (Overextension reversal)
    Baseline 4: BuyAndHoldBaseline (Passive Long Benchmark)

Every prediction run stores all 5 baseline outputs alongside the agent's prediction.
"""

import hashlib
import logging
import random
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class RandomBaseline:
    """
    Baseline 0: Random direction. ~50% expected accuracy.
    Uses SHA-256 deterministic seed for 100% reproducibility across processes/runs.
    Never relies on Python hash() which varies with PYTHONHASHSEED.
    """

    def predict(self, symbol: str, prediction_date: str) -> Dict[str, Any]:
        seed_bytes = hashlib.sha256(f"{symbol}:{prediction_date}".encode("utf-8")).digest()
        seed = int.from_bytes(seed_bytes[:8], "big")
        rng = random.Random(seed)
        direction = rng.choice(["UP", "DOWN"])
        action = "BUY" if direction == "UP" else "SELL"
        
        return {
            "baseline_id": "baseline_0_random",
            "model_type": "DETERMINISTIC_RANDOM",
            "direction": direction,
            "action": action,
            "confidence": 50.0,
            "expected_1d_pct": 0.0,
            "seed": seed,
            "source": "random_sha256",
        }


class PreviousDayBaseline:
    """
    Baseline 1: Yesterday UP -> predict UP; Yesterday DOWN -> predict DOWN.
    Typical empirical accuracy: ~50-52%.
    """

    def predict(
        self,
        symbol: str,
        price_history: Optional[List[float]] = None,
        prev_return: Optional[float] = None,
    ) -> Dict[str, Any]:
        ret = 0.0
        if prev_return is not None:
            ret = prev_return
        elif price_history and len(price_history) >= 2:
            p_prev = price_history[-2]
            p_curr = price_history[-1]
            if p_prev > 0:
                ret = (p_curr - p_prev) / p_prev

        direction = "UP" if ret >= 0 else "DOWN"
        action = "BUY" if direction == "UP" else "SELL"

        return {
            "baseline_id": "baseline_1_previous_day",
            "model_type": "PREVIOUS_DAY_PERSISTENCE",
            "direction": direction,
            "action": action,
            "confidence": 51.0,
            "prev_return_pct": round(ret * 100, 3),
            "source": "previous_day_return",
        }


class MomentumBaseline:
    """
    Baseline 2: 5-day return > 0 -> predict UP; else predict DOWN.
    Typical empirical accuracy: ~52-54%.
    """

    def predict(
        self,
        symbol: str,
        price_history: Optional[List[float]] = None,
        ret_5d: Optional[float] = None,
    ) -> Dict[str, Any]:
        ret = 0.0
        if ret_5d is not None:
            ret = ret_5d
        elif price_history and len(price_history) >= 5:
            p_old = price_history[-5]
            p_curr = price_history[-1]
            if p_old > 0:
                ret = (p_curr - p_old) / p_old
        elif price_history and len(price_history) >= 2:
            p_old = price_history[0]
            p_curr = price_history[-1]
            if p_old > 0:
                ret = (p_curr - p_old) / p_old

        direction = "UP" if ret >= 0 else "DOWN"
        action = "BUY" if direction == "UP" else "SELL"

        return {
            "baseline_id": "baseline_2_momentum_5d",
            "model_type": "MOMENTUM_5D",
            "direction": direction,
            "action": action,
            "confidence": 53.0,
            "momentum_5d_pct": round(ret * 100, 3),
            "source": "rolling_5d_return",
        }


class MeanReversionBaseline:
    """
    Baseline 3: Overbought/Oversold reversal.
    If 5-day return > +2% -> predict DOWN.
    If 5-day return < -2% -> predict UP.
    Else fades 1-day move or holds neutral.
    Typical empirical accuracy: ~48-52%.
    """

    def predict(
        self,
        symbol: str,
        price_history: Optional[List[float]] = None,
        ret_5d: Optional[float] = None,
        ret_1d: Optional[float] = None,
    ) -> Dict[str, Any]:
        r5 = 0.0
        r1 = 0.0

        if ret_5d is not None:
            r5 = ret_5d
        elif price_history and len(price_history) >= 5:
            r5 = (price_history[-1] - price_history[-5]) / price_history[-5] if price_history[-5] > 0 else 0.0

        if ret_1d is not None:
            r1 = ret_1d
        elif price_history and len(price_history) >= 2:
            r1 = (price_history[-1] - price_history[-2]) / price_history[-2] if price_history[-2] > 0 else 0.0

        if r5 > 0.02:
            direction = "DOWN"
            action = "SELL"
            reason = "overbought_reversal"
        elif r5 < -0.02:
            direction = "UP"
            action = "BUY"
            reason = "oversold_bounce"
        else:
            # Short-term fade
            direction = "DOWN" if r1 >= 0 else "UP"
            action = "SELL" if direction == "DOWN" else "BUY"
            reason = "1d_fade"

        return {
            "baseline_id": "baseline_3_mean_reversion",
            "model_type": "MEAN_REVERSION",
            "direction": direction,
            "action": action,
            "confidence": 50.0,
            "trigger_reason": reason,
            "ret_5d_pct": round(r5 * 100, 3),
            "source": "mean_reversion_rules",
        }


class BuyAndHoldBaseline:
    """
    Baseline 4: Always LONG Nifty / Stock.
    The primary hurdle every active alpha strategy must exceed.
    """

    def predict(self, symbol: str, benchmark_symbol: str = "^NSEI") -> Dict[str, Any]:
        return {
            "baseline_id": "baseline_4_buy_and_hold",
            "model_type": "BUY_AND_HOLD_BENCHMARK",
            "direction": "UP",
            "action": "BUY",
            "confidence": 100.0,
            "target_instrument": benchmark_symbol,
            "source": "passive_benchmark",
            "description": "Always LONG Nifty 50 passive index holding",
        }

    def get_return(
        self,
        start_price: float,
        end_price: float,
    ) -> float:
        """Calculate benchmark return over an evaluation period."""
        if start_price <= 0:
            return 0.0
        return (end_price - start_price) / start_price


class Momentum20dBaseline:
    """
    Baseline 4: 20-day return > 0 -> predict UP; else predict DOWN.
    Captures medium-term monthly drift.
    """

    def predict(
        self,
        symbol: str,
        price_history: Optional[List[float]] = None,
        ret_20d: Optional[float] = None,
    ) -> Dict[str, Any]:
        ret = 0.0
        if ret_20d is not None:
            ret = ret_20d
        elif price_history and len(price_history) >= 21:
            p_20_ago = price_history[-21]
            p_curr = price_history[-1]
            if p_20_ago > 0:
                ret = (p_curr - p_20_ago) / p_20_ago

        direction = "UP" if ret >= 0 else "DOWN"
        action = "BUY" if direction == "UP" else "SELL"

        return {
            "baseline_id": "baseline_4_momentum_20d",
            "model_type": "MOMENTUM_20D",
            "direction": direction,
            "action": action,
            "confidence": 53.0,
            "ret_20d_pct": round(ret * 100, 3),
            "source": "20d_return_sign",
        }


class MovingAverageTrendBaseline:
    """
    Baseline 5: Fast SMA (20) > Slow SMA (50) -> predict UP; else predict DOWN.
    """

    def predict(
        self,
        symbol: str,
        price_history: Optional[List[float]] = None,
        sma_20: Optional[float] = None,
        sma_50: Optional[float] = None,
    ) -> Dict[str, Any]:
        if sma_20 is not None and sma_50 is not None:
            direction = "UP" if sma_20 >= sma_50 else "DOWN"
        elif price_history and len(price_history) >= 50:
            m20 = sum(price_history[-20:]) / 20.0
            m50 = sum(price_history[-50:]) / 50.0
            direction = "UP" if m20 >= m50 else "DOWN"
        elif price_history and len(price_history) >= 20:
            m20 = sum(price_history[-20:]) / 20.0
            direction = "UP" if price_history[-1] >= m20 else "DOWN"
        else:
            direction = "UP"

        action = "BUY" if direction == "UP" else "SELL"
        return {
            "baseline_id": "baseline_5_ma_trend",
            "model_type": "MOVING_AVERAGE_TREND",
            "direction": direction,
            "action": action,
            "confidence": 52.5,
            "source": "sma_crossover",
        }


class NiftyMarketDirectionBaseline:
    """
    Baseline 6: NIFTY market direction baseline.
    Predicts stock moves in the same direction as the broad market index.
    """

    def predict(
        self,
        symbol: str,
        nifty_direction: str = "UP",
        nifty_return_pct: float = 0.0,
    ) -> Dict[str, Any]:
        nd = nifty_direction.upper() if nifty_direction in ("UP", "DOWN") else "UP"
        return {
            "baseline_id": "baseline_6_nifty_direction",
            "model_type": "MARKET_DIRECTION_PERSISTENCE",
            "direction": nd,
            "action": "BUY" if nd == "UP" else "SELL",
            "confidence": 53.5,
            "nifty_return_pct": round(nifty_return_pct, 3),
            "source": "nifty_macro_direction",
        }


class SimpleRSIBaseline:
    """
    Baseline 7: Simple 14-period RSI baseline.
    RSI < 30 (oversold) -> predict UP; RSI > 70 (overbought) -> predict DOWN; else follow trend.
    """

    def predict(
        self,
        symbol: str,
        price_history: Optional[List[float]] = None,
        rsi_14: Optional[float] = None,
    ) -> Dict[str, Any]:
        rsi = 50.0
        if rsi_14 is not None:
            rsi = rsi_14
        elif price_history and len(price_history) >= 15:
            # Simple RSI calculation
            deltas = [price_history[i] - price_history[i - 1] for i in range(1, len(price_history))]
            recent_deltas = deltas[-14:]
            gains = [d for d in recent_deltas if d > 0]
            losses = [-d for d in recent_deltas if d < 0]
            avg_gain = sum(gains) / 14.0 if gains else 0.0
            avg_loss = sum(losses) / 14.0 if losses else 0.0001
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        if rsi < 30.0:
            direction = "UP"
            reason = "rsi_oversold_bounce"
        elif rsi > 70.0:
            direction = "DOWN"
            reason = "rsi_overbought_fade"
        else:
            direction = "UP" if rsi >= 50.0 else "DOWN"
            reason = "rsi_midpoint_trend"

        return {
            "baseline_id": "baseline_7_rsi_14",
            "model_type": "SIMPLE_RSI_14",
            "direction": direction,
            "action": "BUY" if direction == "UP" else "SELL",
            "confidence": 51.5,
            "rsi_value": round(rsi, 2),
            "reason": reason,
            "source": "technical_rsi_rules",
        }


class BaselineSuite:
    """
    Unified manager that runs all 7 benchmark baselines together and returns
    a standardized JSON-serializable dictionary for snapshot storage.
    """

    def __init__(self):
        self.b1 = RandomBaseline()
        self.b2 = PreviousDayBaseline()
        self.b3 = MomentumBaseline()
        self.b4 = Momentum20dBaseline()
        self.b5 = MovingAverageTrendBaseline()
        self.b6 = NiftyMarketDirectionBaseline()
        self.b7 = SimpleRSIBaseline()
        # Backward compatibility aliases
        self.b0 = self.b1
        self.mean_reversion = MeanReversionBaseline()
        self.buy_and_hold = BuyAndHoldBaseline()

    def evaluate_all(
        self,
        symbol: str,
        prediction_date: str,
        price_history: Optional[List[float]] = None,
        prev_return: Optional[float] = None,
        ret_5d: Optional[float] = None,
        ret_20d: Optional[float] = None,
        nifty_direction: str = "UP",
        rsi_14: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute all 7 baselines (plus backward-compatible models).
        """
        res_b1 = self.b1.predict(symbol, prediction_date)
        res_b2 = self.b2.predict(symbol, price_history=price_history, prev_return=prev_return)
        res_b3 = self.b3.predict(symbol, price_history=price_history, ret_5d=ret_5d)
        res_b4 = self.b4.predict(symbol, price_history=price_history, ret_20d=ret_20d)
        res_b5 = self.b5.predict(symbol, price_history=price_history)
        res_b6 = self.b6.predict(symbol, nifty_direction=nifty_direction)
        res_b7 = self.b7.predict(symbol, price_history=price_history, rsi_14=rsi_14)

        # Legacy models
        res_mr = self.mean_reversion.predict(symbol, price_history=price_history, ret_5d=ret_5d, ret_1d=prev_return)
        res_bh = self.buy_and_hold.predict(symbol)

        active_baselines = [res_b1, res_b2, res_b3, res_b4, res_b5, res_b6, res_b7]

        return {
            # 7 required baselines
            "baseline_1_random": res_b1,
            "baseline_2_previous_day": res_b2,
            "baseline_3_momentum_5d": res_b3,
            "baseline_4_momentum_20d": res_b4,
            "baseline_5_ma_trend": res_b5,
            "baseline_6_nifty_direction": res_b6,
            "baseline_7_rsi_14": res_b7,
            # Backward compatibility aliases
            "random": res_b1,
            "previous_day": res_b2,
            "momentum_5d": res_b3,
            "mean_reversion": res_mr,
            "buy_and_hold": res_bh,
            "summary": {
                "bullish_count": sum(1 for b in active_baselines if b["direction"] == "UP"),
                "bearish_count": sum(1 for b in active_baselines if b["direction"] == "DOWN"),
                "total_baselines": len(active_baselines),
            },
        }
