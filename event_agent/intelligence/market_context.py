# =============================================================================
# event_agent/intelligence/market_context.py — Context, Breadth, Vol & PIT Fundamentals
# =============================================================================
"""
V3.5 Market Context, Market Breadth, Volatility Engine & Point-in-Time Fundamentals.
Synthesizes macro, cross-asset, breadth, and volatility signals into deterministic
context scores. Enforces strict point-in-time availability on fundamental balance sheets.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class BreadthMetrics:
    advancing_stocks: int
    declining_stocks: int
    advance_decline_ratio: float
    new_52w_highs: int
    new_52w_lows: int
    pct_above_50_dma: float
    pct_above_200_dma: float
    sector_breadth_dispersion: float
    breadth_regime: str                # STRONG_BREADTH, NEUTRAL_BREADTH, DIVERGENT_BREADTH, WEAK_BREADTH


@dataclass
class VolatilityMetrics:
    realized_vol_10d: float
    realized_vol_30d: float
    atr_14: float
    intraday_volatility: float
    volatility_percentile: float       # 0.0 to 100.0 (historical rank)
    vix_value: float
    vix_regime: str                    # LOW, NORMAL, HIGH, EXTREME
    stock_beta: float
    sector_volatility: float


@dataclass
class PointInTimeFundamentals:
    symbol: str
    filing_timestamp: str              # When the quarterly/annual report became public
    revenue_growth_yoy: Optional[float]
    eps_growth_yoy: Optional[float]
    ebitda_margin_pct: Optional[float]
    debt_to_equity: Optional[float]
    roe_pct: Optional[float]
    roce_pct: Optional[float]
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    is_pit_valid: bool = True

    def assert_valid_for_prediction(self, prediction_timestamp: str) -> None:
        """Enforces that filing_timestamp <= prediction_timestamp."""
        if self.filing_timestamp > prediction_timestamp:
            raise ValueError(
                f"Lookahead bias detected! Fundamentals filed at {self.filing_timestamp} "
                f"cannot be used in prediction made at {prediction_timestamp}."
            )


@dataclass
class MarketContextScore:
    overall_context_score: float       # 0.0 (strong headwind) to 100.0 (strong tailwind)
    macro_regime_label: str            # RISK_ON, NEUTRAL, RISK_OFF, CRISIS
    breadth: BreadthMetrics
    volatility: VolatilityMetrics
    stock_vol_adjustment_factor: float # e.g. 1.25x wider stop/target in high vol
    global_context_score: float
    fii_dii_net_sentiment: str         # NET_BUYING, BALANCED, NET_SELLING


class MarketContextEngine:
    """
    Computes unified market context, breadth, and volatility conditioning.
    """

    @classmethod
    def classify_vix_regime(cls, vix: float) -> str:
        if vix < 13.0:
            return "LOW"
        elif vix < 18.0:
            return "NORMAL"
        elif vix < 24.0:
            return "HIGH"
        else:
            return "EXTREME"

    @classmethod
    def compute_volatility(
        cls,
        price_history: List[float],
        high_history: Optional[List[float]] = None,
        low_history: Optional[List[float]] = None,
        vix_value: float = 15.2,
        stock_beta: float = 1.05,
        sector_vol: float = 0.018,
    ) -> VolatilityMetrics:
        """
        Compute comprehensive volatility metrics from price arrays.
        """
        if not price_history or len(price_history) < 5:
            # Fallback values
            return VolatilityMetrics(
                realized_vol_10d=0.015,
                realized_vol_30d=0.016,
                atr_14=25.0,
                intraday_volatility=0.012,
                volatility_percentile=50.0,
                vix_value=vix_value,
                vix_regime=cls.classify_vix_regime(vix_value),
                stock_beta=stock_beta,
                sector_volatility=sector_vol,
            )

        rets = np.diff(price_history) / price_history[:-1]
        vol_10 = float(np.std(rets[-10:])) if len(rets) >= 10 else float(np.std(rets))
        vol_30 = float(np.std(rets[-30:])) if len(rets) >= 30 else float(np.std(rets))

        # ATR calculation if highs/lows provided
        if high_history and low_history and len(high_history) == len(price_history):
            trs = [
                max(h - l, abs(h - p), abs(l - p))
                for h, l, p in zip(high_history[1:], low_history[1:], price_history[:-1])
            ]
            atr = float(np.mean(trs[-14:])) if len(trs) >= 14 else float(np.mean(trs))
        else:
            atr = price_history[-1] * vol_10 * 1.5

        # Intraday vol approximation
        intraday_vol = vol_10 * 0.7

        # Percentile relative to normal 1.5% daily volatility
        pct = min(100.0, max(0.0, (vol_30 / 0.03) * 100.0))
        vix_reg = cls.classify_vix_regime(vix_value)

        return VolatilityMetrics(
            realized_vol_10d=round(vol_10, 5),
            realized_vol_30d=round(vol_30, 5),
            atr_14=round(atr, 2),
            intraday_volatility=round(intraday_vol, 5),
            volatility_percentile=round(pct, 1),
            vix_value=vix_value,
            vix_regime=vix_reg,
            stock_beta=round(stock_beta, 2),
            sector_volatility=round(sector_vol, 5),
        )

    @classmethod
    def compute_breadth(
        cls,
        advances: int = 28,
        declines: int = 22,
        new_highs: int = 8,
        new_lows: int = 2,
        pct_above_50d: float = 64.0,
        pct_above_200d: float = 72.0,
        sector_dispersion: float = 0.14,
    ) -> BreadthMetrics:
        """
        Compute advance/decline and moving average participation.
        """
        ad_ratio = advances / max(1, declines)

        if ad_ratio >= 1.5 and pct_above_50d >= 60.0:
            regime = "STRONG_BREADTH"
        elif ad_ratio <= 0.67 or pct_above_50d <= 40.0:
            regime = "WEAK_BREADTH"
        elif abs(ad_ratio - 1.0) <= 0.3:
            regime = "NEUTRAL_BREADTH"
        else:
            regime = "DIVERGENT_BREADTH"

        return BreadthMetrics(
            advancing_stocks=advances,
            declining_stocks=declines,
            advance_decline_ratio=round(ad_ratio, 2),
            new_52w_highs=new_highs,
            new_52w_lows=new_lows,
            pct_above_50_dma=pct_above_50d,
            pct_above_200_dma=pct_above_200d,
            sector_breadth_dispersion=sector_dispersion,
            breadth_regime=regime,
        )

    @classmethod
    def evaluate_market_context(
        cls,
        symbol: str,
        price_history: List[float],
        vix_value: float = 14.8,
        nifty_return_1d: float = 0.003,
        banknifty_return_1d: float = 0.004,
        usd_inr_change: float = -0.05,
        crude_oil_change: float = -0.8,
        fii_net_crores: float = 1250.0,
        dii_net_crores: float = 850.0,
        advances: int = 30,
        declines: int = 20,
    ) -> MarketContextScore:
        """
        Compute holistic Market Context Score (0 to 100) and volatility scaling.
        """
        vol = cls.compute_volatility(price_history, vix_value=vix_value)
        breadth = cls.compute_breadth(advances=advances, declines=declines)

        score = 50.0

        # Nifty & Bank Nifty contribution
        score += (nifty_return_1d * 800.0)
        score += (banknifty_return_1d * 400.0)

        # Breadth contribution
        if breadth.breadth_regime == "STRONG_BREADTH":
            score += 8.0
        elif breadth.breadth_regime == "WEAK_BREADTH":
            score -= 10.0

        # FII / DII flows
        net_flow = fii_net_crores + dii_net_crores
        if net_flow > 1000.0:
            score += 6.0
            fii_sentiment = "NET_BUYING"
        elif net_flow < -1000.0:
            score -= 8.0
            fii_sentiment = "NET_SELLING"
        else:
            fii_sentiment = "BALANCED"

        # Macro headwinds (USDINR spiking or Crude surging hurts Indian equities)
        if crude_oil_change > 2.0:
            score -= 4.0
        elif crude_oil_change < -2.0:
            score += 3.0

        if usd_inr_change > 0.3:
            score -= 4.0

        # Volatility penalty
        if vol.vix_regime == "EXTREME":
            score -= 15.0
            macro_label = "CRISIS"
            vol_adj = 1.6
        elif vol.vix_regime == "HIGH":
            score -= 7.0
            macro_label = "RISK_OFF"
            vol_adj = 1.3
        elif score >= 60.0:
            macro_label = "RISK_ON"
            vol_adj = 1.0
        elif score <= 40.0:
            macro_label = "RISK_OFF"
            vol_adj = 1.15
        else:
            macro_label = "NEUTRAL"
            vol_adj = 1.0

        final_score = max(5.0, min(95.0, score))

        return MarketContextScore(
            overall_context_score=round(final_score, 1),
            macro_regime_label=macro_label,
            breadth=breadth,
            volatility=vol,
            stock_vol_adjustment_factor=vol_adj,
            global_context_score=round(50.0 + (crude_oil_change * -2.0), 1),
            fii_dii_net_sentiment=fii_sentiment,
        )
