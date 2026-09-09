# =============================================================================
# event_agent/prediction/dynamic_weights.py — Data-Driven Agent Reliability
# =============================================================================
"""
V3.5 Data-Driven & Regime-Conditional Agent Reliability Weighting.
Replaces arbitrary static weights with out-of-sample empirical reliability scores.
Adjusts ensemble weights conditionally based on detected market regime (Bull, Bear, Sideways).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class AgentScorecard:
    agent_name: str
    sample_size: int
    accuracy_pct: float
    brier_score: float
    sharpe_ratio: float
    profit_factor: float
    max_drawdown_pct: float
    reliability_weight: float


class DynamicReliabilityEngine:
    """
    Computes data-driven reliability weights across agents and regimes.
    """

    BASE_AGENTS = ["Alpha", "Momentum", "Macro", "Defensive", "Contrarian"]

    # Regime-conditional historical tilt priors (calibrated empirically)
    REGIME_TILTS = {
        "BULL": {
            "Alpha": 1.20,
            "Momentum": 1.35,
            "Macro": 0.90,
            "Defensive": 0.65,
            "Contrarian": 0.70,
        },
        "BEAR": {
            "Alpha": 0.85,
            "Momentum": 0.70,
            "Macro": 1.15,
            "Defensive": 1.45,
            "Contrarian": 1.10,
        },
        "CRISIS": {
            "Alpha": 0.50,
            "Momentum": 0.40,
            "Macro": 1.30,
            "Defensive": 1.70,
            "Contrarian": 1.10,
        },
        "SIDEWAYS": {
            "Alpha": 1.00,
            "Momentum": 0.75,
            "Macro": 0.95,
            "Defensive": 1.15,
            "Contrarian": 1.30,
        },
    }

    @classmethod
    def calculate_agent_scorecards(
        cls,
        agent_trades_history: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, AgentScorecard]:
        """
        Computes performance scorecard for each agent from historical closed outcomes:
        trades: [{"return_pct": 0.015, "direction_correct": True, "predicted_prob": 0.65}, ...]
        """
        scorecards: Dict[str, AgentScorecard] = {}
        reliability_raw: Dict[str, float] = {}

        for name in cls.BASE_AGENTS:
            trades = agent_trades_history.get(name, [])
            n = len(trades)
            if n < 5:
                # Prior neutral scorecard
                scorecards[name] = AgentScorecard(
                    agent_name=name,
                    sample_size=n,
                    accuracy_pct=50.0,
                    brier_score=0.25,
                    sharpe_ratio=0.5,
                    profit_factor=1.0,
                    max_drawdown_pct=5.0,
                    reliability_weight=0.20,
                )
                reliability_raw[name] = 1.0
                continue

            wins = [t for t in trades if t.get("direction_correct", False)]
            acc = (len(wins) / n) * 100.0

            rets = [float(t.get("return_pct", 0.0)) for t in trades]
            arr_rets = np.array(rets)
            mean_r = float(np.mean(arr_rets))
            std_r = float(np.std(arr_rets)) + 1e-6
            sharpe = (mean_r / std_r) * np.sqrt(252)

            pos_sum = sum(r for r in rets if r > 0)
            neg_sum = abs(sum(r for r in rets if r < 0))
            pf = (pos_sum / neg_sum) if neg_sum > 1e-6 else (2.5 if pos_sum > 0 else 1.0)

            # Cumulative drawdown
            cum = np.cumsum(arr_rets)
            peak = np.maximum.accumulate(cum)
            dd = float(np.max(peak - cum)) if len(cum) > 0 else 0.0

            # Brier score
            probs = [float(t.get("predicted_prob", 0.55)) for t in trades]
            outs = [1.0 if t.get("direction_correct", False) else 0.0 for t in trades]
            brier = float(np.mean([(p - o) ** 2 for p, o in zip(probs, outs)]))

            # Reliability metric: combination of (1 - Brier) * max(0, Sharpe)
            rel = max(0.1, (1.0 - brier * 2.0)) * max(0.2, (sharpe + 1.0))
            reliability_raw[name] = rel

            scorecards[name] = AgentScorecard(
                agent_name=name,
                sample_size=n,
                accuracy_pct=round(acc, 1),
                brier_score=round(brier, 4),
                sharpe_ratio=round(sharpe, 2),
                profit_factor=round(pf, 2),
                max_drawdown_pct=round(dd * 100, 1),
                reliability_weight=round(rel, 3),
            )

        # Normalize reliability weights to sum to 1.0
        tot = sum(reliability_raw.values()) if sum(reliability_raw.values()) > 0 else 1.0
        for name in cls.BASE_AGENTS:
            scorecards[name].reliability_weight = round(reliability_raw[name] / tot, 4)

        return scorecards

    @classmethod
    def get_regime_conditional_weights(
        cls,
        base_scorecards: Dict[str, AgentScorecard],
        current_regime: str = "BULL",
    ) -> Dict[str, float]:
        """
        Adjust base data-driven weights conditionally based on market regime.
        """
        reg_upper = current_regime.upper()
        tilt_map = cls.REGIME_TILTS.get(reg_upper, cls.REGIME_TILTS["BULL"])

        tilted: Dict[str, float] = {}
        for name in cls.BASE_AGENTS:
            base_w = base_scorecards[name].reliability_weight if name in base_scorecards else 0.20
            multiplier = tilt_map.get(name, 1.0)
            tilted[name] = base_w * multiplier

        tot = sum(tilted.values()) if sum(tilted.values()) > 0 else 1.0
        return {name: round(tilted[name] / tot, 4) for name in cls.BASE_AGENTS}
