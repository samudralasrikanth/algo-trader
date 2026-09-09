# =============================================================================
# event_agent/prediction/prediction_decay.py — Signal Half-Life & Decay Modeling
# =============================================================================
"""
V3.5 Prediction Decay & Alpha Half-Life Engine.
Tracks predictive decay profiles across 7 horizons (15m, 30m, 1h, 1D, 3D, 5D, 20D).
Determines exact horizon when event-driven edge dissipates to identify optimal
holding periods for each event category.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np

DECAY_HORIZONS = ["15m", "30m", "60m", "1D", "3D", "5D", "20D"]
HORIZON_HOURS = {
    "15m": 0.25,
    "30m": 0.5,
    "60m": 1.0,
    "1D": 6.25,     # NSE trading day = 6h 15m
    "3D": 18.75,
    "5D": 31.25,
    "20D": 125.0,
}


@dataclass
class DecayProfile:
    event_type: str
    horizon_accuracies: Dict[str, float]  # horizon -> win rate %
    horizon_correlations: Dict[str, float]# horizon -> correlation with final move
    half_life_hours: float
    optimal_horizon: str
    lifespan_category: str                # INTRADAY, SHORT_TERM, MEDIUM_TERM


class PredictionDecayEngine:
    """
    Computes alpha decay rates across all 7 evaluation horizons.
    """

    @classmethod
    def estimate_decay(
        cls,
        event_type: str,
        horizon_results: Dict[str, List[Dict[str, Any]]],
    ) -> DecayProfile:
        """
        horizon_results: Dict mapping horizon ("15m", "1D", etc.) to list of prediction-outcome pairs:
            [{"predicted_dir": "UP", "actual_ret": 0.015, "direction_correct": True}, ...]
        """
        accuracies: Dict[str, float] = {}
        correlations: Dict[str, float] = {}

        for h in DECAY_HORIZONS:
            records = horizon_results.get(h, [])
            if not records:
                # Default decay curve based on event taxonomy
                accuracies[h] = 50.0
                correlations[h] = 0.0
                continue

            wins = [r for r in records if r.get("direction_correct", False)]
            acc = (len(wins) / len(records)) * 100.0
            accuracies[h] = round(acc, 1)

            pred_signs = [1.0 if r.get("predicted_dir") == "UP" else -1.0 for r in records]
            acts = [float(r.get("actual_ret", 0.0)) for r in records]
            if len(records) >= 3 and np.std(pred_signs) > 0 and np.std(acts) > 0:
                corr = float(np.corrcoef(pred_signs, acts)[0, 1])
            else:
                corr = 0.0
            correlations[h] = round(corr, 3)

        # Find horizon with maximum edge
        valid_accs = {h: accuracies[h] for h in DECAY_HORIZONS if h in accuracies}
        opt_h = max(valid_accs, key=valid_accs.get) if valid_accs else "1D"

        # Calculate half-life: point where excess accuracy (Acc - 50%) drops to half of peak
        peak_edge = max(0.1, valid_accs.get(opt_h, 50.0) - 50.0)
        half_edge = peak_edge / 2.0

        half_life_h = 24.0  # default 1 day
        for h in DECAY_HORIZONS:
            cur_edge = valid_accs.get(h, 50.0) - 50.0
            if cur_edge <= half_edge and HORIZON_HOURS.get(h, 24.0) >= HORIZON_HOURS.get(opt_h, 6.25):
                half_life_h = HORIZON_HOURS.get(h, 24.0)
                break

        if half_life_h <= 6.25:
            cat = "INTRADAY"
        elif half_life_h <= 32.0:
            cat = "SHORT_TERM"
        else:
            cat = "MEDIUM_TERM"

        return DecayProfile(
            event_type=event_type,
            horizon_accuracies=accuracies,
            horizon_correlations=correlations,
            half_life_hours=round(half_life_h, 1),
            optimal_horizon=opt_h,
            lifespan_category=cat,
        )
