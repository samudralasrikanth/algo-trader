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
import time
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

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


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter-backed structured event reasoner.
    Works with any OpenRouter model (e.g. openai/gpt-4o-mini, meta-llama/llama-3.3-70b-instruct, etc.)
    Falls back gracefully to HeuristicEventParser if API key is not configured, rate-limited, or network fails.
    Captures complete auditable execution telemetry: request_id, latency_ms, tokens, and inference_mode.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "openai/gpt-4o-mini"):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENROUTER_MODEL", model)
        self.fallback = HeuristicEventParser()

    def ping_health(self) -> Dict[str, Any]:
        """Performs a lightweight connectivity & credential verification test."""
        if not self.api_key:
            return {
                "provider": "openrouter",
                "configured": False,
                "status": "NOT_CONFIGURED",
                "model": self.model,
                "last_success": None,
                "last_failure": "OPENROUTER_API_KEY is not configured",
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/samudralasrikanth/algo-trader",
            "X-Title": "NEXUS Nifty 50 Event Agent",
        }
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": "PING"}],
            "max_tokens": 5,
        }).encode("utf-8")

        start_t = time.perf_counter()
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                data = json.loads(resp.read().decode("utf-8"))
                usage = data.get("usage", {})
                return {
                    "status": "SUCCESS",
                    "provider": "openrouter",
                    "configured": True,
                    "model": self.model,
                    "request_id": data.get("id"),
                    "latency_ms": latency_ms,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "last_success": datetime.now(timezone.utc).isoformat(),
                    "last_failure": None,
                }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            return {
                "status": "FAILED",
                "provider": "openrouter",
                "configured": True,
                "model": self.model,
                "request_id": None,
                "latency_ms": latency_ms,
                "error_reason": str(exc),
                "last_success": None,
                "last_failure": datetime.now(timezone.utc).isoformat(),
            }

    def interpret_event(
        self,
        headline: str,
        description: str = "",
        source: str = "news",
    ) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc).isoformat()
        if not self.api_key:
            res = self.fallback.interpret_event(headline, description, source)
            res["provider"] = "heuristic_baseline"
            res["inference_mode"] = "HEURISTIC_FALLBACK"
            res["ai"] = {
                "provider": "openrouter",
                "model": self.model,
                "request_id": None,
                "latency_ms": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "status": "NOT_CONFIGURED",
                "inference_mode": "HEURISTIC_FALLBACK",
                "error_reason": "OPENROUTER_API_KEY environment variable not configured",
                "timestamp": now_utc,
            }
            return res

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
            "HTTP-Referer": "https://github.com/samudralasrikanth/algo-trader",
            "X-Title": "NEXUS Nifty 50 Event Agent",
        }
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }).encode("utf-8")

        start_t = time.perf_counter()
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                data = json.loads(resp.read().decode("utf-8"))
                content_str = data["choices"][0]["message"]["content"]
                parsed = json.loads(content_str)
                usage = data.get("usage", {})
                req_id = data.get("id")
                parsed["provider"] = f"openrouter_{self.model}"
                parsed["source"] = source
                parsed["timestamp"] = now_utc
                parsed["inference_mode"] = "OPENROUTER_LIVE"
                parsed["ai"] = {
                    "provider": "openrouter",
                    "model": self.model,
                    "request_id": req_id,
                    "latency_ms": latency_ms,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "status": "SUCCESS",
                    "inference_mode": "OPENROUTER_LIVE",
                    "timestamp": now_utc,
                }
                return parsed
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            logger.warning(f"OpenRouter event interpretation failed ({exc}). Falling back to heuristic baseline.")
            res = self.fallback.interpret_event(headline, description, source)
            res["provider"] = "heuristic_fallback"
            res["inference_mode"] = "HEURISTIC_FALLBACK"
            res["ai"] = {
                "provider": "openrouter",
                "model": self.model,
                "request_id": None,
                "latency_ms": latency_ms,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "status": "FAILED",
                "inference_mode": "HEURISTIC_FALLBACK",
                "error_reason": str(exc),
                "timestamp": now_utc,
            }
            return res


def get_default_llm_provider() -> LLMProvider:
    """
    Returns the best available LLM provider based on environment configuration:
    1. OpenRouter if OPENROUTER_API_KEY is configured (or key starts with sk-or-)
    2. OpenAI if OPENAI_API_KEY is configured
    3. HeuristicEventParser (deterministic offline baseline) as default
    """
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if openrouter_key:
        return OpenRouterProvider(api_key=openrouter_key)
    elif openai_key:
        if openai_key.startswith("sk-or-"):
            return OpenRouterProvider(api_key=openai_key)
        return OpenAIProvider(api_key=openai_key)
    else:
        return HeuristicEventParser()
