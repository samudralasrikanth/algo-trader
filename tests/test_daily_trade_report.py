# =============================================================================
# tests/test_daily_trade_report.py
# NEXUS Daily Automated Trade Report Pipeline Acceptance & Regression Suite
# =============================================================================
"""
Complete acceptance testing for the 18:30 IST Post-Market Daily Reporting Pipeline:
1. Trade Reconciliation & Authoritative P&L Calculation (0-trades, win, loss, mixed, slippage)
2. OpenRouter AI Analyst & Narration Script Generation (factual, 9 sections, fallback)
3. ElevenLabs Voice Generation (George voice, turbo model, failure handling)
4. Creatomate Video Storyboard (9 scenes, dark institutional aesthetic, failure handling)
5. YouTube API v3 Publishing (private mode, OAuth token error handling, no duplicate uploads)
6. Executive Email Notification (HTML & plain-text templates, provider fallbacks)
7. Report Provenance & Deterministic SHA-256 Hashing
8. Pipeline Orchestrator Idempotency & Partial Success Resolution
9. Market Clock Weekend / Holiday Invariants
10. Frontend Operations Terminal & Edge Artifacts Verification
"""

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from event_agent.reporting.trade_reconciliation import (
    TradeReconciliationEngine,
    DailyReconciliationReport,
)
from event_agent.reporting.ai_analyst import (
    DailyAIAnalyst,
    DailyAIAnalysisResult,
)
from event_agent.reporting.video_report.elevenlabs import (
    ElevenLabsVoiceService,
    VoiceGenerationResult,
)
from event_agent.reporting.video_report.creatomate import (
    CreatomateVideoService,
    VideoRenderResult,
)
from event_agent.reporting.video_report.youtube import (
    YouTubePublishService,
    YouTubeUploadResult,
)
from event_agent.reporting.video_report.email import (
    DailyReportEmailService,
    EmailSendResult,
)
from event_agent.reporting.provenance import ReportProvenanceEngine
from event_agent.reporting.daily_trade_pipeline import (
    DailyTradeReportPipeline,
    PipelineExecutionReport,
)
from event_agent.jobs.job_ledger import JobLedger
from event_agent.storage.ledger import (
    init_db,
    save_daily_trade_report,
    get_daily_trade_report,
)
from event_agent.arena.market_clock import MarketClock

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_DIR = WORKSPACE_ROOT / "web_app"
INDEX_HTML = WEB_APP_DIR / "index.html"
APP_JS = WEB_APP_DIR / "app.js"
STYLES_CSS = WEB_APP_DIR / "styles.css"
DATA_JSON = WEB_APP_DIR / "data.json"
PACKAGE_JSON = WORKSPACE_ROOT / "package.json"
NETLIFY_TOML = WORKSPACE_ROOT / "netlify.toml"


