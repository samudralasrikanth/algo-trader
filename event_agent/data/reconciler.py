# =============================================================================
# event_agent/data/reconciler.py — Market Data Reconciler & Health Tracker
# =============================================================================
"""
Reconciles primary market data (yfinance) against secondary fallback (NSE Public Adapter).
Enforces freshness validation: FRESH, STALE, DEGRADED, INVALID.
Records discrepancies (e.g. ₹1,250 vs ₹1,251) and maintains Data Source Health status.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..adapters.market_data_adapter import MarketDataProvider, YFinanceProvider
from ..adapters.nse_adapter import NSEPublicAdapter

logger = logging.getLogger(__name__)


@dataclass
class ReconciledQuote:
    """Reconciled quote with discrepancy tracking and quality validation."""
    symbol: str
    price: float
    primary_price: Optional[float]
    secondary_price: Optional[float]
    discrepancy: float
    discrepancy_pct: float
    primary_provider: str
    secondary_provider: str
    market_timestamp: str
    ingestion_timestamp: str
    market_data_age_seconds: float
    quality: str  # "GOOD", "DEGRADED", "INVALID"
    freshness: str  # "FRESH", "STALE", "DEGRADED", "INVALID"
    sources_count: int
    conflicts_count: int
    can_trade: bool
    reconciliation_notes: str = ""
    discrepancy_detected: bool = False

    @property
    def source(self) -> str:
        if self.primary_price is None and self.secondary_price is not None:
            return "nse (fallback)"
        return self.primary_provider

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "primary_price": self.primary_price,
            "secondary_price": self.secondary_price,
            "discrepancy": round(self.discrepancy, 2),
            "discrepancy_pct": round(self.discrepancy_pct, 3),
            "primary_provider": self.primary_provider,
            "secondary_provider": self.secondary_provider,
            "market_timestamp": self.market_timestamp,
            "ingestion_timestamp": self.ingestion_timestamp,
            "market_data_age_seconds": round(self.market_data_age_seconds, 1),
            "quality": self.quality,
            "freshness": self.freshness,
            "sources_count": self.sources_count,
            "conflicts_count": self.conflicts_count,
            "can_trade": self.can_trade,
            "notes": self.reconciliation_notes,
        }


class MarketDataReconciler:
    @property
    def discrepancy_log(self) -> List[Dict[str, Any]]:
        return self._discrepancy_log

    def get_reconciled_quote(self, symbol: str) -> ReconciledQuote:
        return self.reconcile_quote(symbol)

    """
    Reconciles market data across primary and secondary adapters.
    Maintains health telemetry for the Data Source Health Dashboard.
    """

    def __init__(
        self,
        primary_provider: Optional[MarketDataProvider] = None,
        secondary_provider: Optional[MarketDataProvider] = None,
        discrepancy_tolerance_pct: float = 0.5,
        max_discrepancy_pct: Optional[float] = None,
        staleness_threshold_seconds: float = 120.0,
    ):
        self.primary = primary_provider or YFinanceProvider()
        self.secondary = secondary_provider or NSEPublicAdapter()
        if max_discrepancy_pct is not None:
            discrepancy_tolerance_pct = max_discrepancy_pct
        self.discrepancy_tolerance_pct = discrepancy_tolerance_pct
        self.staleness_threshold_seconds = staleness_threshold_seconds

        self._health_status: Dict[str, str] = {
            "YFINANCE": "HEALTHY",
            "NSE": "HEALTHY",
            "NEWS_RSS": "HEALTHY",
            "EVENT_DATA": "HEALTHY",
            "OPTION_CHAIN": "MODELLED",
        }
        self._discrepancy_log: List[Dict[str, Any]] = []

    def reconcile_quote(self, symbol: str) -> ReconciledQuote:
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Fetch from primary
        try:
            q_pri = self.primary.get_quote(symbol)
            p_pri = q_pri.get("price")
            if p_pri and p_pri > 0:
                self._health_status["YFINANCE"] = "HEALTHY"
            else:
                self._health_status["YFINANCE"] = "DEGRADED"
        except Exception as exc:
            logger.warning(f"Primary provider error for {symbol}: {exc}")
            q_pri = {"price": None, "quality": "INVALID", "freshness_seconds": 999}
            p_pri = None
            self._health_status["YFINANCE"] = "DEGRADED"

        # 2. Fetch from secondary
        try:
            q_sec = self.secondary.get_quote(symbol)
            p_sec = q_sec.get("price")
            if p_sec and p_sec > 0:
                self._health_status["NSE"] = "HEALTHY"
            else:
                self._health_status["NSE"] = "DEGRADED"
        except Exception as exc:
            logger.warning(f"Secondary provider error for {symbol}: {exc}")
            q_sec = {"price": None, "quality": "INVALID", "freshness_seconds": 999}
            p_sec = None
            self._health_status["NSE"] = "DEGRADED"

        sources = 0
        if p_pri is not None and p_pri > 0:
            sources += 1
        if p_sec is not None and p_sec > 0:
            sources += 1

        # 3. Handle complete failure
        if sources == 0:
            return ReconciledQuote(
                symbol=symbol,
                price=0.0,
                primary_price=None,
                secondary_price=None,
                discrepancy=0.0,
                discrepancy_pct=0.0,
                primary_provider="yfinance",
                secondary_provider="nse_public",
                market_timestamp=now_iso,
                ingestion_timestamp=now_iso,
                market_data_age_seconds=999.0,
                quality="INVALID",
                freshness="INVALID",
                sources_count=0,
                conflicts_count=0,
                can_trade=False,
                reconciliation_notes="Both primary and secondary providers failed to return a valid quote.",
            )

        # 4. Handle single source availability
        if p_pri is not None and p_sec is None:
            return ReconciledQuote(
                symbol=symbol,
                price=p_pri,
                primary_price=p_pri,
                secondary_price=None,
                discrepancy=0.0,
                discrepancy_pct=0.0,
                primary_provider="yfinance",
                secondary_provider="nse_public",
                market_timestamp=q_pri.get("market_timestamp", now_iso),
                ingestion_timestamp=now_iso,
                market_data_age_seconds=q_pri.get("freshness_seconds", 5.0),
                quality="DEGRADED",
                freshness=q_pri.get("quality", "FRESH"),
                sources_count=1,
                conflicts_count=0,
                can_trade=True,
                reconciliation_notes="Primary provider active; secondary provider unavailable.",
            )

        if p_pri is None and p_sec is not None:
            return ReconciledQuote(
                symbol=symbol,
                price=p_sec,
                primary_price=None,
                secondary_price=p_sec,
                discrepancy=0.0,
                discrepancy_pct=0.0,
                primary_provider="yfinance",
                secondary_provider="nse_public",
                market_timestamp=q_sec.get("market_timestamp", now_iso),
                ingestion_timestamp=now_iso,
                market_data_age_seconds=q_sec.get("freshness_seconds", 10.0),
                quality="DEGRADED",
                freshness=q_sec.get("quality", "FRESH"),
                sources_count=1,
                conflicts_count=0,
                can_trade=True,
                reconciliation_notes="Secondary provider active as fallback; primary provider unavailable.",
            )

        # 5. Reconcile both active sources & record discrepancy
        discrepancy = abs(p_pri - p_sec)
        ref_price = (p_pri + p_sec) / 2.0
        discrepancy_pct = (discrepancy / ref_price * 100.0) if ref_price > 0 else 0.0

        is_conflict = discrepancy_pct > self.discrepancy_tolerance_pct
        conflicts = 1 if is_conflict else 0

        age_pri = q_pri.get("freshness_seconds", 5.0)
        age_sec = q_sec.get("freshness_seconds", 5.0)
        max_age = max(age_pri, age_sec)

        freshness = "FRESH"
        if max_age > self.staleness_threshold_seconds:
            freshness = "STALE"

        quality = "GOOD"
        if is_conflict:
            quality = "DEGRADED"
            notes = f"Discrepancy detected: yfinance=₹{p_pri:.2f} vs NSE=₹{p_sec:.2f} (diff: ₹{discrepancy:.2f}, {discrepancy_pct:.2f}%). Preferred primary price."
            self._discrepancy_log.append({
                "timestamp": now_iso,
                "symbol": symbol,
                "primary_price": p_pri,
                "secondary_price": p_sec,
                "diff": discrepancy,
                "diff_pct": discrepancy_pct,
            })
        else:
            notes = f"Reconciled successfully. yfinance=₹{p_pri:.2f}, NSE=₹{p_sec:.2f} (diff: {discrepancy_pct:.2f}%)."

        selected_price = p_pri if p_pri > 0 else p_sec

        return ReconciledQuote(
            symbol=symbol,
            price=selected_price,
            primary_price=p_pri,
            secondary_price=p_sec,
            discrepancy=discrepancy,
            discrepancy_pct=discrepancy_pct,
            primary_provider="yfinance",
            secondary_provider="nse_public",
            market_timestamp=q_pri.get("market_timestamp", now_iso),
            ingestion_timestamp=now_iso,
            market_data_age_seconds=max_age,
            quality=quality,
            freshness=freshness,
            sources_count=2,
            conflicts_count=conflicts,
            can_trade=True,
            discrepancy_detected=is_conflict,
            reconciliation_notes=notes,
        )

    def get_data_source_health(self) -> Dict[str, Any]:
        """Return live status dictionary for the Data Source Health Dashboard."""
        return {
            "sources": dict(self._health_status),
            "recent_discrepancies_count": len(self._discrepancy_log),
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
