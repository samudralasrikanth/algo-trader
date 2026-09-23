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
        """Performs a lightweight connectivity & credential verification test with zero key leak."""
        fingerprint = f"SHA256:{hashlib.sha256(self.api_key.encode()).hexdigest()[:16]}" if self.api_key else None
        if not self.api_key:
            return {
                "provider": "openrouter",
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
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                tot_tok = usage.get("total_tokens", 0)
                cost = (in_tok * 0.15 + out_tok * 0.60) / 1_000_000.0
                return {
                    "status": "SUCCESS",
                    "substatus": "AUTHENTICATED",
                    "provider": "openrouter",
                    "configured": True,
                    "credential_fingerprint": fingerprint,
                    "inference_mode": "OPENROUTER_LIVE",
                    "model": data.get("model", self.model),
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
            err_substatus = "INVALID_KEY" if status_code in (401, 403) else ("RATE_LIMITED" if status_code == 429 else "UNREACHABLE")
            return {
                "status": "FAILED",
                "substatus": err_substatus,
                "provider": "openrouter",
                "configured": True,
                "credential_fingerprint": fingerprint,
                "inference_mode": "UNAVAILABLE",
                "model": self.model,
                "request_id": None,
                "latency_ms": latency_ms,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "error_reason": str(exc),
                "last_success": None,
                "last_failure": datetime.now(timezone.utc).isoformat(),
            }

    def generate_decision_thesis(
        self,
        agent_id: str,
        symbol: str,
        stock_data: Dict[str, Any],
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes real decision-time OpenRouter inference for an agent.
        Logs verified execution telemetry directly to SQLite ledger.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        if not self.api_key:
            return {
                "status": "UNCONFIGURED",
                "error": "OPENROUTER_API_KEY environment variable not configured",
                "direction": None,
                "expected_move_pct": 0.0,
                "horizon": "1D",
                "confidence": 0.0,
                "catalysts": [],
                "invalidating_conditions": [],
                "reasoning": "AI intelligence unavailable: OPENROUTER_API_KEY not configured.",
                "ai_request_id": None,
                "model": self.model,
                "actual_provider": "none",
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

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/samudralasrikanth/algo-trader",
            "X-Title": "NEXUS Decision Engine",
        }
        body_str = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 400,
        })
        body = body_str.encode("utf-8")
        in_hash = hashlib.sha256(body).hexdigest()

        start_t = time.perf_counter()
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                raw_bytes = resp.read()
                out_hash = hashlib.sha256(raw_bytes).hexdigest()
                data = json.loads(raw_bytes.decode("utf-8"))
                content_str = data["choices"][0]["message"]["content"]
                parsed = json.loads(content_str)
                usage = data.get("usage", {})
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                tot_tok = usage.get("total_tokens", 0)
                cost = (in_tok * 0.15 + out_tok * 0.60) / 1_000_000.0
                req_id = data.get("id")
                act_model = data.get("model", self.model)

                # Persist telemetry to SQLite
                try:
                    from event_agent.storage.ledger import record_ai_telemetry
                    record_ai_telemetry({
                        "ai_request_id": req_id,
                        "market_date": datetime.now().strftime("%Y-%m-%d"),
                        "call_type": "DECISION_THESIS",
                        "agent_id": agent_id,
                        "symbol": symbol,
                        "model": act_model,
                        "model_provider": "openrouter",
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

                parsed["status"] = "SUCCESS"
                parsed["ai_request_id"] = req_id
                parsed["model"] = act_model
                parsed["actual_provider"] = "openrouter"
                parsed["latency_ms"] = latency_ms
                parsed["tokens"] = tot_tok
                return parsed

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            logger.warning(f"OpenRouter thesis inference failed ({exc}) for {agent_id} on {symbol}")
            try:
                from event_agent.storage.ledger import record_ai_telemetry
                record_ai_telemetry({
                    "ai_request_id": f"failed_{int(time.time()*1000)}",
                    "market_date": datetime.now().strftime("%Y-%m-%d"),
                    "call_type": "DECISION_THESIS",
                    "agent_id": agent_id,
                    "symbol": symbol,
                    "model": self.model,
                    "model_provider": "openrouter",
                    "input_hash": in_hash,
                    "output_hash": "",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "latency_ms": latency_ms,
                    "http_status": 500,
                    "status": "FAILED",
                    "error_message": str(exc),
                })
            except Exception:
                pass

            return {
                "status": "FAILED",
                "error": str(exc),
                "direction": None,
                "expected_move_pct": 0.0,
                "horizon": "1D",
                "confidence": 0.0,
                "catalysts": [],
                "invalidating_conditions": [],
                "reasoning": f"Inference failed: {exc}",
                "ai_request_id": None,
                "model": self.model,
                "actual_provider": "openrouter",
            }

    def format_post_trade_diagnosis(self, audit_evidence: Dict[str, Any]) -> str:
        """
        Post-Trade AI Formatter: converts pre-computed 8D quantitative forensic evidence
        into human-readable analysis without inventing causes or changing root-cause codes.
        """
        if not self.api_key:
            return audit_evidence.get("deterministic_summary", "Audit completed via deterministic engine.")

        prompt = (
            f"You are the NEXUS Quantitative Forensic Auditor.\n"
            f"Translate this PRE-COMPUTED 8-dimensional evidence into a concise, institutional post-trade diagnosis.\n"
            f"CRITICAL INVARIANT: You are a FORMATTER ONLY. Do NOT invent alternative explanations or modify root-cause codes.\n"
            f"Evidence JSON:\n{json.dumps(audit_evidence, indent=2)}\n\n"
            f"Format as structured markdown: Direction, Magnitude, Timing, Regime, Intraday Path, Catalyst Realization, Cross-Asset Confirmation, Root Cause."
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/samudralasrikanth/algo-trader",
            "X-Title": "NEXUS Forensic Engine",
        }
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 350,
        }).encode("utf-8")

        start_t = time.perf_counter()
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                req_id = data.get("id")

                try:
                    from event_agent.storage.ledger import record_ai_telemetry
                    record_ai_telemetry({
                        "ai_request_id": req_id,
                        "market_date": datetime.now().strftime("%Y-%m-%d"),
                        "call_type": "POST_TRADE_AUDIT",
                        "symbol": audit_evidence.get("symbol"),
                        "model": data.get("model", self.model),
                        "model_provider": "openrouter",
                        "input_hash": hashlib.sha256(body).hexdigest(),
                        "output_hash": hashlib.sha256(text.encode()).hexdigest(),
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                        "cost_usd": (usage.get("total_tokens", 0) * 0.30) / 1_000_000.0,
                        "latency_ms": latency_ms,
                        "http_status": 200,
                        "status": "SUCCESS",
                    })
                except Exception:
                    pass

                return text.strip()
        except Exception as exc:
            logger.warning(f"Post-trade AI formatting fallback: {exc}")
            return audit_evidence.get("deterministic_summary", "Audit completed via deterministic engine.")


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
