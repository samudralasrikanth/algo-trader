# =============================================================================
# event_agent/sentinel/market_shock_detector.py — News-Independent Market Shock Detector
# =============================================================================
"""
V4.2.1 News-Independent Market Shock Detector:
- Evaluates rapid price velocity, volatility spikes, and cross-asset anomalies.
- Operates even when NEWS = NONE.
- Direct circuit-breaker path into TradeGuard and IndependentKillSwitch.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import EventCategory, SentinelEvent, TriggerVerdict

logger = logging.getLogger(__name__)


@dataclass
class MarketShockResult:
    is_shock: bool
    shock_score: float                     # 0.0 to 100.0
    primary_trigger: Optional[str] = None
    shock_metrics: Dict[str, Any] = field(default_factory=dict)
    sentinel_event: Optional[SentinelEvent] = None


class MarketShockDetector:
    """
    Evaluates market anomalies across velocity and volatility thresholds.
    Triggers independently of news publication.
    """

    # Institutional Shock Thresholds
    NIFTY_RAPID_DROP_PCT = -2.50          # NIFTY drops > 2.5% intraday
    INDIA_VIX_SURGE_PCT = 35.0            # India VIX spikes > 35%
    USDINR_SPIKE_PCT = 1.00               # USD/INR moves > 1.0% in session
    US_FUTURES_DROP_PCT = -2.00           # S&P / Nasdaq futures fall > 2.0%

    @classmethod
    def evaluate(
        cls,
        market_data: Dict[str, Any],
        historical_baseline: Optional[Dict[str, Any]] = None,
    ) -> MarketShockResult:
        """
        Evaluate real-time quote feeds for extreme dislocation.
        market_data expected format:
          {
            "nifty_change_pct": float,
            "india_vix_change_pct": float,
            "usdinr_change_pct": float,
            "us_futures_change_pct": float,
            "nifty_10m_velocity_pct": Optional[float]
          }
        """
        nifty_chg = float(market_data.get("nifty_change_pct", 0.0))
        nifty_10m = float(market_data.get("nifty_10m_velocity_pct", nifty_chg))
        vix_chg = float(market_data.get("india_vix_change_pct", 0.0))
        usdinr_chg = float(market_data.get("usdinr_change_pct", 0.0))
        us_fut_chg = float(market_data.get("us_futures_change_pct", 0.0))

        reasons = []
        shock_score = 0.0

        # Check 1: NIFTY sudden crash
        if nifty_10m <= cls.NIFTY_RAPID_DROP_PCT or nifty_chg <= cls.NIFTY_RAPID_DROP_PCT:
            reasons.append(f"NIFTY velocity dislocated ({nifty_10m:.2f}% <= {cls.NIFTY_RAPID_DROP_PCT}%)")
            shock_score += 45.0

        # Check 2: India VIX explosion
        if vix_chg >= cls.INDIA_VIX_SURGE_PCT:
            reasons.append(f"India VIX surge (+{vix_chg:.2f}% >= +{cls.INDIA_VIX_SURGE_PCT}%)")
            shock_score += 35.0

        # Check 3: USD/INR currency run
        if usdinr_chg >= cls.USDINR_SPIKE_PCT:
            reasons.append(f"USD/INR sharp depreciation (+{usdinr_chg:.2f}% >= +{cls.USDINR_SPIKE_PCT}%)")
            shock_score += 20.0

        # Check 4: Global futures selloff
        if us_fut_chg <= cls.US_FUTURES_DROP_PCT:
            reasons.append(f"US futures plunge ({us_fut_chg:.2f}% <= {cls.US_FUTURES_DROP_PCT}%)")
            shock_score += 25.0

        shock_score = min(100.0, shock_score)
        is_shock = shock_score >= 40.0 or len(reasons) > 0

        metrics = {
            "nifty_change_pct": nifty_chg,
            "nifty_10m_velocity_pct": nifty_10m,
            "india_vix_change_pct": vix_chg,
            "usdinr_change_pct": usdinr_chg,
            "us_futures_change_pct": us_fut_chg,
            "shock_score": round(shock_score, 2),
            "reasons": reasons,
        }

        sentinel_evt = None
        if is_shock:
            metrics["verdict"] = "MARKET_SHOCK"
            now_iso = datetime.now(timezone.utc).isoformat()
            ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            evt_id = f"EV-SHOCK-{ts_str}"
            summary_title = f"MARKET SHOCK: {'; '.join(reasons)}"
            sentinel_evt = SentinelEvent(
                event_id=evt_id,
                category=EventCategory.MARKET_SHOCK,
                source="MARKET_TICK_ANOMALY_DETECTOR",
                title=summary_title,
                description=f"Automated news-independent cross-asset shock detected: {reasons}",
                raw_payload_hash=SentinelEvent.generate_hash(summary_title),
                timestamp=now_iso,
                event_data=metrics,
            )
            logger.warning(f"🚨 MARKET SHOCK DETECTED [Score={shock_score}]: {summary_title}")

        return MarketShockResult(
            is_shock=is_shock,
            shock_score=shock_score,
            primary_trigger=reasons[0] if reasons else None,
            shock_metrics=metrics,
            sentinel_event=sentinel_evt,
        )
