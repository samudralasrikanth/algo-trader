# =============================================================================
# event_agent/fundamentals/fundamental_normalizer.py — Sector-Aware Normalizer
# =============================================================================
"""
Normalizes raw fundamental accounting metrics into standardized percentile/score scales [0, 100].
Applies sector-specific benchmark envelopes to prevent structural sector biases (e.g.
financials naturally carrying higher financial leverage than IT services).
"""

from typing import Any, Dict, Optional

# Sector reference medians for Nifty 50 equities
SECTOR_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "Financial Services": {
        "pe_median": 18.0,
        "pb_median": 2.2,
        "roce_median": 14.0,
        "roe_median": 15.0,
        "op_margin_median": 22.0,
        "max_acceptable_de": 6.0,  # Deposits & borrowings considered liabilities
    },
    "Information Technology": {
        "pe_median": 28.0,
        "pb_median": 6.5,
        "roce_median": 35.0,
        "roe_median": 28.0,
        "op_margin_median": 24.0,
        "max_acceptable_de": 0.3,
    },
    "Consumer Goods / FMCG": {
        "pe_median": 45.0,
        "pb_median": 10.0,
        "roce_median": 30.0,
        "roe_median": 25.0,
        "op_margin_median": 20.0,
        "max_acceptable_de": 0.5,
    },
    "Automobile": {
        "pe_median": 22.0,
        "pb_median": 3.5,
        "roce_median": 18.0,
        "roe_median": 16.0,
        "op_margin_median": 12.0,
        "max_acceptable_de": 1.0,
    },
    "Energy / Oil & Gas": {
        "pe_median": 14.0,
        "pb_median": 1.8,
        "roce_median": 15.0,
        "roe_median": 14.0,
        "op_margin_median": 14.0,
        "max_acceptable_de": 1.2,
    },
    "Default": {
        "pe_median": 24.0,
        "pb_median": 3.2,
        "roce_median": 18.0,
        "roe_median": 16.0,
        "op_margin_median": 15.0,
        "max_acceptable_de": 1.0,
    },
}


class FundamentalNormalizer:
    """
    Normalizes company metrics against sector-specific reference baselines.
    """

    @classmethod
    def get_sector_benchmarks(cls, sector: str) -> Dict[str, Any]:
        for sec_name, bm in SECTOR_BENCHMARKS.items():
            if sec_name.lower() in sector.lower() or sector.lower() in sec_name.lower():
                return bm
        return SECTOR_BENCHMARKS["Default"]

    @classmethod
    def normalize_valuation(
        cls,
        valuation: Dict[str, float],
        sector: str = "Default",
    ) -> float:
        """
        Normalizes valuation multiples into an attractiveness score (0 to 100).
        Higher score = more attractive / cheaper relative to sector.
        Lower score = expensive / stretched multiples.
        """
        bm = cls.get_sector_benchmarks(sector)
        pe = valuation.get("pe_ratio")
        pb = valuation.get("pb_ratio")

        scores = []
        if pe is not None and pe > 0:
            pe_med = bm["pe_median"]
            # Ratio of median PE to stock PE. If stock PE = 0.5 * median -> score ~ 80.
            # If stock PE = 2.0 * median -> score ~ 20.
            ratio = pe_med / pe
            pe_score = min(100.0, max(0.0, 50.0 + (ratio - 1.0) * 40.0))
            scores.append(pe_score)

        if pb is not None and pb > 0:
            pb_med = bm["pb_median"]
            ratio = pb_med / pb
            pb_score = min(100.0, max(0.0, 50.0 + (ratio - 1.0) * 40.0))
            scores.append(pb_score)

        return round(sum(scores) / len(scores), 2) if scores else 50.0

    @classmethod
    def normalize_profitability_and_quality(
        cls,
        profitability: Dict[str, float],
        leverage: Dict[str, float],
        ownership: Dict[str, float],
        sector: str = "Default",
    ) -> float:
        """
        Computes normalized Quality score (0 to 100).
        High ROCE/ROE, stable margins, low debt, unpledged promoter holdings boost score.
        """
        bm = cls.get_sector_benchmarks(sector)
        components = []

        # 1. ROCE / ROE component (0 to 40 pts)
        roce = profitability.get("roce_pct", profitability.get("roe_pct", bm["roce_median"]))
        roce_med = bm["roce_median"]
        roce_score = min(40.0, max(0.0, (roce / max(1.0, roce_med)) * 25.0))
        components.append(roce_score)

        # 2. Operating margin component (0 to 25 pts)
        op_margin = profitability.get("operating_margin_pct", bm["op_margin_median"])
        op_score = min(25.0, max(0.0, (op_margin / max(1.0, bm["op_margin_median"])) * 15.0))
        components.append(op_score)

        # 3. Leverage health component (0 to 25 pts)
        de = leverage.get("debt_to_equity", 0.5)
        max_de = bm["max_acceptable_de"]
        if de <= 0:
            de_score = 25.0
        elif de <= max_de:
            de_score = 25.0 * (1.0 - (de / (max_de * 1.5)))
        else:
            de_score = max(0.0, 10.0 * (1.0 - (de - max_de) / max_de))
        components.append(de_score)

        # 4. Ownership governance component (0 to 10 pts)
        pledged = ownership.get("pledged_pct", 0.0)
        pledge_score = max(0.0, 10.0 * (1.0 - min(1.0, pledged / 20.0)))
        components.append(pledge_score)

        return round(min(100.0, max(0.0, sum(components))), 2)

    @classmethod
    def normalize_growth(
        cls,
        growth: Dict[str, float],
    ) -> float:
        """
        Computes normalized Growth score (0 to 100).
        """
        rev_growth = growth.get("revenue_growth_yoy", 10.0)
        pat_growth = growth.get("pat_growth_yoy", 10.0)
        cagr = growth.get("cagr_3y_revenue", rev_growth)

        # Base 50 for 10% YoY growth
        rev_score = min(40.0, max(0.0, 20.0 + (rev_growth - 10.0) * 1.2))
        pat_score = min(40.0, max(0.0, 20.0 + (pat_growth - 10.0) * 1.0))
        cagr_score = min(20.0, max(0.0, 10.0 + (cagr - 10.0) * 0.8))

        return round(min(100.0, max(0.0, rev_score + pat_score + cagr_score)), 2)
