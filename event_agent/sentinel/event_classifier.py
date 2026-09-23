# =============================================================================
# event_agent/sentinel/event_classifier.py — 19-Category Deterministic Event Classifier
# =============================================================================
"""
V4.2.1 Deterministic Event Classifier:
Classifies raw financial headlines and events into 19 standardized categories:
  FOMC, RBI, ECB, BOJ, INFLATION, EMPLOYMENT, GDP, INTEREST_RATE, BOND_YIELD,
  CURRENCY, COMMODITY, GEOPOLITICAL, GLOBAL_EQUITY, INDIA_MACRO, CORPORATE,
  EARNINGS, REGULATORY, BLACK_SWAN, MARKET_SHOCK.
Extracts monetary policy actions, basis points, and corporate earnings surprises.
"""

import re
from typing import Any, Dict, Optional, Tuple

from .models import EventCategory


class EventClassifier:
    """
    Deterministic rule-based classification engine.
    Zero LLM dependency to ensure fast, consistent, and cost-free tagging.
    """

    @classmethod
    def classify(
        cls,
        title: str,
        description: str = "",
        source: str = "",
    ) -> Tuple[EventCategory, Dict[str, Any]]:
        """
        Classify an event by analyzing title and content.
        Returns the canonical EventCategory and structured extracted metadata.
        """
        text = f"{title} {description} {source}".lower()
        extracted: Dict[str, Any] = {}

        # 1. MARKET_SHOCK
        if any(w in text for w in ["market shock", "circuit breaker", "flash crash", "trading halted across market", "velocity dislocated"]):
            return EventCategory.MARKET_SHOCK, extracted

        # 2. Central Banks (Specific Authorities)
        if any(w in text for w in ["fomc", "federal reserve", "fed rate", "powell", "fed raises", "fed cuts", "fed hikes"]):
            cls._extract_rate_info(text, extracted)
            return EventCategory.FOMC, extracted

        if any(w in text for w in ["rbi", "reserve bank of india", "mpc", "shaktikanta", "repo rate"]):
            cls._extract_rate_info(text, extracted)
            return EventCategory.RBI, extracted

        if any(w in text for w in ["ecb", "european central bank", "lagarde"]):
            cls._extract_rate_info(text, extracted)
            return EventCategory.ECB, extracted

        if any(w in text for w in ["boj", "bank of japan", "ueda"]):
            cls._extract_rate_info(text, extracted)
            return EventCategory.BOJ, extracted

        # 3. Macro Indicators
        if any(w in text for w in ["india macro", "budget", "fiscal deficit", "fii flows", "dii flows", "gst collection", "monsoon", "india wholesale", "wpi"]):
            return EventCategory.INDIA_MACRO, extracted

        if any(w in text for w in ["inflation", "cpi", "consumer price index", "wholesale price"]):
            cls._extract_inflation_info(text, extracted)
            return EventCategory.INFLATION, extracted

        if any(w in text for w in ["non-farm payroll", "nfp", "unemployment rate", "jobless claims", "employment report", "jobs report"]):
            return EventCategory.EMPLOYMENT, extracted

        if any(w in text for w in ["gdp", "gross domestic product", "economic growth rate"]):
            return EventCategory.GDP, extracted

        if any(w in text for w in ["interest rate", "rate hike", "rate cut", "basis points", "monetary policy", "policy rate", "tightening", "rate tightening"]):
            cls._extract_rate_info(text, extracted)
            return EventCategory.INTEREST_RATE, extracted

        if any(w in text for w in ["treasury yield", "10-year yield", "10y yield", "bond yield", "sovereign yield"]):
            return EventCategory.BOND_YIELD, extracted

        if any(w in text for w in ["usdinr", "rupee", "dollar index", "dxy", "forex", "eurusd", "usdjpy", "currency"]):
            return EventCategory.CURRENCY, extracted

        if any(w in text for w in ["crude oil", "brent", "wti", "gold price", "silver price", "copper", "natural gas", "comex"]):
            return EventCategory.COMMODITY, extracted

        if any(w in text for w in ["war", "sanctions", "geopolitic", "missile", "military strike", "tariff", "trade war", "tensions", "airstrike", "airstrikes", "conflict"]):
            return EventCategory.GEOPOLITICAL, extracted

        if any(w in text for w in ["s&p 500", "nasdaq", "dow jones", "nikkei", "hang seng", "dax", "ftse", "global markets"]):
            return EventCategory.GLOBAL_EQUITY, extracted

        if any(w in text for w in ["india macro", "budget", "fiscal deficit", "fii flows", "dii flows", "gst collection", "monsoon"]):
            return EventCategory.INDIA_MACRO, extracted

        if any(w in text for w in ["quarterly results", "q1", "q2", "q3", "q4", "net profit", "revenue up", "revenue down", "earnings"]):
            return EventCategory.EARNINGS, extracted

        if any(w in text for w in ["sebi", "sec", "doj", "rbi notice", "probe", "regulatory action", "penalty"]):
            return EventCategory.REGULATORY, extracted

        if any(w in text for w in ["black swan", "systemic collapse", "bank run", "default on sovereign", "cyber attack", "sovereign debt settlement", "unprecedented cyber"]):
            return EventCategory.BLACK_SWAN, extracted

        # Corporate / general update fallback
        return EventCategory.CORPORATE, extracted

    @classmethod
    def _extract_rate_info(cls, text: str, out: Dict[str, Any]) -> None:
        """Extract rate action (HIKE/CUT/HOLD) and basis points."""
        if any(w in text for w in ["hikes", "raises", "hiked", "raised", "hike"]):
            out["rate_decision_action"] = "HIKE"
        elif any(w in text for w in ["cuts", "cut", "lowers", "lowered", "easing"]):
            out["rate_decision_action"] = "CUT"
        elif any(w in text for w in ["holds", "pause", "paused", "unchanged", "steady"]):
            out["rate_decision_action"] = "HOLD"

        # Regex for basis points: e.g. "25 bps", "50 basis points", "0.25%"
        m = re.search(r"(\d+)\s*(?:bps|basis points)", text)
        if m:
            bps = float(m.group(1))
            if out.get("rate_decision_action") == "CUT":
                bps = -bps
            out["rate_change_bps"] = bps
        else:
            m2 = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m2 and ("rate" in text or "repo" in text):
                val = float(m2.group(1))
                if val <= 5.0:
                    out["rate_change_pct"] = -val if out.get("rate_decision_action") == "CUT" else val

    @classmethod
    def _extract_inflation_info(cls, text: str, out: Dict[str, Any]) -> None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if m:
            out["inflation_reading_pct"] = float(m.group(1))
