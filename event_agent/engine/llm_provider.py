# =============================================================================
# event_agent/engine/llm_provider.py — Provider-Agnostic LLM Event Reasoner
# =============================================================================
"""
Provider-agnostic LLM reasoning layer:
LLMProvider (ABC) -> OpenAIProvider, GeminiProvider, ClaudeProvider.
Includes HeuristicEventParser as a 100% deterministic offline fallback.

STRICT INVARIANT:
The LLM generates structured event interpretations and investment theses ONLY.
It NEVER decides position sizing, leverage, exposure, or risk limits.
The Risk Engine remains 100% deterministic.
"""

import json
import logging
import os
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract LLM event reasoning provider."""

    @abstractmethod
    def interpret_event(
        self,
        headline: str,
        description: str = "",
        source: str = "news",
    ) -> Dict[str, Any]:
        """
        Extract structured event classification, company affected, catalyst vs noise,
        expected duration, and investment thesis.
        """
        ...


class HeuristicEventParser(LLMProvider):
    def parse_event(self, headline: str) -> Dict[str, Any]:
        res = self.interpret_event(headline)
        symbol = "NIFTY50"
        hl_lower = headline.lower()
        if "reliance" in hl_lower:
            symbol = "RELIANCE.NS"
        elif "tcs" in hl_lower or "tata consultancy" in hl_lower:
            symbol = "TCS.NS"
        elif "infy" in hl_lower or "infosys" in hl_lower:
            symbol = "INFY.NS"
        elif "hdfc" in hl_lower:
            symbol = "HDFCBANK.NS"

        return {
            "symbol": symbol,
            "sentiment": res.get("impact_direction", "NEUTRAL"),
            "confidence": res.get("confidence", 60.0) / 100.0,
            "thesis": res.get("investment_thesis", ""),
            "category": res.get("event_category", "GENERAL"),
            "raw": res,
        }

    """
    Deterministic, zero-cost offline heuristic parser.
    Guarantees 100% reproducible test suite execution without API keys or network latency.
    """

    def interpret_event(
        self,
        headline: str,
        description: str = "",
        source: str = "news",
    ) -> Dict[str, Any]:
        hl_lower = (headline + " " + description).lower()

        # Classification
        if any(w in hl_lower for w in ["profit up", "surges", "jumps", "beat", "beats", "record profit"]):
            category = "EARNINGS_SURPRISE"
            impact = "POSITIVE"
            cat_noise = "CATALYST"
            duration = "1_3_DAYS"
            confidence = 82.0
            thesis = "Strong quarterly results beat street expectations, driving valuation re-rating."
        elif any(w in hl_lower for w in ["net loss", "drops", "slumps", "miss", "misses", "falls"]):
            category = "EARNINGS_SURPRISE"
            impact = "NEGATIVE"
            cat_noise = "CATALYST"
            duration = "1_3_DAYS"
            confidence = 80.0
            thesis = "Quarterly results missed expectations, leading to target and margin downgrades."
        elif any(w in hl_lower for w in ["order win", "bags order", "secures deal", "wins contract"]):
            category = "ORDER_WIN"
            impact = "POSITIVE"
            cat_noise = "CATALYST"
            duration = "1_2_WEEKS"
            confidence = 78.0
            thesis = "New contract enhances multi-year revenue visibility and order book backlog."
        elif any(w in hl_lower for w in ["sebi", "probe", "notice", "penalty", "fda", "warning letter"]):
            category = "REGULATORY_ACTION"
            impact = "NEGATIVE"
            cat_noise = "CATALYST"
            duration = "MULTI_WEEK"
            confidence = 85.0
            thesis = "Regulatory scrutiny triggers compliance overhang and operational uncertainty."
        elif any(w in hl_lower for w in ["rate cut", "repo cut", "dovish", "inflation cools"]):
            category = "MACRO_POLICY"
            impact = "POSITIVE"
            cat_noise = "CATALYST"
            duration = "MULTI_MONTH"
            confidence = 75.0
            thesis = "Accommodative monetary stance eases corporate cost of borrowing."
        elif any(w in hl_lower for w in ["rate hike", "repo hike", "hawkish", "crude surge"]):
            category = "MACRO_POLICY"
            impact = "NEGATIVE"
            cat_noise = "CATALYST"
            duration = "MULTI_MONTH"
            confidence = 75.0
            thesis = "Tightening monetary liquidity dampens valuation multiples."
        else:
            category = "GENERAL_UPDATE"
            impact = "NEUTRAL"
            cat_noise = "NOISE"
            duration = "INTRADAY"
            confidence = 60.0
            thesis = "Routine financial media headline with negligible structural impact."

        return {
            "provider": "heuristic_offline",
            "headline": headline,
            "event_category": category,
            "impact_direction": impact,
            "catalyst_vs_noise": cat_noise,
            "surprise_vs_priced_in": "SURPRISE" if cat_noise == "CATALYST" else "PRICED_IN",
            "expected_duration": duration,
            "confidence": confidence,
            "investment_thesis": thesis,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class OpenAIProvider(LLMProvider):
    """
    OpenAI-backed structured event reasoner (using gpt-4o-mini).
    Falls back gracefully to HeuristicEventParser if API key is not configured or network fails.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.fallback = HeuristicEventParser()

    def interpret_event(
        self,
        headline: str,
        description: str = "",
        source: str = "news",
    ) -> Dict[str, Any]:
        if not self.api_key:
            return self.fallback.interpret_event(headline, description, source)

        prompt = (
            f"You are a quantitative research analyst evaluating an Indian market headline.\n"
            f"Headline: {headline}\n"
            f"Context: {description}\n"
            f"Respond with JSON containing:\n"
            f"- event_category (EARNINGS_SURPRISE, ORDER_WIN, REGULATORY_ACTION, MACRO_POLICY, GENERAL_UPDATE)\n"
            f"- impact_direction (POSITIVE, NEGATIVE, NEUTRAL)\n"
            f"- catalyst_vs_noise (CATALYST, NOISE)\n"
            f"- surprise_vs_priced_in (SURPRISE, PRICED_IN)\n"
            f"- expected_duration (INTRADAY, 1_3_DAYS, 1_2_WEEKS, MULTI_MONTH)\n"
            f"- confidence (0 to 100)\n"
            f"- investment_thesis (2 sentences maximum)"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }).encode("utf-8")

        try:
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content_str = data["choices"][0]["message"]["content"]
                parsed = json.loads(content_str)
                parsed["provider"] = f"openai_{self.model}"
                parsed["source"] = source
                parsed["timestamp"] = datetime.now(timezone.utc).isoformat()
                return parsed
        except Exception as exc:
            logger.warning(f"OpenAI event interpretation failed ({exc}). Falling back to heuristic.")
            res = self.fallback.interpret_event(headline, description, source)
            res["provider"] = "openai_fallback_heuristic"
            return res
