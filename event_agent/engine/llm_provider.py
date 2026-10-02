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
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import re
import threading
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


class OpenRouterStatus(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    INFERENCE_SUCCESS = "INFERENCE_SUCCESS"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    CREDIT_EXHAUSTED = "CREDIT_EXHAUSTED"
    UNAVAILABLE = "UNAVAILABLE"


def sanitize_secret_error(error_str: Any) -> str:
    """Sanitizes raw provider errors to ensure no API keys or tokens are leaked into telemetry or logs."""
    if not error_str:
        return ""
    s = str(error_str)
    s = re.sub(r"sk-[a-zA-Z0-9_\-]{16,}", "[REDACTED_API_KEY]", s)
    s = re.sub(r"gsk_[a-zA-Z0-9_\-]{20,}", "[REDACTED_API_KEY]", s)
    s = re.sub(r"AIza[a-zA-Z0-9_\-]{20,}", "[REDACTED_API_KEY]", s)
    s = re.sub(r"AQ\.[a-zA-Z0-9_\-]{20,}", "[REDACTED_API_KEY]", s)
    s = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]{16,}", "Bearer [REDACTED_TOKEN]", s, flags=re.IGNORECASE)
    return s


class OpenRouterMetricsTracker:
    """Tracks operational availability vs model quality metrics for institutional audits."""
    _lock = threading.Lock()
    _metrics = {
        "AI_DECISION_ATTEMPTS": 0,
        "AI_SUCCESSFUL_DECISIONS": 0,
        "AI_UNAVAILABLE_DECISIONS": 0,
        "AI_CREDIT_EXHAUSTED": 0,
        "AI_RATE_LIMITED": 0,
        "AI_INFERENCE_FAILED": 0,
    }

    @classmethod
    def record_decision(cls, status: str):
        with cls._lock:
            cls._metrics["AI_DECISION_ATTEMPTS"] += 1
            st = str(status).upper()
            if st in ("INFERENCE_SUCCESS", "SUCCESS"):
                cls._metrics["AI_SUCCESSFUL_DECISIONS"] += 1
            else:
                cls._metrics["AI_UNAVAILABLE_DECISIONS"] += 1
                if st == "CREDIT_EXHAUSTED":
                    cls._metrics["AI_CREDIT_EXHAUSTED"] += 1
                elif st == "RATE_LIMITED":
                    cls._metrics["AI_RATE_LIMITED"] += 1
                else:
                    cls._metrics["AI_INFERENCE_FAILED"] += 1

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        with cls._lock:
            m = dict(cls._metrics)
            attempts = m["AI_DECISION_ATTEMPTS"]
            m["AI_AVAILABILITY_PCT"] = round((m["AI_SUCCESSFUL_DECISIONS"] / attempts * 100.0), 2) if attempts > 0 else 100.0
            return m

    @classmethod
    def reset(cls):
        with cls._lock:
            for k in cls._metrics:
                cls._metrics[k] = 0


