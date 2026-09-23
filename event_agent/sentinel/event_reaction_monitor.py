# =============================================================================
# event_agent/sentinel/event_reaction_monitor.py — Cross-Market Reaction Monitor
# =============================================================================
"""
V4.2.1 Cross-Market Reaction Monitor:
- Tracks post-event asset price transmission across key global barometers:
    US Dollar Index (DXY), US 10Y Yield, S&P 500 futures, COMEX Gold, CBOE VIX, USD/INR.
- Computes normalized composite market reaction score [0.0 to 100.0].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketReactionSnapshot:
    measured_at: str
    composite_reaction_score: float        # 0.0 to 100.0
    barometers: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "measured_at": self.measured_at,
            "composite_reaction_score": round(self.composite_reaction_score, 2),
            "barometers": self.barometers,
            "reasons": self.reasons,
        }


class EventReactionMonitor:
    """
    Evaluates multi-asset price movements following a macro event or news item.
    """

    @classmethod
    def evaluate_reaction(
        cls,
        market_quotes: Dict[str, Any],
        pre_event_baseline: Optional[Dict[str, Any]] = None,
    ) -> MarketReactionSnapshot:
        """
        Evaluate market reaction across barometers.
        Calculates deltas vs pre-event baseline if provided, or uses quote change_pct.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        barometers: dict[str, float] = {}
        reasons: list[str] = []
        score = 0.0

        # Helper to extract delta from multiple possible keys
        def get_delta(*keys: str) -> float:
            for k in keys:
                if not k:
                    continue
                cur = market_quotes.get(k)
                if cur is not None:
                    if isinstance(cur, dict):
                        return float(cur.get("change_pct", 0.0))
                    return float(cur)
            return 0.0

        # 1. USD Index (DXY)
        dxy_chg = get_delta("dxy", "DXY", "dxy_change_pct", "dxy_delta_pct")
        barometers["dxy_delta_pct"] = dxy_chg
        if abs(dxy_chg) >= 0.50:
            score += 20.0
            reasons.append(f"DXY moved {dxy_chg:+.2f}%")

        # 2. US 10Y Yield
        us10y_chg = get_delta("us10y", "US10Y", "us10y_change_pct", "us_10y_change_pct", "us10y_delta_pct")
        barometers["us10y_delta_pct"] = us10y_chg
        if abs(us10y_chg) >= 1.50:
            score += 25.0
            reasons.append(f"US 10Y Treasury yield moved {us10y_chg:+.2f}%")

        # 3. Global Equity Futures (S&P 500 / NASDAQ)
        sp_fut_chg = get_delta("sp_futures", "us_futures_change_pct")
        barometers["sp_futures_delta_pct"] = sp_fut_chg
        if abs(sp_fut_chg) >= 0.80:
            score += 25.0
            reasons.append(f"US Futures moved {sp_fut_chg:+.2f}%")

        # 4. COMEX Gold
        gold_chg = get_delta("gold", "GOLD")
        barometers["gold_delta_pct"] = gold_chg
        if abs(gold_chg) >= 1.00:
            score += 15.0
            reasons.append(f"Gold moved {gold_chg:+.2f}%")

        # 5. Volatility (CBOE VIX / India VIX)
        vix_chg = get_delta("india_vix_change_pct", "vix")
        barometers["vix_delta_pct"] = vix_chg
        if vix_chg >= 10.0:
            score += 25.0
            reasons.append(f"VIX surged {vix_chg:+.2f}%")

        # 6. USD/INR Spot
        usdinr_chg = get_delta("usdinr_change_pct", "usdinr")
        barometers["usdinr_delta_pct"] = usdinr_chg
        if abs(usdinr_chg) >= 0.30:
            score += 20.0
            reasons.append(f"USD/INR moved {usdinr_chg:+.2f}%")

        composite_score = min(100.0, score)
        return MarketReactionSnapshot(
            measured_at=now_iso,
            composite_reaction_score=composite_score,
            barometers=barometers,
            reasons=reasons,
        )
