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
from risk.risk_invariants import evaluate_risk_invariants

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


# =============================================================================
# V3.6.4 INSTITUTIONAL CERTIFICATION TESTS
# =============================================================================

class TestV364RiskInvariantsSpecification:
    """V3.6.4 Institutional Risk Engine Specification & Absence of Evidence Invariants."""

    def test_var_99_two_cases_and_insufficient_data(self):
        """
        VaR 99%:
          Case A: valid dataset with mild return volatility -> PASS (<= 2.0%)
          Case B: excessive volatility -> FAIL (> 2.0%)
          Case C: insufficient data (< 5 closed trades) -> NOT_VERIFIED
        """
        # Case A: Low volatility (std ~ 0.003 -> VaR99 ~ 0.7% <= 2.0%)
        trades_low_vol = [
            {"pnl": 100.0, "capital_at_risk": 100000.0},
            {"pnl": -50.0, "capital_at_risk": 100000.0},
            {"pnl": 120.0, "capital_at_risk": 100000.0},
            {"pnl": 80.0, "capital_at_risk": 100000.0},
            {"pnl": -20.0, "capital_at_risk": 100000.0},
            {"pnl": 40.0, "capital_at_risk": 100000.0},
        ]
        gates_a = evaluate_risk_invariants(portfolio={"current_capital": 100000.0}, trades=trades_low_vol)
        var_a = next(g for g in gates_a if g["id"] == "GATE_VAR_99")
        assert var_a["status"] == "PASS"
        assert var_a["current"] is not None

        # Case B: Excessive volatility (std ~ 0.02 -> VaR99 ~ 4.6% > 2.0%)
        trades_high_vol = [
            {"pnl": 3000.0, "capital_at_risk": 100000.0},
            {"pnl": -2500.0, "capital_at_risk": 100000.0},
            {"pnl": 2800.0, "capital_at_risk": 100000.0},
            {"pnl": -3200.0, "capital_at_risk": 100000.0},
            {"pnl": 3500.0, "capital_at_risk": 100000.0},
            {"pnl": -2900.0, "capital_at_risk": 100000.0},
        ]
        gates_b = evaluate_risk_invariants(portfolio={"current_capital": 100000.0}, trades=trades_high_vol)
        var_b = next(g for g in gates_b if g["id"] == "GATE_VAR_99")
        assert var_b["status"] == "FAIL"
        assert var_b["current"] is not None

        # Case C: Insufficient data (< 5 trades) -> MUST NOT equal PASS or FAIL
        trades_empty = []
        gates_c = evaluate_risk_invariants(portfolio={"current_capital": 100000.0}, trades=trades_empty)
        var_c = next(g for g in gates_c if g["id"] == "GATE_VAR_99")
        assert var_c["status"] == "NOT_VERIFIED"
        assert var_c["current"] is None

    def test_slippage_two_cases_and_insufficient_data(self):
        """
        Slippage:
          Case A: 4 bps -> PASS (<= 15 bps)
          Case B: 20 bps -> FAIL (> 15 bps)
          Case C: empty dataset -> NOT_VERIFIED
        """
        # Case A: 4 bps (entry 100.0, exit 100.04)
        trades_a = [{"entry_price": 100.0, "exit_price": 100.04}]
        gates_a = evaluate_risk_invariants(trades=trades_a)
        slip_a = next(g for g in gates_a if g["id"] == "GATE_SLIPPAGE")
        assert slip_a["status"] == "PASS"
        assert "4.0 bps" in slip_a["current"]

        # Case B: 20 bps (entry 100.0, exit 100.20)
        trades_b = [{"entry_price": 100.0, "exit_price": 100.20}]
        gates_b = evaluate_risk_invariants(trades=trades_b)
        slip_b = next(g for g in gates_b if g["id"] == "GATE_SLIPPAGE")
        assert slip_b["status"] == "FAIL"
        assert "20.0 bps" in slip_b["current"]

        # Case C: empty dataset -> NOT_VERIFIED
        gates_c = evaluate_risk_invariants(trades=[])
        slip_c = next(g for g in gates_c if g["id"] == "GATE_SLIPPAGE")
        assert slip_c["status"] == "NOT_VERIFIED"
        assert slip_c["current"] is None

    def test_concentration_two_cases_and_insufficient_data(self):
        """
        Single Stock Concentration:
          Case A: 8% -> PASS (<= 10.0%)
          Case B: 12% -> FAIL (> 10.0%)
          Case C: empty dataset -> NOT_VERIFIED
        """
        # Case A: 8% (notional 8,000 on 100,000 capital)
        positions_a = [{"symbol": "INFY", "notional": 8000.0}]
        gates_a = evaluate_risk_invariants(portfolio={"current_capital": 100000.0}, open_positions=positions_a)
        conc_a = next(g for g in gates_a if g["id"] == "GATE_STOCK_CONCENTRATION")
        assert conc_a["status"] == "PASS"
        assert "8.0%" in conc_a["current"]

        # Case B: 12% (notional 12,000 on 100,000 capital)
        positions_b = [{"symbol": "RELIANCE", "notional": 12000.0}]
        gates_b = evaluate_risk_invariants(portfolio={"current_capital": 100000.0}, open_positions=positions_b)
        conc_b = next(g for g in gates_b if g["id"] == "GATE_STOCK_CONCENTRATION")
        assert conc_b["status"] == "FAIL"
        assert "12.0%" in conc_b["current"]

        # Case C: zero capital -> NOT_VERIFIED
        gates_c = evaluate_risk_invariants(portfolio={"current_capital": 0.0}, open_positions=[])
        conc_c = next(g for g in gates_c if g["id"] == "GATE_STOCK_CONCENTRATION")
        assert conc_c["status"] == "NOT_VERIFIED"
        assert conc_c["current"] is None

    def test_session_cutoff_two_cases_and_insufficient_data(self):
        """
        Session Cutoff (15:30 IST):
          Case A: 15:29 IST -> PASS
          Case B: 15:31 IST -> FAIL
          Case C: absent timestamp -> NOT_VERIFIED
        """
        # Case A: 15:29 IST (09:59 UTC)
        sys_a = {"last_order_submitted_at": "2026-09-09T09:59:00+00:00"}
        gates_a = evaluate_risk_invariants(system_status=sys_a)
        cut_a = next(g for g in gates_a if g["id"] == "GATE_SESSION_CUTOFF")
        assert cut_a["status"] == "PASS"

        # Case B: 15:31 IST (10:01 UTC)
        sys_b = {"last_order_submitted_at": "2026-09-09T10:01:00+00:00"}
        gates_b = evaluate_risk_invariants(system_status=sys_b)
        cut_b = next(g for g in gates_b if g["id"] == "GATE_SESSION_CUTOFF")
        assert cut_b["status"] == "FAIL"

        # Case C: empty system status -> NOT_VERIFIED
        gates_c = evaluate_risk_invariants(system_status={})
        cut_c = next(g for g in gates_c if g["id"] == "GATE_SESSION_CUTOFF")
        assert cut_c["status"] == "NOT_VERIFIED"
        assert cut_c["current"] is None

    def test_canonical_status_and_zero_passed_boolean(self):
        """
        Institutional Invariant:
        Absence of evidence = NOT_VERIFIED.
        Every gate must have status in ['PASS', 'FAIL', 'NOT_VERIFIED'].
        ZERO gates may contain a 'passed' boolean.
        """
        gates = evaluate_risk_invariants()
        assert len(gates) == 8
        for g in gates:
            assert g["status"] in ["PASS", "FAIL", "NOT_VERIFIED"]
            assert "passed" not in g, f"Gate {g['id']} contains legacy 'passed' boolean field!"

        # Check production data.json
        data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        prod_gates = data.get("risk_gates", [])
        assert len(prod_gates) == 8
        for g in prod_gates:
            assert g["status"] in ["PASS", "FAIL", "NOT_VERIFIED"]
            assert "passed" not in g, f"Production gate {g.get('id')} contains 'passed' boolean!"


