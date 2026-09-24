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
    def normalize_leverage(
        cls,
        leverage: Dict[str, float],
        sector: str = "Default",
    ) -> float:
        """
        Computes sector-normalized leverage health score [0 to 100].
        Higher score = healthy, well-capitalized capital structure for the sector.
        Lower score = stressed leverage or excessive financial risk.
        
        Sector awareness:
        - Financial Services / Banks: D/E up to 6.0 is normal due to deposit intermediation.
          A D/E of 3.5-5.0 produces a healthy score (>= 60).
        - IT / FMCG: Asset-light models expected to be debt-free or near-zero debt.
          A D/E of 3.5 produces a distressed score (< 15).
        """
        bm = cls.get_sector_benchmarks(sector)
        de = leverage.get("debt_to_equity", 0.5)
        ic = leverage.get("interest_coverage", 5.0)
        max_de = bm["max_acceptable_de"]

        # DE health component (0 to 70 pts)
        if de <= 0:
            de_score = 70.0
        elif de <= max_de:
            # Scaled gracefully between 70 and 40
            de_score = 70.0 - (de / max_de) * 30.0
        else:
            # Beyond acceptable threshold: rapidly diminishes to 0
            excess_ratio = (de - max_de) / max_de
            de_score = max(0.0, 40.0 * max(0.0, 1.0 - excess_ratio * 0.8))

        # Interest coverage component (0 to 30 pts)
        # For financials, IC is typically lower (2.0-4.0); for IT, IC can be >50
        ic_benchmark = 3.0 if "financial" in sector.lower() or "bank" in sector.lower() else 6.0
        ic_score = min(30.0, max(0.0, (ic / max(1.0, ic_benchmark)) * 20.0))

        return round(min(100.0, max(0.0, de_score + ic_score)), 2)

    @classmethod
    def normalize_profitability(
        cls,
        profitability: Dict[str, float],
        sector: str = "Default",
    ) -> float:
        """
        Computes sector-normalized profitability score [0 to 100].
        Considers sector-specific return hurdles (ROCE/ROE/Operating Margins).
        """
        bm = cls.get_sector_benchmarks(sector)
        roce = profitability.get("roce_pct", profitability.get("roe_pct", bm["roce_median"]))
        op_margin = profitability.get("operating_margin_pct", bm["op_margin_median"])

        roce_med = max(1.0, bm["roce_median"])
        margin_med = max(1.0, bm["op_margin_median"])

        # Return on capital (0 to 60 pts)
        roce_score = min(60.0, max(0.0, (roce / roce_med) * 40.0))
        # Operating margin (0 to 40 pts)
        margin_score = min(40.0, max(0.0, (op_margin / margin_med) * 25.0))

        return round(min(100.0, max(0.0, roce_score + margin_score)), 2)

    @classmethod
    def normalize_quality(
        cls,
        profitability: Dict[str, float],
        leverage: Dict[str, float],
        ownership: Dict[str, float],
        sector: str = "Default",
    ) -> float:
        """
        Computes normalized Quality score (0 to 100).
        High ROCE/ROE, stable margins, healthy sector leverage, unpledged promoter holdings boost score.
        """
        norm_prof = cls.normalize_profitability(profitability, sector=sector)
        norm_lev = cls.normalize_leverage(leverage, sector=sector)

        # Ownership governance component (0 to 15 pts)
        pledged = ownership.get("pledged_pct", 0.0)
        pledge_score = max(0.0, 15.0 * (1.0 - min(1.0, pledged / 20.0)))

        # Weighted aggregate: 50% Profitability, 35% Leverage Health, 15% Governance
        raw_quality = (norm_prof * 0.50) + (norm_lev * 0.35) + pledge_score
        return round(min(100.0, max(0.0, raw_quality)), 2)

    @classmethod
    def normalize_profitability_and_quality(
        cls,
        profitability: Dict[str, float],
        leverage: Dict[str, float],
        ownership: Dict[str, float],
        sector: str = "Default",
    ) -> float:
        """Alias for normalize_quality."""
        return cls.normalize_quality(
            profitability=profitability,
            leverage=leverage,
            ownership=ownership,
            sector=sector,
        )

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

