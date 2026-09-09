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


class BaselineSuite:
    """
    Unified manager that runs all 5 baselines together and returns
    a standardized JSON-serializable dictionary for snapshot storage.
    """

    def __init__(self):
        self.b0 = RandomBaseline()
        self.b1 = PreviousDayBaseline()
        self.b2 = MomentumBaseline()
        self.b3 = MeanReversionBaseline()
        self.b4 = BuyAndHoldBaseline()

    def evaluate_all(
        self,
        symbol: str,
        prediction_date: str,
        price_history: Optional[List[float]] = None,
        prev_return: Optional[float] = None,
        ret_5d: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute all 5 baselines. Returns dict keyed by baseline name.
        """
        res_b0 = self.b0.predict(symbol, prediction_date)
        res_b1 = self.b1.predict(symbol, price_history=price_history, prev_return=prev_return)
        res_b2 = self.b2.predict(symbol, price_history=price_history, ret_5d=ret_5d)
        res_b3 = self.b3.predict(symbol, price_history=price_history, ret_5d=ret_5d, ret_1d=prev_return)
        res_b4 = self.b4.predict(symbol)

        return {
            "random": res_b0,
            "previous_day": res_b1,
            "momentum_5d": res_b2,
            "mean_reversion": res_b3,
            "buy_and_hold": res_b4,
            "summary": {
                "bullish_count": sum(
                    1 for b in [res_b0, res_b1, res_b2, res_b3, res_b4] if b["direction"] == "UP"
                ),
                "bearish_count": sum(
                    1 for b in [res_b0, res_b1, res_b2, res_b3, res_b4] if b["direction"] == "DOWN"
                ),
            },
        }