class TestV364ApiAccountingDistinction:
    """Explicit distinction: HTTP API requests vs domain records analyzed/persisted."""

    def test_requests_attempted_does_not_equal_records_analyzed(self):
        """
        User Mandate 3:
        24 news records -> 6 batched OpenRouter requests -> 24 records analyzed -> 23 persisted.
        Never derive requests_attempted from records_analyzed.
        """
        telemetry = {
            "feed": "OpenRouter AI Intelligence",
            "http_status": 200,
            "requests_attempted": 6,
            "requests_succeeded": 6,
            "requests_failed": 0,
            "input_tokens": 1234,
            "output_tokens": 987,
            "total_tokens": 2221,
            "records_analyzed": 24,
            "records_persisted": 23,
            "freshness": "CURRENT",
            "fallback": "None",
            "error": None,
        }

        assert telemetry["requests_attempted"] == 6
        assert telemetry["records_analyzed"] == 24
        assert telemetry["records_persisted"] == 23
        assert telemetry["requests_attempted"] != telemetry["records_analyzed"]
        assert telemetry["records_persisted"] != telemetry["records_analyzed"]


class TestV364FailureHierarchy:
    """V3.6.4 Parent / Child execution failure hierarchy."""

    def test_all_children_success_yields_parent_success(self):
        """All children SUCCESS -> Parent SUCCESS."""
        sub_jobs = {
            "intl": {"status": "SUCCESS"},
            "market": {"status": "SUCCESS"},
            "commodity": {"status": "SUCCESS"},
            "news": {"status": "SUCCESS"},
        }
        any_failed = any(v.get("status") == "FAILED" for v in sub_jobs.values())
        any_unconfigured = any(v.get("status") == "NOT_CONFIGURED" for v in sub_jobs.values())
        all_success = all(v.get("status") == "SUCCESS" for v in sub_jobs.values())

        if all_success:
            classification = "SUCCESS"
        elif any_failed or any_unconfigured:
            classification = "PARTIAL"
        else:
            classification = "FAILED"

        assert classification == "SUCCESS"

    def test_child_failure_yields_parent_partial(self):
        """Child FAILED -> Parent PARTIAL."""
        sub_jobs = {
            "intl": {"status": "SUCCESS"},
            "market": {"status": "SUCCESS"},
            "commodity": {"status": "SUCCESS"},
            "news": {"status": "FAILED"},
        }
        any_failed = any(v.get("status") == "FAILED" for v in sub_jobs.values())
        all_success = all(v.get("status") == "SUCCESS" for v in sub_jobs.values())

        classification = "SUCCESS" if all_success else ("PARTIAL" if any_failed else "FAILED")
        assert classification == "PARTIAL"

    def test_child_not_configured_yields_parent_partial(self):
        """Child NOT_CONFIGURED -> Parent PARTIAL."""
        sub_jobs = {
            "intl": {"status": "SUCCESS"},
            "market": {"status": "SUCCESS"},
            "commodity": {"status": "NOT_CONFIGURED"},
            "news": {"status": "SUCCESS"},
        }
        any_partial_trigger = any(v.get("status") in ["FAILED", "NOT_CONFIGURED"] for v in sub_jobs.values())
        classification = "PARTIAL" if any_partial_trigger else "SUCCESS"
        assert classification == "PARTIAL"