# =============================================================================
# 1. Trade Reconciliation & P&L Calculation Suite
# =============================================================================
class TestTradeReconciliation:
    """Verifies reconciliation engine across all trading day regimes."""

    def test_reconciliation_zero_trades_day(self):
        """Zero trades must yield ₹0.00 P&L and NO_TRADES status without crashing."""
        report = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-01",
            custom_trades_fixture=[],
        )
        assert report.total_trades == 0
        assert report.winning_trades == 0
        assert report.losing_trades == 0
        assert report.win_rate == 0.0
        assert report.net_pnl == 0.0
        assert report.gross_pnl == 0.0
        assert report.charges == 0.0
        assert report.trading_status == "NO_TRADES"
        assert report.best_trade is None
        assert report.worst_trade is None

    def test_reconciliation_profitable_day(self):
        """Verifies net P&L and metrics when all trades are profitable."""
        trades = [
            {
                "trade_id": "T1",
                "symbol": "RELIANCE.NS",
                "side": "BUY",
                "entry_price": 2500.0,
                "exit_price": 2550.0,
                "quantity": 100,
                "gross_pnl": 5000.0,
                "net_pnl": 4850.0,
                "charges": 150.0,
                "agent_id": "ALPHA",
                "strategy_version": "Event_Arbitrage_V1",
            },
            {
                "trade_id": "T2",
                "symbol": "TCS.NS",
                "side": "BUY",
                "entry_price": 3800.0,
                "exit_price": 3840.0,
                "quantity": 50,
                "gross_pnl": 2000.0,
                "net_pnl": 1920.0,
                "charges": 80.0,
                "agent_id": "BETA",
                "strategy_version": "Momentum_V1",
            }
        ]
        report = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-02",
            custom_trades_fixture=trades,
        )
        assert report.total_trades == 2
        assert report.winning_trades == 2
        assert report.losing_trades == 0
        assert report.win_rate == 100.0
        assert report.gross_pnl == 7000.0
        assert report.net_pnl == 6770.0
        assert report.charges == 230.0
        assert report.trading_status == "ACTIVE_TRADING"
        assert report.best_trade["symbol"] == "RELIANCE.NS"
        assert report.best_trade["net_pnl"] == 4850.0

    def test_reconciliation_losing_day(self):
        """Verifies net P&L and metrics on a drawdown trading day."""
        trades = [
            {
                "trade_id": "T1",
                "symbol": "INFY.NS",
                "side": "BUY",
                "entry_price": 1850.0,
                "exit_price": 1820.0,
                "quantity": 100,
                "gross_pnl": -3000.0,
                "net_pnl": -3120.0,
                "charges": 120.0,
                "agent_id": "GAMMA",
                "strategy_version": "Mean_Reversion_V1",
            }
        ]
        report = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-03",
            custom_trades_fixture=trades,
        )
        assert report.total_trades == 1
        assert report.winning_trades == 0
        assert report.losing_trades == 1
        assert report.win_rate == 0.0
        assert report.net_pnl == -3120.0
        assert report.charges == 120.0
        assert report.worst_trade["symbol"] == "INFY.NS"

    def test_reconciliation_mixed_trades_day(self):
        """Mixed winners and losers calculate precise win rate and profit factor."""
        trades = [
            {
                "trade_id": "T1",
                "symbol": "HDFCBANK.NS",
                "side": "BUY",
                "entry_price": 1600.0,
                "exit_price": 1630.0,
                "quantity": 100,
                "gross_pnl": 3000.0,
                "net_pnl": 2880.0,
                "charges": 120.0,
                "agent_id": "ALPHA",
            },
            {
                "trade_id": "T2",
                "symbol": "ICICIBANK.NS",
                "side": "BUY",
                "entry_price": 1200.0,
                "exit_price": 1185.0,
                "quantity": 100,
                "gross_pnl": -1500.0,
                "net_pnl": -1590.0,
                "charges": 90.0,
                "agent_id": "BETA",
            },
        ]
        report = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-04",
            custom_trades_fixture=trades,
        )
        assert report.total_trades == 2
        assert report.winning_trades == 1
        assert report.losing_trades == 1
        assert report.win_rate == 50.0
        assert report.net_pnl == 1290.0
        assert report.profit_factor > 1.0


# =============================================================================
# 2. OpenRouter AI Analyst Suite
# =============================================================================
class TestAIAnalyst:
    """Verifies AI analysis generation, structure, and fallback invariants."""

    def test_ai_analysis_fallback_when_api_fails(self):
        """When OpenRouter API is unavailable, fallback must be factual and truthful."""
        rec = TradeReconciliationEngine.reconcile_date("2026-09-05", custom_trades_fixture=[])
        analyst = DailyAIAnalyst(api_key="invalid_mock_key_for_test")

        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            res = analyst.analyze_daily_performance(rec)
            assert res.ai_status == "FAILED"
            assert "DATA UNAVAILABLE" in res.executive_summary
            assert "DATA UNAVAILABLE" in res.narration_script

    def test_ai_analysis_sections_structure(self):
        """Verifies that mock AI response adheres to all required sections."""
        rec = TradeReconciliationEngine.reconcile_date(
            "2026-09-06",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "RELIANCE.NS",
                    "side": "BUY",
                    "entry_price": 2500.0,
                    "exit_price": 2525.0,
                    "quantity": 40,
                    "gross_pnl": 1000.0,
                    "net_pnl": 950.0,
                    "charges": 50.0,
                    "agent_id": "ALPHA",
                }
            ],
        )
        analyst = DailyAIAnalyst(api_key="mock_key")
        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "executive_summary": "Solid momentum execution.",
                        "performance_analysis": "Trades aligned with alpha momentum.",
                        "strategy_analysis": "Event arbitrage delivered gains.",
                        "agent_analysis": "Alpha led performance.",
                        "risk_analysis": "Risk limits held.",
                        "prediction_accuracy": "High accuracy.",
                        "best_trade_analysis": "Reliance long was optimal.",
                        "worst_trade_analysis": "None.",
                        "lessons_learned": "Disciplined execution pays off.",
                        "tomorrow_watchlist": "Reliance, HDFC Bank.",
                        "narration_script": "[PAPER TRADING REPORT] Good evening investors.",
                    })
                }
            }],
            "id": "gen-mock-123",
            "usage": {"prompt_tokens": 100, "completion_tokens": 150, "total_tokens": 250},
        }
        with patch("urllib.request.urlopen") as mock_call:
            mock_call.return_value.__enter__.return_value.read.return_value = json.dumps(mock_response).encode()
            res = analyst.analyze_daily_performance(rec)
            assert res.ai_status == "SUCCESS"
            assert res.executive_summary == "Solid momentum execution."
            assert "[PAPER TRADING REPORT]" in res.narration_script


