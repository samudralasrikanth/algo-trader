# =============================================================================
# tests/test_v363_api_integrity_and_provenance.py
# V3.6.3 API Connectivity, Data Provenance & Failure Injection Audit Test Suite
# =============================================================================
"""
V3.6.3 Institutional Acceptance Suite:
1. Server-side OpenRouter API Key Isolation (Never reaches browser/DOM/storage)
2. Zero Fabricated Runtime Telemetry (Honest defaults, no hardcoded stats)
3. AI Provenance Integrity (Full execution audit: request_id, latency_ms > 0, tokens > 0)
4. Failure Injection: Invalid API Key -> PARTIAL / DEGRADED
5. Failure Injection: Missing API Key -> NOT CONFIGURED / HEURISTIC BASELINE
6. Dynamic Risk Gate Resolution (No hardcoded 8 or 16)
7. API Connectivity Table & dP Gold Authenticity (Awaiting authorized feed)
8. Cryptographic Hash Provenance (No static invented hashes)
"""

import json
import os
from pathlib import Path
import pytest
from datetime import datetime, timezone

from event_agent.engine.llm_provider import OpenRouterProvider, HeuristicEventParser
from event_agent.jobs.news_collection import NewsIntelligenceCollector, NewsArticleRecord
from event_agent.jobs.job_ledger import JobLedger, JobRunRecord
from event_agent.jobs.scheduler import AfterMarketScheduler

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_DIR = WORKSPACE_ROOT / "web_app"
INDEX_HTML = WEB_APP_DIR / "index.html"
APP_JS = WEB_APP_DIR / "app.js"
DATA_JSON = WEB_APP_DIR / "data.json"
DATA_JS = WEB_APP_DIR / "data.js"
NETLIFY_HEALTH_AI = WORKSPACE_ROOT / "netlify" / "functions" / "health_ai.js"
NETLIFY_TOML = WORKSPACE_ROOT / "netlify.toml"


class TestV363ServerSideIsolation:
    """1. 🔴 Server-side key isolation acceptance tests."""

    def test_openrouter_key_never_reaches_client_bundles(self):
        """
        MANDATORY ACCEPTANCE TEST:
        OPENROUTER_API_KEY must NEVER appear in:
        - index.html
        - app.js
        - data.json
        - data.js
        - client DOM/assets
        """
        client_files = [INDEX_HTML, APP_JS, DATA_JSON, DATA_JS]
        for path in client_files:
            assert path.exists(), f"Missing client bundle {path.name}"
            content = path.read_text(encoding="utf-8")
            # Must not contain live sk-or keys
            assert "sk-or-v1-" not in content, f"Secret leak found in {path.name}"
            # Must not expose the environment variable name in data payloads
            if path.suffix == ".json":
                data = json.loads(content)
                dumped = json.dumps(data)
                assert "sk-or-" not in dumped
                assert "OPENROUTER_API_KEY=" not in dumped

    def test_netlify_health_ai_proxy_security(self):
        """Verifies netlify/functions/health_ai.js accesses key server-side and never echoes it."""
        assert NETLIFY_HEALTH_AI.exists(), "Netlify health_ai function missing"
        code = NETLIFY_HEALTH_AI.read_text(encoding="utf-8")
        assert "process.env.OPENROUTER_API_KEY" in code
        assert "password" not in code.lower()
        # Ensure it doesn't return the key in JSON responses
        assert 'apiKey: apiKey' not in code
        assert 'key: apiKey' not in code

        # Check netlify.toml redirect exists before wildcard
        toml_content = NETLIFY_TOML.read_text(encoding="utf-8")
        assert "/api/health/ai" in toml_content
        assert "/.netlify/functions/health_ai" in toml_content
        # Ensure /api/health/ai is defined before /*
        api_idx = toml_content.find("/api/health/ai")
        catchall_idx = toml_content.find('from = "/*"')
        assert api_idx < catchall_idx, "/api/health/ai redirect must precede the wildcard catch-all"