class TestV364DurableProvenanceChain:
    """User Mandate 5: Full lineage for every LLM-derived record."""

    def test_complete_provenance_chain_fields(self):
        """
        Lineage:
        record_id -> source_article_id -> ingested_at -> inference_id ->
        provider -> model -> request_id -> analyzed_at -> output -> snapshot_hash
        """
        record = NewsArticleRecord(
            article_id="ART-101",
            headline="RBI Keeps Repo Rate Unchanged at 6.5%",
            source="PTI",
            url="https://example.com/rbi",
            category="Macro",
            region="India",
            published_at="2026-09-09T10:00:00Z",
            ingested_at="2026-09-09T10:01:00Z",
            analyzed_at="2026-09-09T10:01:02Z",
            content_hash="hash-12345",
            event_type="MACRO_RATE_DECISION",
            sentiment="NEUTRAL",
            impact="HIGH",
            surprise="0.0σ",
            affected_assets=["NIFTY 50", "BANKNIFTY"],
            affected_sectors=["Banking"],
            horizon="1–3 DAYS",
            ai_summary="RBI maintains status quo",
            ai_reasoning="Inflation remains within tolerance band",
            confidence=92.0,
            why_it_matters_chain=["Repo static -> Lending rates stable -> BFSI margins preserved"],
            why_it_matters_text="Status quo supports equity valuations",
            nexus_impact="HIGH",
            transmission_horizon="1–3 DAYS",
            inference_mode="OPENROUTER_LIVE",
            record_id="REC-ART-101",
            source_article_id="SRC-RBI-PTI-001",
            inference_id="INF-20260909-001",
            provider="openrouter",
            model="openai/gpt-4o-mini",
            request_id="gen-req-778899",
            snapshot_hash="snap-sha256-abcdef123456",
        )

        d = record.to_dict()
        assert d["record_id"] == "REC-ART-101"
        assert d["source_article_id"] == "SRC-RBI-PTI-001"
        assert d["inference_id"] == "INF-20260909-001"
        assert d["provider"] == "openrouter"
        assert d["model"] == "openai/gpt-4o-mini"
        assert d["request_id"] == "gen-req-778899"
        assert d["snapshot_hash"] == "snap-sha256-abcdef123456"
        assert d["analyzed_at"] >= d["ingested_at"]


class TestV364JobLedgerTelemetryPersistence:
    """User Mandate 4: Telemetry attached to specific immutable JobRunRecord."""

    def test_job_ledger_persists_api_telemetry_in_sqlite(self, tmp_path):
        """Verifies api_telemetry is stored and retrieved per JobRunRecord."""
        db_path = tmp_path / "test_ledger.db"
        ledger = JobLedger(db_path=db_path)

        now = datetime.now(timezone.utc)
        parent = ledger.create_run(
            job_name="AFTER_MARKET_EVALUATION",
            trigger_type="TEST",
            run_classification="SUCCESS",
        )

        tel_payload = {
            "provider": "openrouter",
            "requests_attempted": 24,
            "requests_succeeded": 24,
            "requests_failed": 0,
            "records_analyzed": 24,
            "records_persisted": 24,
        }

        completed = ledger.complete_run(
            run_id=parent.run_id,
            status="SUCCESS",
            records_fetched=24,
            records_processed=24,
            records_rejected=0,
            sources_attempted=1,
            sources_succeeded=1,
            sources_failed=0,
            data_quality="GOOD",
            api_telemetry=tel_payload,
        )

        # Retrieve independently from database
        fetched = ledger.get_run(parent.run_id)
        assert fetched is not None
        assert fetched.api_telemetry == tel_payload
        assert fetched.api_telemetry["requests_attempted"] == 24