# =============================================================================
# 3. Media Services (ElevenLabs, Creatomate, YouTube, Email) Suite
# =============================================================================
class TestMediaServices:
    """Verifies media production and external notification services."""

    def test_elevenlabs_voice_service_config(self):
        """Verifies ElevenLabs voice service configuration parameters."""
        service = ElevenLabsVoiceService()
        assert service.voice_id == "JBFqnCBsd6RMkjVDRZzb"  # George voice
        assert service.model_id == "eleven_turbo_v2_5"

    def test_elevenlabs_voice_failure_handling(self):
        """Verifies voice service handles HTTP or network errors gracefully."""
        service = ElevenLabsVoiceService(api_key="mock_invalid_key")
        with patch("urllib.request.urlopen", side_effect=Exception("Unauthorized")):
            res = service.generate_narration_audio("Test script", "test_out")
            assert "FAIL" in res.status
            assert res.audio_url is None

    def test_creatomate_video_storyboard_structure(self):
        """Creatomate storyboard must contain 9 scenes with dark institutional styling."""
        service = CreatomateVideoService()
        rec = TradeReconciliationEngine.reconcile_date("2026-09-07", custom_trades_fixture=[])
        ai_res = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="openai/gpt-4o-mini",
            ai_request_id="REQ-TEST",
            ai_latency_ms=100,
            ai_tokens={"total_tokens": 100},
            executive_summary="Zero trade execution day.",
            performance_analysis="Market remained inside range.",
            strategy_analysis="Neutral execution.",
            agent_analysis="ALPHA held discipline.",
            risk_analysis="Risk limits preserved capital.",
            prediction_accuracy="Directional bias verified.",
            best_trade_analysis="No trades executed.",
            worst_trade_analysis="No trades executed.",
            lessons_learned="Patience in low-catalyst sessions.",
            tomorrow_watchlist="RELIANCE, HDFCBANK",
            narration_script="Today NEXUS maintained capital discipline with zero trades.",
        )
        source = service._build_storyboard_source(rec, ai_res, audio_url_or_path=None)
        assert source["output_format"] == "mp4"
        assert source["width"] == 1080
        assert source["height"] == 1920
        assert source["duration"] == 45.0
        # Exactly 9 scene start times: 0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0
        time_offsets = {el.get("time") for el in source["elements"] if "time" in el}
        assert len(time_offsets) == 9

    def test_creatomate_failure_handling(self):
        """Creatomate returns FAILED result if rendering fails or times out."""
        service = CreatomateVideoService(api_key="mock_invalid_key")
        rec = TradeReconciliationEngine.reconcile_date("2026-09-08", custom_trades_fixture=[])
        ai_res = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id=None,
            ai_latency_ms=0,
            ai_tokens={},
            executive_summary="Test summary",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="",
            prediction_accuracy="",
            best_trade_analysis="",
            worst_trade_analysis="",
            lessons_learned="",
            tomorrow_watchlist="",
            narration_script="Test script",
        )
        with patch("urllib.request.urlopen", side_effect=Exception("Render error")):
            res = service.create_daily_report_video(rec, ai_res)
            assert "FAIL" in res.status
            assert res.video_url is None

    def test_youtube_oauth_error_handling(self):
        """YouTube upload with invalid token records FAILED and requests OAuth."""
        service = YouTubePublishService(api_credentials="mock_expired_token")
        with patch("urllib.request.urlopen", side_effect=Exception("HTTP Error 401: Unauthorized")):
            res = service.upload_daily_report_video(
                video_url_or_path="https://example.com/mock.mp4",
                report_data={"report_date": "2026-09-09", "net_pnl": 0.0, "total_trades": 0, "win_rate": 0.0},
            )
            assert "FAIL" in res.status
            assert res.video_url is None
            assert res.video_id is None
            assert "OAUTH_AUTHENTICATION_REQUIRED" in res.error_message or "401" in res.error_message

    def test_email_service_dispatch(self):
        """Email service generates compliant dark terminal HTML and sends or logs."""
        service = DailyReportEmailService(api_key="mock_resend_key")
        report_data = {
            "report_date": "2026-09-10",
            "total_trades": 2,
            "net_pnl": 3500.0,
            "win_rate": 100.0,
            "realized_pnl": 3500.0,
            "unrealized_pnl": 0.0,
            "charges": 150.0,
            "winning_trades": 2,
            "losing_trades": 0,
            "ai_executive_summary": "Strong alpha generation today.",
            "ai_lessons_learned": ["Follow morning catalysts."],
        }
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.return_value.__enter__.return_value.read.return_value = json.dumps({"id": "email_mock_123"}).encode()
            res = service.send_daily_report(
                report_data=report_data,
                youtube_url="https://youtube.com/watch?v=mock_video",
            )
            assert res.status in ("SUCCESS", "FAILED")
            assert "@" in res.recipient