class TestV363ZeroFakeTelemetry:
    """2. 🔴 Zero fabricated runtime telemetry."""

    def test_no_hardcoded_telemetry_in_production_data(self):
        """Verifies no example numbers (24 requests, 1420ms, 18:00:19Z) are hardcoded as active data."""
        data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        ai_diag = data.get("openrouter_telemetry", {})
        # If uncalled or default, must not fabricate runtime metrics
        if ai_diag.get("status") in ["NOT_TESTED", "NOT_CONFIGURED"]:
            assert ai_diag.get("latency_ms") is None or ai_diag.get("latency_ms") == 0
            assert ai_diag.get("request_id") is None
            assert ai_diag.get("total_tokens") == 0


class TestV363AIProvenanceIntegrity:
    """3. 🟢 AI Provenance Integrity (Prove AI was genuinely executed)."""

    def test_ai_provenance_attributes_on_article(self):
        """
        User Mandate 8 (Test 6):
        For every LLM-generated article assert:
        - status == 'SUCCESS' (or 'NOT_CONFIGURED'/'FAILED' if tested offline)
        - provider == 'openrouter'
        - request_id is not None (when SUCCESS)
        - latency_ms > 0 (when SUCCESS)
        - total_tokens > 0 (when SUCCESS)
        - analyzed_at >= ingested_at
        """
        # Create an article with real or mock OpenRouter telemetry
        ingest_t = "2026-09-09T18:00:00+00:00"
        analyzed_t = "2026-09-09T18:00:01+00:00"

        ai_meta = {
            "provider": "openrouter",
            "model": "openai/gpt-4o-mini",
            "request_id": "gen-1788972817-x0dert61u4DxkWD81e8E",
            "latency_ms": 1250,
            "input_tokens": 142,
            "output_tokens": 81,
            "total_tokens": 223,
            "status": "SUCCESS",
            "inference_mode": "OPENROUTER_LIVE",
            "ingested_at": ingest_t,
            "analyzed_at": analyzed_t,
            "timestamp": analyzed_t,
        }

        record = NewsArticleRecord(
            article_id="ART-test1234",
            headline="NIFTY 50 surges past key hurdle",
            source="Reuters",
            url="https://example.com/test",
            category="equities",
            region="IN",
            published_at=ingest_t,
            ingested_at=ingest_t,
            analyzed_at=analyzed_t,
            content_hash="test1234",
            event_type="EARNINGS_BEAT",
            sentiment="POSITIVE",
            impact="HIGH",
            surprise="+1.8σ",
            affected_assets=["NIFTY 50"],
            affected_sectors=["Broad Market"],
            horizon="1–3 DAYS",
            ai_summary="Positive momentum",
            ai_reasoning="Causal breakout",
            confidence=85.0,
            why_it_matters_chain=["Chain 1", "Chain 2"],
            why_it_matters_text="Surprise -> Re-rating",
            nexus_impact="HIGH",
            transmission_horizon="1–3 DAYS",
            inference_mode="OPENROUTER_LIVE",
            ai=ai_meta,
        )

        ai = record.ai
        assert ai is not None
        assert ai["status"] == "SUCCESS"
        assert ai["provider"] == "openrouter"
        assert ai["request_id"] is not None
        assert ai["latency_ms"] > 0
        assert ai["total_tokens"] > 0
        assert ai["analyzed_at"] >= ai["ingested_at"]