class OpenRouterProvider(LLMProvider):
    """
    Structured event reasoner supporting Groq, Google Gemini, and OpenRouter OpenAI-compatible endpoints.
    Supports resilient multi-provider failover chain.
    Captures complete auditable execution telemetry: request_id, latency_ms, tokens, and inference_mode.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        groq_key = os.environ.get("GROQ_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        openrouter_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        provider_pref = os.environ.get("LLM_PROVIDER", "").strip().lower()

        # Build failover candidate providers
        self.providers_chain: List[Dict[str, Any]] = []

        if groq_key:
            self.providers_chain.append({
                "type": "groq",
                "name": "groq",
                "key": groq_key,
                "endpoint": "https://api.groq.com/openai/v1/chat/completions",
                "model": model if (provider_pref == "groq" and model) else os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
            })
        if gemini_key:
            self.providers_chain.append({
                "type": "gemini",
                "name": "gemini",
                "key": gemini_key,
                "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                "model": model if (provider_pref == "gemini" and model) else os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            })
        if openrouter_key:
            self.providers_chain.append({
                "type": "openrouter",
                "name": "openrouter",
                "key": openrouter_key,
                "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                "model": model if (provider_pref == "openrouter" and model) else os.environ.get("OPENROUTER_MODEL", "openrouter/free"),
            })

        if api_key is not None:
            if not api_key:
                self.providers_chain = []
                self.api_key = None
            else:
                if api_key.startswith("gsk_"):
                    ptype = "groq"
                    pend = "https://api.groq.com/openai/v1/chat/completions"
                    pm = model or os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
                elif api_key.startswith("AQ.") or api_key.startswith("AIza"):
                    ptype = "gemini"
                    pend = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                    pm = model or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
                else:
                    ptype = "openrouter"
                    pend = "https://openrouter.ai/api/v1/chat/completions"
                    pm = model or os.environ.get("OPENROUTER_MODEL", "openrouter/free")
                custom_cfg = {"type": ptype, "name": ptype, "key": api_key, "endpoint": pend, "model": pm}
                self.providers_chain = [custom_cfg]
        elif provider_pref:
            self.providers_chain.sort(key=lambda c: 0 if c["type"] == provider_pref else 1)

        # Primary provider attributes for backward compatibility
        if self.providers_chain:
            primary = self.providers_chain[0]
            self.api_key = primary["key"]
            self.provider_type = primary["type"]
            self.provider_name = primary["name"]
            self.endpoint_url = primary["endpoint"]
            self.model = primary["model"]
        else:
            self.api_key = None
            self.provider_type = "none"
            self.provider_name = "none"
            self.endpoint_url = "https://openrouter.ai/api/v1/chat/completions"
            self.model = model or os.environ.get("OPENROUTER_MODEL", "openrouter/free")

        self.fallback = HeuristicEventParser()

    @classmethod
    def default_telemetry(cls, model: str = "openai/gpt-4o-mini") -> Dict[str, Any]:
        """Returns baseline unexecuted OpenRouter telemetry adhering to canonical taxonomy."""
        return {
            "provider": "openrouter",
            "model": model,
            "status": "NOT_TESTED",
            "inference_mode": "NOT_EXECUTED",
            "request_id": None,
            "latency_ms": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "error_reason": None,
            "timestamp": None,
        }

    def check_runtime_connection(self) -> Dict[str, Any]:
        return self.ping_health()

    def ping_health(self) -> Dict[str, Any]:
        """Performs a lightweight connectivity & credential verification test across candidates."""
        if not self.providers_chain or not self.api_key:
            return {
                "provider": self.provider_name,
                "configured": False,
                "credential_fingerprint": None,
                "status": "NOT_CONFIGURED",
                "inference_mode": "UNAVAILABLE",
                "model": self.model,
                "request_id": None,
                "latency_ms": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "last_success": None,
                "last_failure": f"{self.provider_name.upper()}_API_KEY is not configured",
            }

        last_fail_res = None
        for cand_idx, cand in enumerate(list(self.providers_chain)):
            cand_key = cand["key"]
            cand_name = cand["name"]
            cand_type = cand["type"]
            cand_endpoint = cand["endpoint"]
            cand_model = cand["model"]
            fingerprint = f"SHA256:{hashlib.sha256(cand_key.encode()).hexdigest()[:16]}" if cand_key else None

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cand_key}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NEXUS/1.0",
            }
            if cand_type == "openrouter":
                headers["HTTP-Referer"] = "https://github.com/samudralasrikanth/algo-trader"
                headers["X-Title"] = "NEXUS Nifty 50 Event Agent"

            body = json.dumps({
                "model": cand_model,
                "messages": [{"role": "user", "content": "PING"}],
                "max_tokens": 5,
            }).encode("utf-8")

            start_t = time.perf_counter()
            try:
                req = urllib.request.Request(cand_endpoint, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    latency_ms = int((time.perf_counter() - start_t) * 1000)
                    data = json.loads(resp.read().decode("utf-8"))
                    usage = data.get("usage", {})
                    in_tok = usage.get("prompt_tokens", 0)
                    out_tok = usage.get("completion_tokens", 0)
                    tot_tok = usage.get("total_tokens", 0)
                    cost = 0.0 if cand_type in ("gemini", "groq") else (in_tok * 0.15 + out_tok * 0.60) / 1_000_000.0

                    if cand_idx > 0:
                        logger.info(f"Promoting working provider {cand_name} to head of failover chain.")
                        self.providers_chain.insert(0, self.providers_chain.pop(cand_idx))
                        self.api_key = cand_key
                        self.provider_type = cand_type
                        self.provider_name = cand_name
                        self.endpoint_url = cand_endpoint
                        self.model = cand_model

                    return {
                        "status": "SUCCESS",
                        "substatus": "AUTHENTICATED",
                        "provider": cand_name,
                        "configured": True,
                        "credential_fingerprint": fingerprint,
                        "inference_mode": f"{cand_name.upper()}_LIVE",
                        "model": data.get("model", cand_model),
                        "request_id": data.get("id"),
                        "latency_ms": latency_ms,
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "total_tokens": tot_tok,
                        "cost_usd": round(cost, 6),
                        "last_success": datetime.now(timezone.utc).isoformat(),
                        "last_failure": None,
                    }
            except Exception as exc:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                status_code = getattr(exc, "code", 500) if hasattr(exc, "code") else 500
                raw_err = str(exc)
                if status_code in (401, 403):
                    err_substatus = "INVALID_KEY"
                elif status_code == 402 or "402" in raw_err or "Payment Required" in raw_err:
                    err_substatus = "CREDIT_EXHAUSTED"
                elif status_code == 429:
                    err_substatus = "RATE_LIMITED"
                else:
                    err_substatus = "UNREACHABLE"

                last_fail_res = {
                    "status": "FAILED",
                    "substatus": err_substatus,
                    "provider": cand_name,
                    "configured": True,
                    "credential_fingerprint": fingerprint,
                    "inference_mode": "UNAVAILABLE",
                    "model": cand_model,
                    "request_id": None,
                    "latency_ms": latency_ms,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "error_reason": sanitize_secret_error(raw_err),
                    "last_success": None,
                    "last_failure": datetime.now(timezone.utc).isoformat(),
                }
                if len(self.providers_chain) > 1:
                    logger.warning(f"Provider {cand_name} ping check failed ({last_fail_res['error_reason']}). Checking next provider...")

        return last_fail_res

    def generate_decision_thesis(
        self,
        agent_id: str,
        symbol: str,
        stock_data: Dict[str, Any],
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes real decision-time inference for an agent.
        Logs verified execution telemetry directly to SQLite ledger.
        Supports multi-provider failover chain.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        if not self.providers_chain or not self.api_key:
            OpenRouterMetricsTracker.record_decision(OpenRouterStatus.UNAVAILABLE.value)
            return {
                "status": OpenRouterStatus.UNAVAILABLE.value,
                "ai_status": OpenRouterStatus.UNAVAILABLE.value,
                "error": f"{self.provider_name.upper()}_API_KEY environment variable not configured",
                "direction": "NO_TRADE",
                "expected_move_pct": 0.0,
                "horizon": "1D",
                "confidence": 0.0,
                "catalysts": [],
                "invalidating_conditions": [f"{self.provider_name.upper()}_API_KEY unconfigured"],
                "reasoning": f"AI intelligence unavailable: {self.provider_name.upper()}_API_KEY not configured.",
                "ai_request_id": None,
                "model": self.model,
                "actual_provider": "none",
                "decision_mode": "AI_UNAVAILABLE",
                "decision_model": f"{self.provider_name.upper()}:{self.model}",
                "model_provider": self.provider_name,
                "model_version": self.model,
                "fallback_reason": f"{self.provider_name.upper()}_API_KEY unconfigured",
                "evaluation_status": "EXCLUDED_FROM_ACCURACY",
            }

        ctx = market_context or {}
        news_items = stock_data.get("catalysts", [])[:3] or ["Consolidation in line with sector"]
        base_p = stock_data.get("base_price", 0.0)

        prompt = (
            f"You are the Decision-Time AI for Autonomous Trading Agent {agent_id}.\n"
            f"Asset: {symbol} (Current Price: ₹{base_p:,.2f})\n"
            f"Recent News / Catalysts: {json.dumps(news_items)}\n"
            f"Market Context: NIFTY Regime={ctx.get('regime', 'NORMAL')}, VIX={ctx.get('vix', 'NORMAL')}, USDINR={ctx.get('usdinr', 'FLAT')}\n"
            f"Agent Philosophy: Evaluate catalyst vs macro headwinds. Produce a calibrated market thesis.\n"
            f"Respond strictly in valid JSON with these keys:\n"
            f"- direction: 'BULLISH' or 'BEARISH'\n"
            f"- expected_move_pct: float between -10.0 and +10.0\n"
            f"- horizon: '1D', '3D', or '7D'\n"
            f"- confidence: float between 35.0 and 90.0\n"
            f"- catalysts: list of 1 to 3 specific driving catalysts\n"
            f"- invalidating_conditions: list of 1 to 3 specific conditions that cancel this thesis\n"
            f"- reasoning: concise 2-sentence economic thesis"
        )

        last_error = ""
        last_status = OpenRouterStatus.INFERENCE_FAILED.value
        last_provider_name = self.provider_name
        last_model = self.model

        for cand_idx, cand in enumerate(list(self.providers_chain)):
            cand_key = cand["key"]
            cand_type = cand["type"]
            cand_name = cand["name"]
            cand_endpoint = cand["endpoint"]
            cand_model = cand["model"]
            last_provider_name = cand_name
            last_model = cand_model

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cand_key}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NEXUS/1.0",
            }
            if cand_type == "openrouter":
                headers["HTTP-Referer"] = "https://github.com/samudralasrikanth/algo-trader"
                headers["X-Title"] = "NEXUS Decision Engine"

            if cand_type == "openrouter":
                default_tokens = "1500"
            else:
                default_tokens = "600"
            max_tokens = int(os.environ.get(f"{cand_name.upper()}_MAX_TOKENS") or os.environ.get("LLM_MAX_TOKENS") or default_tokens)

            req_payload: Dict[str, Any] = {
                "model": cand_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
            if cand_type not in ("gemini", "openrouter"):
                req_payload["response_format"] = {"type": "json_object"}

            body_str = json.dumps(req_payload)
            body = body_str.encode("utf-8")
            in_hash = hashlib.sha256(body).hexdigest()

            max_attempts = 2 if len(self.providers_chain) > 1 else 4
            for attempt in range(max_attempts):
                start_t = time.perf_counter()
                try:
                    req = urllib.request.Request(cand_endpoint, data=body, headers=headers)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        latency_ms = int((time.perf_counter() - start_t) * 1000)
                        raw_bytes = resp.read()
                        out_hash = hashlib.sha256(raw_bytes).hexdigest()
                        data = json.loads(raw_bytes.decode("utf-8"))
                        content_str = data["choices"][0]["message"].get("content") or ""

                        clean_content = content_str.strip()
                        if clean_content.startswith("```"):
                            clean_content = re.sub(r"^```[a-zA-Z]*\n?", "", clean_content)
                            clean_content = re.sub(r"\n?```$", "", clean_content).strip()
                        if "{" in clean_content and "}" in clean_content:
                            clean_content = clean_content[clean_content.find("{"):clean_content.rfind("}")+1]
                        parsed = json.loads(clean_content)

                        usage = data.get("usage", {})
                        in_tok = usage.get("prompt_tokens", 0)
                        out_tok = usage.get("completion_tokens", 0)
                        tot_tok = usage.get("total_tokens", 0)
                        cost = 0.0 if cand_type in ("gemini", "groq") else (in_tok * 0.15 + out_tok * 0.60) / 1_000_000.0
                        req_id = data.get("id") or f"{cand_name}_{int(time.time()*1000)}"
                        act_model = data.get("model", cand_model)

                        try:
                            from event_agent.storage.ledger import record_ai_telemetry
                            record_ai_telemetry({
                                "ai_request_id": req_id,
                                "market_date": datetime.now().strftime("%Y-%m-%d"),
                                "call_type": "DECISION_THESIS",
                                "agent_id": agent_id,
                                "symbol": symbol,
                                "model": act_model,
                                "model_provider": cand_name,
                                "input_hash": in_hash,
                                "output_hash": out_hash,
                                "input_tokens": in_tok,
                                "output_tokens": out_tok,
                                "total_tokens": tot_tok,
                                "cost_usd": cost,
                                "latency_ms": latency_ms,
                                "http_status": 200,
                                "status": "SUCCESS",
                            })
                        except Exception as db_err:
                            logger.debug(f"Telemetry logging error: {db_err}")

                        OpenRouterMetricsTracker.record_decision(OpenRouterStatus.INFERENCE_SUCCESS.value)
                        parsed["status"] = OpenRouterStatus.INFERENCE_SUCCESS.value
                        parsed["ai_status"] = OpenRouterStatus.INFERENCE_SUCCESS.value
                        parsed["ai_request_id"] = req_id
                        parsed["model"] = act_model
                        parsed["actual_provider"] = cand_name
                        parsed["latency_ms"] = latency_ms
                        parsed["tokens"] = tot_tok
                        parsed["decision_mode"] = "AI_INFERENCE"
                        parsed["decision_model"] = f"{cand_name.upper()}:{act_model}"
                        parsed["model_provider"] = cand_name
                        parsed["model_version"] = act_model
                        parsed["fallback_reason"] = None
                        parsed["evaluation_status"] = "EVALUABLE"
                        return parsed

                except Exception as exc:
                    latency_ms = int((time.perf_counter() - start_t) * 1000)
                    raw_err = str(exc)
                    sanitized_err = sanitize_secret_error(raw_err)
                    status_code = getattr(exc, "code", 500) if hasattr(exc, "code") else 500
                    last_error = sanitized_err

                    if (status_code == 429 or "429" in raw_err) and attempt < max_attempts - 1:
                        retry_wait = 2.0 * (attempt + 1)
                        time.sleep(min(retry_wait, 5.0))
                        continue

                    if status_code == 402 or "402" in raw_err or "Payment Required" in raw_err or "prepayment credits are depleted" in raw_err.lower():
                        ai_status = OpenRouterStatus.CREDIT_EXHAUSTED.value
                    elif status_code == 429 or "429" in raw_err or "resource_exhausted" in raw_err.lower():
                        ai_status = OpenRouterStatus.RATE_LIMITED.value
                    elif status_code == 503 or "timed out" in raw_err.lower() or "connection refused" in raw_err.lower():
                        ai_status = OpenRouterStatus.UNAVAILABLE.value
                    else:
                        ai_status = OpenRouterStatus.INFERENCE_FAILED.value

                    last_status = ai_status
                    logger.warning(
                        f"{cand_name.capitalize()} thesis inference failed ({ai_status}: {sanitized_err}) "
                        f"for {agent_id} on {symbol}."
                    )
                    try:
                        from event_agent.storage.ledger import record_ai_telemetry
                        record_ai_telemetry({
                            "ai_request_id": f"failed_{int(time.time()*1000)}",
                            "market_date": datetime.now().strftime("%Y-%m-%d"),
                            "call_type": "DECISION_THESIS",
                            "agent_id": agent_id,
                            "symbol": symbol,
                            "model": cand_model,
                            "model_provider": cand_name,
                            "input_hash": in_hash,
                            "output_hash": "",
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                            "cost_usd": 0.0,
                            "latency_ms": latency_ms,
                            "http_status": status_code,
                            "status": ai_status,
                            "error_message": sanitized_err,
                        })
                    except Exception:
                        pass

                    if cand_idx < len(self.providers_chain) - 1:
                        logger.info(f"Failing over to next LLM provider in chain...")
                        break

        OpenRouterMetricsTracker.record_decision(last_status)
        return {
            "status": last_status,
            "ai_status": last_status,
            "error": last_error,
            "direction": "NO_TRADE",
            "expected_move_pct": 0.0,
            "horizon": "1D",
            "confidence": 0.0,
            "catalysts": [],
            "invalidating_conditions": ["AI intelligence failure / credit exhausted across all providers"],
            "reasoning": f"AI intelligence unavailable ({last_status}): {last_error}",
            "ai_request_id": None,
            "model": last_model,
            "actual_provider": last_provider_name,
            "decision_mode": "AI_UNAVAILABLE",
            "decision_model": f"{last_provider_name.upper()}:{last_model}",
            "model_provider": last_provider_name,
            "model_version": last_model,
            "fallback_reason": last_error,
            "evaluation_status": "EXCLUDED_FROM_ACCURACY",
        }

    def format_post_trade_diagnosis(self, audit_evidence: Dict[str, Any]) -> str:
        """
        Post-Trade AI Formatter: converts pre-computed 8D quantitative forensic evidence
        into human-readable analysis without inventing causes or changing root-cause codes.
        """
        if not self.providers_chain or not self.api_key:
            return audit_evidence.get("deterministic_summary", "Audit completed via deterministic engine.")

        prompt = (
            f"You are the NEXUS Quantitative Forensic Auditor.\n"
            f"Translate this PRE-COMPUTED 8-dimensional evidence into a concise, institutional post-trade diagnosis.\n"
            f"CRITICAL INVARIANT: You are a FORMATTER ONLY. Do NOT invent alternative explanations or modify root-cause codes.\n"
            f"Evidence JSON:\n{json.dumps(audit_evidence, indent=2)}\n\n"
            f"Format as structured markdown: Direction, Magnitude, Timing, Regime, Intraday Path, Catalyst Realization, Cross-Asset Confirmation, Root Cause."
        )

        for cand in self.providers_chain:
            cand_key = cand["key"]
            cand_type = cand["type"]
            cand_name = cand["name"]
            cand_endpoint = cand["endpoint"]
            cand_model = cand["model"]

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cand_key}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NEXUS/1.0",
            }
            if cand_type == "openrouter":
                headers["HTTP-Referer"] = "https://github.com/samudralasrikanth/algo-trader"
                headers["X-Title"] = "NEXUS Forensic Engine"

            body = json.dumps({
                "model": cand_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 400,
            }).encode("utf-8")

            start_t = time.perf_counter()
            try:
                req = urllib.request.Request(cand_endpoint, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    latency_ms = int((time.perf_counter() - start_t) * 1000)
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    req_id = data.get("id") or f"{cand_name}_{int(time.time()*1000)}"

                    try:
                        from event_agent.storage.ledger import record_ai_telemetry
                        record_ai_telemetry({
                            "ai_request_id": req_id,
                            "market_date": datetime.now().strftime("%Y-%m-%d"),
                            "call_type": "POST_TRADE_AUDIT",
                            "symbol": audit_evidence.get("symbol"),
                            "model": data.get("model", cand_model),
                            "model_provider": cand_name,
                            "input_hash": hashlib.sha256(body).hexdigest(),
                            "output_hash": hashlib.sha256(text.encode()).hexdigest(),
                            "input_tokens": usage.get("prompt_tokens", 0),
                            "output_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                            "cost_usd": 0.0 if cand_type in ("gemini", "groq") else (usage.get("total_tokens", 0) * 0.30) / 1_000_000.0,
                            "latency_ms": latency_ms,
                            "http_status": 200,
                            "status": "SUCCESS",
                        })
                    except Exception:
                        pass

                    return text.strip()
            except Exception as exc:
                logger.warning(f"Post-trade AI formatting fallback on {cand_name}: {exc}")

        return audit_evidence.get("deterministic_summary", "Audit completed via deterministic engine.")

    def interpret_event(
        self,
        headline: str,
        description: str = "",
        source: str = "news",
    ) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc).isoformat()
        if not self.providers_chain or not self.api_key:
            res = self.fallback.interpret_event(headline, description, source)
            res["provider"] = "heuristic_baseline"
            res["inference_mode"] = "HEURISTIC_FALLBACK"
            res["ai"] = {
                "provider": self.provider_name,
                "model": self.model,
                "request_id": None,
                "latency_ms": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "status": "NOT_CONFIGURED",
                "inference_mode": "HEURISTIC_FALLBACK",
                "error_reason": f"{self.provider_name.upper()}_API_KEY environment variable not configured",
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

        last_exc = None
        start_t = time.perf_counter()
        for cand in self.providers_chain:
            cand_key = cand["key"]
            cand_type = cand["type"]
            cand_name = cand["name"]
            cand_endpoint = cand["endpoint"]
            cand_model = cand["model"]

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cand_key}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NEXUS/1.0",
            }
            if cand_type == "openrouter":
                headers["HTTP-Referer"] = "https://github.com/samudralasrikanth/algo-trader"
                headers["X-Title"] = "NEXUS Nifty 50 Event Agent"

            max_tokens = 1000 if cand_type == "openrouter" else 400
            req_payload: Dict[str, Any] = {
                "model": cand_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
            if cand_type not in ("gemini", "openrouter"):
                req_payload["response_format"] = {"type": "json_object"}

            body = json.dumps(req_payload).encode("utf-8")
            cand_start_t = time.perf_counter()
            try:
                req = urllib.request.Request(cand_endpoint, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    latency_ms = int((time.perf_counter() - cand_start_t) * 1000)
                    data = json.loads(resp.read().decode("utf-8"))
                    content_str = data["choices"][0]["message"].get("content") or ""
                    clean_content = content_str.strip()
                    if clean_content.startswith("```"):
                        clean_content = re.sub(r"^```[a-zA-Z]*\n?", "", clean_content)
                        clean_content = re.sub(r"\n?```$", "", clean_content).strip()
                    if "{" in clean_content and "}" in clean_content:
                        clean_content = clean_content[clean_content.find("{"):clean_content.rfind("}")+1]
                    parsed = json.loads(clean_content)
                    usage = data.get("usage", {})
                    req_id = data.get("id") or f"{cand_name}_{int(time.time()*1000)}"
                    parsed["provider"] = f"{cand_name}_{cand_model}"
                    parsed["source"] = source
                    parsed["timestamp"] = now_utc
                    parsed["inference_mode"] = f"{cand_name.upper()}_LIVE"
                    parsed["ai"] = {
                        "provider": cand_name,
                        "model": cand_model,
                        "request_id": req_id,
                        "latency_ms": latency_ms,
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                        "status": "SUCCESS",
                        "inference_mode": f"{cand_name.upper()}_LIVE",
                        "timestamp": now_utc,
                    }
                    return parsed
            except Exception as exc:
                last_exc = exc
                logger.warning(f"{cand_name.capitalize()} event interpretation failed ({exc}). Trying next provider...")

        latency_ms = int((time.perf_counter() - start_t) * 1000)
        res = self.fallback.interpret_event(headline, description, source)
        res["provider"] = "heuristic_fallback"
        res["inference_mode"] = "HEURISTIC_FALLBACK"
        res["ai"] = {
            "provider": self.provider_name,
            "model": self.model,
            "request_id": None,
            "latency_ms": latency_ms,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "status": "FAILED",
            "inference_mode": "HEURISTIC_FALLBACK",
            "error_reason": sanitize_secret_error(str(last_exc)),
            "timestamp": now_utc,
        }
        return res


def get_default_llm_provider() -> LLMProvider:
    """
    Returns the best available LLM provider based on environment configuration:
    1. OpenRouterProvider with multi-provider failover chain across Groq, Gemini, OpenRouter
    2. OpenAIProvider if explicitly configured
    3. HeuristicEventParser (deterministic offline baseline) as default
    """
    provider = OpenRouterProvider()
    if provider.providers_chain:
        return provider

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        if openai_key.startswith("sk-or-"):
            return OpenRouterProvider(api_key=openai_key)
        return OpenAIProvider(api_key=openai_key)
    else:
        return HeuristicEventParser()
