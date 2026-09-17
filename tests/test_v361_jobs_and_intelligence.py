"""
NEXUS V3.6.1 Automated Test Suite
==================================
Validates:
1. Job Ledger (Persistent SQLite audit storage with 18 required fields)
2. Market Data Collection (Indian benchmarks & closing feeds)
3. International Market Collection (24 global assets with freshness)
4. Commodity Collection (Gold & Silver spot in USD/oz and converted INR)
5. News Intelligence & Deduplication (SHA-256 + Jaccard title similarity)
6. Overnight Intelligence Engine (Opening bias, gap, scenarios, risks)
7. Overnight Scheduler (UTC-aware 3-hour cadence, web data sync)
8. Web App UI Integrity (Navigation, view panels, modals, zero placeholders)
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest

from event_agent.jobs import (
    JobLedger,
    JobRunRecord,
    OvernightScheduler,
    ScheduleWindow,
    MarketCloseCollector,
    InternationalDataCollector,
    CommodityDataCollector,
    NewsIntelligenceCollector,
    NewsArticleRecord,
    OvernightIntelligenceEngine,
)


class TestJobLedger:
    def test_ledger_creation_and_run_lifecycle(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            ledger = JobLedger(db_path=db_path)

            # Create/start run
            rec = ledger.create_run(
                job_name="TEST_JOB",
                config_hash="cfg_test_123",
                code_commit="commit_abc"
            )
            assert rec.run_id.startswith("RUN-")
            assert rec.status == "RUNNING"
            assert rec.job_name == "TEST_JOB"

            # Complete run
            completed = ledger.complete_run(
                run_id=rec.run_id,
                status="SUCCESS",
                records_fetched=10,
                records_processed=10,
                records_rejected=0,
                sources_attempted=2,
                sources_succeeded=2,
                sources_failed=0,
                data_quality="HEALTHY"
            )
            assert completed.status == "SUCCESS"
            assert completed.records_processed == 10
            assert completed.duration_ms >= 0

            # Verify retrieval
            fetched = ledger.get_run(rec.run_id)
            assert fetched is not None
            assert fetched.run_id == rec.run_id
            assert fetched.sources_succeeded == 2
            assert fetched.config_hash == "cfg_test_123"

            # Check recent runs
            recent = ledger.get_recent_runs(limit=10)
            assert len(recent) == 1
            assert recent[0].run_id == rec.run_id

            # Verify 18 columns exist in SQLite table
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(job_runs)")
            cols = [row[1] for row in cursor.fetchall()]
            conn.close()

            required_cols = [
                "id", "run_id", "job_name", "started_at", "completed_at",
                "duration_ms", "status", "records_fetched", "records_processed",
                "records_rejected", "sources_attempted", "sources_succeeded",
                "sources_failed", "data_quality", "error_message",
                "config_hash", "code_commit", "created_at"
            ]
            for c in required_cols:
                assert c in cols, f"Missing required column {c} in job_runs table"


class TestMarketAndInternationalCollection:
    def test_market_collector_structure(self):
        res = MarketCloseCollector.collect_all_benchmarks()
        assert "timestamp" in res
        assert "quotes" in res
        quotes = res["quotes"]
        assert "NIFTY 50" in quotes
        assert "BANK NIFTY" in quotes
        assert "INDIA VIX" in quotes
        for name, q in quotes.items():
            assert "price" in q
            assert "quality" in q
            assert "market_timestamp" in q

    def test_international_collector_structure(self):
        res = InternationalDataCollector.collect_all()
        assert "timestamp" in res
        assert "quotes" in res
        quotes = res["quotes"]
        assert len(quotes) >= 15
        assert "S&P 500" in quotes
        assert "NASDAQ Composite" in quotes
        assert "Nikkei 225" in quotes
        assert "US 10Y Yield" in quotes
        assert "USD/INR" in quotes


class TestCommodityCollection:
    def test_commodity_collector_conversions(self):
        res = CommodityDataCollector.collect_precious_metals()
        assert "gold" in res
        assert "silver" in res
        assert "energy_and_metals" in res
        assert "usd_inr_exchange_rate" in res

        gold = res["gold"]
        assert "price_usd_oz" in gold
        assert "price_inr" in gold
        assert "quality" in gold

        # Conversion formula verification: (USD/oz / 31.1035) * 10 * USD_INR
        usd_inr = res["usd_inr_exchange_rate"]
        expected_inr_10g = (gold["price_usd_oz"] / 31.1034768) * 10 * usd_inr
        # Allow minor difference (<25 INR out of ~135,000 INR) due to unrounded float vs rounded float inputs
        assert abs(gold["price_inr"] - expected_inr_10g) < 25.0

        silver = res["silver"]
        assert "price_usd_oz" in silver
        assert "price_inr" in silver
        expected_inr_kg = (silver["price_usd_oz"] / 31.1034768) * 1000 * usd_inr
        assert abs(silver["price_inr"] - expected_inr_kg) < 100.0


class TestNewsIntelligence:
    def test_news_collection_and_fields(self):
        articles = NewsIntelligenceCollector.collect_and_analyze(max_articles_per_category=2)
        assert len(articles) > 0

        # Verify article attributes
        for a in articles:
            assert isinstance(a, NewsArticleRecord)
            assert a.article_id.startswith(("NEWS-", "ART-"))
            assert a.headline
            assert a.content_hash
            assert a.sentiment in ["POSITIVE", "NEGATIVE", "NEUTRAL"]
            assert a.impact in ["HIGH", "MEDIUM", "LOW"]


class TestOvernightIntelligence:
    def test_synthesis_generation(self):
        mock_mkt = {"quotes": {"NIFTY 50": {"price": 25481.3, "change_pct": 0.64}}}
        mock_intl = {"quotes": {
            "S&P 500": {"price": 5580.0, "change_pct": 0.45, "region": "US"},
            "NASDAQ Composite": {"price": 19500.0, "change_pct": 0.60, "region": "US"},
            "Nikkei 225": {"price": 38200.0, "change_pct": -0.20, "region": "ASIA"},
            "USD/INR": {"price": 83.92, "change_pct": 0.04, "region": "FX"}
        }}
        mock_comm = {
            "gold": {"price_usd_oz": 4465.0, "price_inr": 136500.0, "change_pct": 0.48},
            "silver": {"price_usd_oz": 68.67, "price_inr": 209900.0, "change_pct": 0.32},
            "energy_and_metals": {"BRENT_CRUDE": {"price": 71.49, "change_pct": -0.82}},
            "usd_inr_exchange_rate": 83.92
        }
        mock_news = [
            {
                "article_id": "NEWS-001",
                "headline": "L&T reports robust Q1 order inflow and margin expansion",
                "source": "Moneycontrol",
                "url": "https://example.com/1",
                "published_at": "2026-09-09T14:00:00Z",
                "ingested_at": "2026-09-09T14:05:00Z",
                "analyzed_at": "2026-09-09T14:05:10Z",
                "content_hash": "hash123",
                "event_type": "EARNINGS_BEAT",
                "sentiment": "POSITIVE",
                "impact": "HIGH",
                "surprise": "+1.8",
                "affected_assets": ["LT.NS"],
                "category": "Companies",
                "region": "India",
                "summary": "Strong Q1 performance",
                "full_text_snippet": "L&T quarterly profits increased significantly..."
            }
        ]

        report = OvernightIntelligenceEngine.synthesize_intelligence(
            market_data=mock_mkt,
            international_data=mock_intl,
            commodity_data=mock_comm,
            news_articles=mock_news
        )
        assert report.india_opening_bias in ["BULLISH", "BEARISH", "NEUTRAL"]
        assert 0.0 <= report.opening_bias_confidence_pct <= 100.0
        assert len(report.scenarios) == 3
        scenario_names = [s.get("scenario_name", "") for s in report.scenarios]
        assert "BULL_CASE" in scenario_names
        assert "BASE_CASE" in scenario_names
        assert "BEAR_CASE" in scenario_names
        assert len(report.key_risks) >= 2
        assert len(report.evidence_trail) > 0


class TestScheduler:
    def test_schedule_calculations(self):
        scheduler = OvernightScheduler()
        info = scheduler.get_schedule_window_info()
        assert isinstance(info, ScheduleWindow)
        assert info.next_run_ist.endswith("IST")
        assert "UTC" in info.next_run_utc or "+00:00" in info.next_run_utc or "Z" in info.next_run_utc
        assert info.cron_utc == "30 0,12,15,18,21 * * *"


class TestWebIntegrationAndPlaceholders:
    def test_index_html_nav_and_placeholders(self):
        html_path = Path("web_app/index.html")
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")

        # Verify Nav links exist
        assert 'data-tab="news"' in content
        assert 'data-tab="overnight"' in content
        assert 'data-tab="jobs"' in content

        # Verify View panels exist
        assert 'id="view-news"' in content
        assert 'id="view-overnight"' in content
        assert 'id="view-jobs"' in content

        # Verify Modals exist
        assert 'id="news-modal-backdrop"' in content
        assert 'id="job-modal-backdrop"' in content

        # Verify Market strip items exist
        assert 'id="strip-gold-price"' in content
        assert 'id="strip-silver-price"' in content
        assert 'id="strip-crude-price"' in content

        # Verify static placeholders removed
        assert "ALL SYSTEMS RECONCILED" not in content, "Static placeholder 'ALL SYSTEMS RECONCILED' must be removed"
        assert "Dual-feed reconciled" not in content, "Static placeholder 'Dual-feed reconciled' must be removed"

    def test_app_js_routing_and_handlers(self):
        app_path = Path("web_app/app.js")
        assert app_path.exists()
        content = app_path.read_text(encoding="utf-8")

        # Check routing and renderers
        assert "renderNewsPage" in content
        assert "renderOvernightIntelligencePage" in content
        assert "renderJobsPage" in content
        assert "openNewsModal" in content
        assert "openJobModal" in content
        assert "filterNewsCategory" in content
        assert "filterJobsStatus" in content

    def test_data_json_and_data_js_consistency(self):
        data_json_path = Path("web_app/data.json")
        data_js_path = Path("web_app/data.js")
        assert data_json_path.exists()
        assert data_js_path.exists()

        with open(data_json_path) as f:
            d = json.load(f)

        assert "job_runs_ledger" in d
        assert "next_scheduled_runs" in d
        assert "commodities" in d
        assert "news_intelligence" in d
        assert "overnight_intelligence" in d

        # Commodities check
        gold = d["commodities"]["gold"]
        assert gold["price_usd_oz"] > 0
        assert gold["price_inr"] > 0
        silver = d["commodities"]["silver"]
        assert silver["price_usd_oz"] > 0
        assert silver["price_inr"] > 0


class TestV361SpecificRequirements:
    """Verifies the four explicit user-requested architectural additions for V3.6.1."""

    def test_run_slot_classifications(self):
        """18:00 POST_MARKET, 21:00 OVERNIGHT, 00:00 OVERNIGHT, 03:00 OVERNIGHT, 06:00 PRE_MARKET."""
        from datetime import datetime, timezone
        from event_agent.jobs.scheduler import AfterMarketScheduler

        sched = AfterMarketScheduler()

        # Test each IST slot
        # 18:00 IST = 12:30 UTC
        dt_1800 = datetime(2026, 9, 9, 12, 30, tzinfo=timezone.utc)
        assert sched.classify_run_slot(dt_1800) == "POST_MARKET"

        # 21:00 IST = 15:30 UTC
        dt_2100 = datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc)
        assert sched.classify_run_slot(dt_2100) == "OVERNIGHT"

        # 00:00 IST = 18:30 UTC
        dt_0000 = datetime(2026, 9, 9, 18, 30, tzinfo=timezone.utc)
        assert sched.classify_run_slot(dt_0000) == "OVERNIGHT"

        # 03:00 IST = 21:30 UTC
        dt_0300 = datetime(2026, 9, 9, 21, 30, tzinfo=timezone.utc)
        assert sched.classify_run_slot(dt_0300) == "OVERNIGHT"

        # 06:00 IST = 00:30 UTC
        dt_0600 = datetime(2026, 9, 10, 0, 30, tzinfo=timezone.utc)
        assert sched.classify_run_slot(dt_0600) == "PRE_MARKET"

    def test_evidence_sufficiency_engine(self):
        """Dynamic sufficiency: deficient evidence yields INSUFFICIENT_EVIDENCE, not manufactured bias."""
        from event_agent.jobs.intelligence_collection import OvernightIntelligenceEngine

        # Case 1: Deficient evidence (< configured minimum 3 observations)
        empty_intel = OvernightIntelligenceEngine.synthesize_intelligence(
            market_data={"quotes": {}},
            international_data={"quotes": {}},
            commodity_data={"gold": {}, "silver": {}, "energy_and_metals": {}},
            news_articles=[],
            min_configured_evidence=3,
            min_configured_sources=2,
        )
        assert empty_intel.is_evidence_sufficient is False
        assert empty_intel.india_opening_bias == "INSUFFICIENT_EVIDENCE"
        assert empty_intel.opening_bias_confidence_pct == 0.0

        # Case 2: Sufficient evidence (>= 3 observations and >= 2 independent sources)
        mock_market = {"quotes": {"NIFTY 50": {"change_pct": -0.5, "price": 23450}}}
        mock_intl = {
            "quotes": {
                "S&P 500": {"asset_name": "S&P 500", "change_pct": 0.5, "price": 5500, "market_timestamp": "2026-09-09T14:00:00Z"},
                "NASDAQ Composite": {"asset_name": "NASDAQ Composite", "change_pct": 0.8, "price": 17500, "market_timestamp": "2026-09-09T14:00:00Z"},
                "USD/INR": {"asset_name": "USD/INR", "change_pct": -0.1, "price": 84.0, "market_timestamp": "2026-09-09T14:00:00Z"},
            }
        }
        mock_comm = {
            "energy_and_metals": {
                "BRENT_CRUDE": {"asset": "BRENT_CRUDE", "change_pct": -1.2, "price": 82.0},
            }
        }
        suff_intel = OvernightIntelligenceEngine.synthesize_intelligence(
            market_data=mock_market,
            international_data=mock_intl,
            commodity_data=mock_comm,
            news_articles=[],
            min_configured_evidence=3,
            min_configured_sources=2,
        )
        assert suff_intel.is_evidence_sufficient is True
        assert suff_intel.india_opening_bias in ["BULLISH", "BEARISH", "NEUTRAL"]
        assert len(suff_intel.evidence_indicators) >= 3

    def test_deterministic_replay_and_hierarchy(self):
        """Ensures parent scheduler run tracks children and bitwise replay reconstructs state."""
        from event_agent.jobs.job_ledger import JobLedger

        ledger = JobLedger(enable_supabase=False)
        runs = ledger.get_recent_runs(limit=100)
        parent_sched = next((r for r in runs if "SCHED-" in r.run_id), None)
        assert parent_sched is not None, "A SCHEDULER parent run must exist in ledger"

        # Verify child runs link to parent
        children = ledger.get_child_runs(parent_sched.run_id)
        assert len(children) >= 1

        # Verify deterministic replay capability
        replay = ledger.replay_run(parent_sched.run_id)
        assert replay["status"] == "REPRODUCED"
        assert replay["deterministic_match"] is True
        assert "snapshot" in replay
        assert "config_hash" in replay
        assert "code_commit" in replay