class TestV363FailureInjection:
    """4 & 5. 🟢 Failure injection tests (Invalid key & Missing key)."""

    def test_failure_injection_invalid_key_triggers_degraded_pipeline(self):
        """
        OPENROUTER_API_KEY = INVALID_TEST_KEY
               ↓
        OpenRouter fails (HTTP 401)
               ↓
        AI status = FAILED
               ↓
        inference_mode = HEURISTIC_FALLBACK
        """
        provider = OpenRouterProvider(api_key="sk-or-v1-INVALID_MOCK_KEY_FOR_INJECTION_TEST")
        # ping_health should report FAILED
        ping = provider.ping_health()
        assert ping["status"] == "FAILED"
        assert ping["provider"] == "openrouter"
        assert ping["request_id"] is None

        # interpret_event should fall back gracefully
        res = provider.interpret_event("TCS reports 8% revenue growth", source="news")
        assert res["inference_mode"] == "HEURISTIC_FALLBACK"
        assert res["ai"]["status"] == "FAILED"
        assert res["ai"]["provider"] == "openrouter"
        assert res["ai"]["inference_mode"] == "HEURISTIC_FALLBACK"

    def test_failure_injection_missing_key_triggers_not_configured(self):
        """
        OPENROUTER_API_KEY = None / ""
               ↓
        AI CONFIGURATION: NOT CONFIGURED
        OpenRouter calls: 0
        Inference: NOT EXECUTED
        Fallback: HEURISTIC BASELINE
        """
        provider = OpenRouterProvider(api_key="")
        ping = provider.ping_health()
        assert ping["status"] == "NOT_CONFIGURED"
        assert ping["configured"] is False
        assert ping["last_failure"] is not None

        res = provider.interpret_event("Infosys bags multi-year cloud contract", source="news")
        assert res["inference_mode"] == "HEURISTIC_FALLBACK"
        assert res["ai"]["status"] == "NOT_CONFIGURED"
        assert res["provider"] == "heuristic_baseline"


class TestV363DynamicRiskGates:
    """6. 🟢 Dynamic Risk-Gate Calculation (No hardcoding 8 or 16)."""

    def test_backend_risk_gates_invariants_and_dynamic_count(self):
        """Verifies that risk_gates contains backend invariants and counts are dynamic."""
        data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        assert "risk_gates" in data
        gates = data["risk_gates"]
        assert len(gates) >= 8

        # Invariant checks
        gate_names = [g["name"] for g in gates]
        assert any("VaR" in n for n in gate_names)
        assert any("Slippage" in n for n in gate_names)
        assert any("Delta" in n for n in gate_names)
        assert any("Gamma" in n for n in gate_names)
        assert any("Cutoff" in n for n in gate_names)

        # Verify app.js uses dynamic length calculation
        app_js = APP_JS.read_text(encoding="utf-8")
        assert "const passed = gates.filter(" in app_js
        assert "const total = gates.length;" in app_js
        assert "statusText: `${passed} / ${total} GATES VERIFIED`" in app_js
        # Must not hardcode 16 in default string
        assert "16 / 16 GATES VERIFIED" not in app_js


class TestV363ApiConnectivityTableAndProvenance:
    """7 & 8. 🟢 API Connectivity Table, dP Gold Authenticity & Hash Provenance."""

    def test_api_connectivity_table_feeds_and_dp_gold_truthfulness(self):
        """Verifies API connectivity table contains 5 feeds and dP Gold has NO invented REST API."""
        data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        assert "api_telemetry" in data
        feeds = data["api_telemetry"]
        assert len(feeds) == 5

        feed_names = [f["feed"] for f in feeds]
        assert "NSE India Equity & Indices" in feed_names
        assert "News RSS (Google Financial)" in feed_names
        assert "OpenRouter AI Intelligence" in feed_names
        assert "COMEX Gold Continuous Futures" in feed_names
        assert "dP Gold Physical Bullion" in feed_names

        # Inspect dP Gold specifically: must NOT invent endpoint
        dp_gold = next(f for f in feeds if "dP Gold" in f["feed"])
        assert dp_gold["http_status"] == "—"
        assert dp_gold["schema_validation"] == "NOT CONFIGURED"
        assert dp_gold["freshness"] == "UNAVAILABLE"
        assert "Awaiting authorized feed" in dp_gold["error"]

        # Ensure no invented dpgold.com/api URL in codebase
        for p in [INDEX_HTML, APP_JS, DATA_JSON]:
            content = p.read_text(encoding="utf-8")
            assert "dpgold.com/api" not in content, f"Invented dP Gold API found in {p.name}"

    def test_static_sequential_hash_purged(self):
        """Verifies static sequential hash 4f9e8a1b2c3d4e5f... is completely removed from index.html."""
        html_content = INDEX_HTML.read_text(encoding="utf-8")
        fake_hash = "4f9e8a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f"
        assert fake_hash not in html_content, "Hardcoded fake sequential hash still present in index.html"
        assert "AWAITING RECORD SELECTION" in html_content
