# =============================================================================
# event_agent/fundamentals/fundamental_score.py — Deterministic Scoring & Regime
# =============================================================================
"""
Computes deterministic fundamental scores and evaluates both stock-level and
market-wide fundamental regimes without LLM hallucinations.
"""

from typing import Any, Dict, List, Optional
from .fundamental_normalizer import FundamentalNormalizer
from .fundamental_snapshot import FundamentalRegime, FundamentalSnapshot


class FundamentalScoreEngine:
    """
    Computes scores and determines fundamental regime classifications.
    """

    @classmethod
    def score_snapshot(
        cls,
        symbol: str,
        as_of: Any,
        source: str,
        valuation: Dict[str, float],
        profitability: Dict[str, float],
        growth: Dict[str, float],
        leverage: Dict[str, float],
        ownership: Dict[str, float],
        sector: str = "Default",
    ) -> FundamentalSnapshot:
        """
        Calculates all deterministic scores and returns a populated FundamentalSnapshot.
        If source indicates unavailable, returns an unpopulated snapshot.
        """
        if source == "FUNDAMENTALS_UNAVAILABLE" or not valuation and not profitability:
            return FundamentalSnapshot(
                symbol=symbol,
                as_of=as_of,
                source="FUNDAMENTALS_UNAVAILABLE",
                valuation={},
                profitability={},
                growth={},
                leverage={},
                ownership={},
                quality_score=None,
                valuation_score=None,
                growth_score=None,
                balance_sheet_score=None,
                fundamental_regime=FundamentalRegime.INSUFFICIENT_DATA.value,
                freshness="UNAVAILABLE",
            )

        q_score = FundamentalNormalizer.normalize_profitability_and_quality(
            profitability=profitability,
            leverage=leverage,
            ownership=ownership,
            sector=sector,
        )
        v_score = FundamentalNormalizer.normalize_valuation(
            valuation=valuation,
            sector=sector,
        )
        g_score = FundamentalNormalizer.normalize_growth(
            growth=growth,
        )

        # Balance sheet score: combines debt-to-equity and interest coverage
        de = leverage.get("debt_to_equity", 0.5)
        ic = leverage.get("interest_coverage", 5.0)
        bs_de = max(0.0, 50.0 * (1.0 - min(1.0, de / 2.0)))
        bs_ic = min(50.0, max(0.0, (ic / 8.0) * 50.0))
        bs_score = round(bs_de + bs_ic, 2)

        # Stock-level fundamental regime
        stock_regime = cls.classify_stock_regime(
            quality_score=q_score,
            valuation_score=v_score,
            growth_score=g_score,
            debt_to_equity=de,
        )

        return FundamentalSnapshot(
            symbol=symbol,
            as_of=as_of,
            source=source,
            valuation=valuation,
            profitability=profitability,
            growth=growth,
            leverage=leverage,
            ownership=ownership,
            quality_score=q_score,
            valuation_score=v_score,
            growth_score=g_score,
            balance_sheet_score=bs_score,
            fundamental_regime=stock_regime.value,
            freshness="FRESH",
        )

    @classmethod
    def classify_stock_regime(
        cls,
        quality_score: float,
        valuation_score: float,
        growth_score: float,
        debt_to_equity: float,
    ) -> FundamentalRegime:
        """
        Categorizes a single company's fundamental health.
        """
        if debt_to_equity > 2.5 or (quality_score < 30.0 and growth_score < 30.0):
            return FundamentalRegime.STRESSED
        if growth_score < 35.0 and quality_score < 45.0:
            return FundamentalRegime.WEAKENING
        if valuation_score < 30.0 and quality_score >= 65.0:
            return FundamentalRegime.STRETCHED
        if quality_score >= 65.0 and growth_score >= 55.0 and debt_to_equity <= 1.2:
            return FundamentalRegime.HEALTHY
        return FundamentalRegime.MIXED

    @classmethod
    def compute_market_breadth_and_regime(
        cls,
        snapshots: Dict[str, FundamentalSnapshot],
    ) -> Dict[str, Any]:
        """
        Computes NIFTY 50 universe fundamental breadth distribution and market regime.
        """
        available = [s for s in snapshots.values() if s.is_available and s.quality_score is not None]
        total = len(available)

        if total < 10:
            return {
                "total_equities": total,
                "strong_quality_count": 0,
                "improving_growth_count": 0,
                "weak_growth_count": 0,
                "high_valuation_count": 0,
                "low_valuation_count": 0,
                "high_leverage_count": 0,
                "fundamentally_stressed_count": 0,
                "fundamental_regime": FundamentalRegime.INSUFFICIENT_DATA.value,
                "breadth_ratio": 0.0,
            }

        strong_quality = sum(1 for s in available if (s.quality_score or 0) >= 65.0)
        improving_growth = sum(1 for s in available if (s.growth_score or 0) >= 60.0)
        weak_growth = sum(1 for s in available if (s.growth_score or 0) < 40.0)
        high_valuation = sum(1 for s in available if (s.valuation_score or 0) < 35.0)
        low_valuation = sum(1 for s in available if (s.valuation_score or 0) >= 65.0)
        high_leverage = sum(1 for s in available if s.leverage.get("debt_to_equity", 0) > 1.5)
        stressed = sum(1 for s in available if s.fundamental_regime == FundamentalRegime.STRESSED.value)

        # Determine aggregate market fundamental regime
        quality_ratio = strong_quality / total
        stress_ratio = stressed / total
        growth_ratio = improving_growth / total

        if stress_ratio >= 0.25:
            market_regime = FundamentalRegime.STRESSED
        elif quality_ratio >= 0.55 and growth_ratio >= 0.50:
            market_regime = FundamentalRegime.HEALTHY
        elif high_valuation / total >= 0.50 and quality_ratio >= 0.50:
            market_regime = FundamentalRegime.STRETCHED
        elif weak_growth / total >= 0.40:
            market_regime = FundamentalRegime.WEAKENING
        else:
            market_regime = FundamentalRegime.MIXED

        return {
            "total_equities": total,
            "strong_quality_count": strong_quality,
            "improving_growth_count": improving_growth,
            "weak_growth_count": weak_growth,
            "high_valuation_count": high_valuation,
            "low_valuation_count": low_valuation,
            "high_leverage_count": high_leverage,
            "fundamentally_stressed_count": stressed,
            "fundamental_regime": market_regime.value,
            "breadth_ratio": round(quality_ratio, 2),
        }