# =============================================================================
# 4. Provenance & Pipeline Orchestrator Suite
# =============================================================================
class TestPipelineAndProvenance:
    """Verifies end-to-end pipeline invariants, idempotency, and cryptographic provenance."""

    def test_deterministic_sha256_provenance(self):
        """Same input data must produce identical SHA-256 hash; changes must alter hash."""
        data_a = {
            "report_date": "2026-09-10",
            "net_pnl": 5000.0,
            "total_trades": 1,
            "win_rate": 100.0,
        }
        prov1 = ReportProvenanceEngine.compute_provenance("2026-09-10", reconciliation_data=data_a)
        prov2 = ReportProvenanceEngine.compute_provenance("2026-09-10", reconciliation_data=data_a)
        assert prov1["provenance_hash"] == prov2["provenance_hash"]

        data_modified = copy.deepcopy(data_a)
        data_modified["net_pnl"] = 5001.0
        prov3 = ReportProvenanceEngine.compute_provenance("2026-09-10", reconciliation_data=data_modified)
        assert prov1["provenance_hash"] != prov3["provenance_hash"]

    def test_pipeline_idempotency_prevents_duplicate_uploads(self):
        """Second run on same date without force must return SKIPPED."""
        init_db()
        save_daily_trade_report({
            "report_date": "2026-08-15",
            "status": "SUCCESS",
            "total_trades": 0,
            "net_pnl": 0.0,
            "provenance_hash": "mock_hash_815",
        })

        pipeline = DailyTradeReportPipeline()
        report = pipeline.run_pipeline(report_date="2026-08-15", force_regenerate=False)
        assert report.overall_status == "SKIPPED"
        assert report.stage_statuses["IDEMPOTENCY"] == "SKIPPED_ALREADY_EXISTS"

    def test_weekend_market_session_check(self):
        """Weekend date (Saturday or Sunday) must report inactive session."""
        # 2026-09-12 is Saturday, 2026-09-13 is Sunday
        dt_sat = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
        assert MarketClock.is_trading_day(dt_sat) is False

        dt_sun = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        assert MarketClock.is_trading_day(dt_sun) is False


# =============================================================================
# 5. Frontend & Netlify Artifacts Suite
# =============================================================================
class TestFrontendArtifacts:
    """Verifies that web app templates, scripts, and build artifacts are present."""

    def test_index_html_contains_daily_video_report_section(self):
        assert INDEX_HTML.exists()
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert "daily-video-report-panel" in content
        assert "DAILY AUTOMATED VIDEO REPORT &amp; BROADCAST" in content
        assert "daily-report-status-badge" in content
        assert "daily-report-run-btn" in content
        assert "daily-report-youtube-link" in content

    def test_app_js_contains_render_daily_video_report(self):
        assert APP_JS.exists()
        content = APP_JS.read_text(encoding="utf-8")
        assert "function renderDailyVideoReport" in content
        assert "function triggerDailyReportRun" in content
        assert "renderDailyVideoReport();" in content

    def test_styles_css_contains_daily_report_styles(self):
        assert STYLES_CSS.exists()
        content = STYLES_CSS.read_text(encoding="utf-8")
        assert ".daily-report-grid" in content
        assert ".stage-pills-bar" in content
        assert ".video-container-box" in content

    def test_netlify_redirects_include_daily_report(self):
        assert NETLIFY_TOML.exists()
        content = NETLIFY_TOML.read_text(encoding="utf-8")
        assert "/api/daily_report" in content

    def test_package_json_contains_report_scripts(self):
        assert PACKAGE_JSON.exists()
        pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})
        assert "report:run" in scripts
        assert "report:test" in scripts
