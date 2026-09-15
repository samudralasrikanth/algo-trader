# =============================================================================
# tests/test_content_strategy_and_thumbnail.py
# NEXUS Content Intelligence, Narrative Short & Automatic Thumbnail Test Suite
# =============================================================================
"""
Tests for:
1. Content Intelligence Engine & Dynamic Theme Selection (7 priority regimes)
2. High-Retention 60-75s Storyboard Narration Script Generation
3. 16:9 Clickable YouTube Thumbnail Specification (6 adaptive templates)
4. Creatomate Static Image & Short Video Source Generation
5. YouTube Custom Thumbnail Upload API with graceful error isolation
6. Deterministic SHA-256 Data Integrity across video and thumbnail
7. End-to-end Daily Trade Pipeline integration with zero manual intervention
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from event_agent.reporting.content_strategy import (
    ContentIntelligenceEngine,
    DailyContentPackage,
)
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
    ThumbnailRenderResult,
)
from event_agent.reporting.video_report.youtube import (
    YouTubePublishService,
    YouTubeUploadResult,
)
from event_agent.reporting.daily_trade_pipeline import (
    DailyTradeReportPipeline,
    PipelineExecutionReport,
)
from event_agent.storage.ledger import (
    init_db,
    save_daily_trade_report,
    get_daily_trade_report,
)


# =============================================================================
# 1. Content Intelligence Engine Suite
# =============================================================================
class TestContentIntelligenceEngine:
    """Verifies content theme priority, story generation, and data integrity."""

    def test_theme_capital_protected_when_risk_blocked_loss(self):
        """When risk manager blocked trades, theme must be CAPITAL_PROTECTED."""
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-10",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "RELIANCE.NS",
                    "side": "BUY",
                    "entry_price": 2500.0,
                    "exit_price": 2545.0,
                    "quantity": 10,
                    "gross_pnl": 450.0,
                    "net_pnl": 450.0,
                    "charges": 0.0,
                    "agent_id": "ALPHA",
                }
            ],
        )
        rec.risk_rejected_count = 2

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="1",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Risk manager intercepted volatility spike.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="Risk filters vetoed 2 sub-optimal trades.",
            prediction_accuracy="",
            best_trade_analysis="",
            worst_trade_analysis="",
            lessons_learned="Risk protection preserved gains.",
            tomorrow_watchlist="RELIANCE",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        assert pkg.content_theme == "CAPITAL_PROTECTED"
        assert pkg.thumbnail_template == "RISK"
        assert "BLOCKED" in pkg.thumbnail_headline or "RISK" in pkg.thumbnail_subheadline

    def test_theme_signal_failure_on_negative_pnl(self):
        """Negative net P&L must trigger SIGNAL_FAILURE without falsifying success."""
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-11",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "INFY.NS",
                    "side": "BUY",
                    "entry_price": 1850.0,
                    "exit_price": 1810.0,
                    "quantity": 100,
                    "gross_pnl": -4000.0,
                    "net_pnl": -4200.0,
                    "charges": 200.0,
                    "agent_id": "GAMMA",
                }
            ],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="2",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Tech sector momentum failed intraday.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="",
            prediction_accuracy="",
            best_trade_analysis="",
            worst_trade_analysis="INFY failed breakout support.",
            lessons_learned="Cut intraday momentum early.",
            tomorrow_watchlist="INFY, TCS",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        assert pkg.content_theme == "SIGNAL_FAILURE"
        assert pkg.thumbnail_template == "RESULT"
        assert pkg.thumbnail_accent_color == "#FF1744"
        assert ("FAILED" in pkg.thumbnail_headline) or ("-" in pkg.thumbnail_subheadline)

    def test_theme_standout_trade_high_single_pnl(self):
        """A single standout trade earning >= ₹3,000 triggers STANDOUT_TRADE."""
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-12",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "TATASTEEL.NS",
                    "side": "BUY",
                    "entry_price": 150.0,
                    "exit_price": 160.0,
                    "quantity": 620,
                    "gross_pnl": 6200.0,
                    "net_pnl": 6200.0,
                    "charges": 0.0,
                    "agent_id": "ALPHA",
                },
                {
                    "trade_id": "T2",
                    "symbol": "SBIN.NS",
                    "side": "BUY",
                    "entry_price": 800.0,
                    "exit_price": 790.0,
                    "quantity": 100,
                    "gross_pnl": -1000.0,
                    "net_pnl": -1000.0,
                    "charges": 0.0,
                    "agent_id": "BETA",
                }
            ],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="3",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Metal breakout delivered standout alpha.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="",
            prediction_accuracy="",
            best_trade_analysis="Tata Steel surged after commodity news.",
            worst_trade_analysis="",
            lessons_learned="Commodity catalysts have high follow-through.",
            tomorrow_watchlist="TATASTEEL, JSWSTEEL",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        assert pkg.content_theme == "STANDOUT_TRADE"
        assert pkg.thumbnail_template == "SIGNAL"
        assert "TATASTEEL" in pkg.thumbnail_subheadline or "TATASTEEL" in pkg.thumbnail_headline

    def test_theme_no_trades_capital_preservation(self):
        """Zero trades must trigger NO_TRADE_PRESERVATION with truthful headline."""
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-13",
            custom_trades_fixture=[],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="4",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Zero catalysts met our confidence threshold.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="",
            prediction_accuracy="",
            best_trade_analysis="",
            worst_trade_analysis="",
            lessons_learned="Sitting on hands is a valid trading strategy.",
            tomorrow_watchlist="NIFTY 50",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        assert pkg.content_theme == "NO_TRADE_PRESERVATION"
        assert pkg.thumbnail_template == "NO_TRADE"
        assert "ZERO" in pkg.thumbnail_headline or "0 TRADES" in pkg.thumbnail_headline or "NO TRADES" in pkg.thumbnail_headline

    def test_narration_script_pacing_and_compliance(self):
        """Script must be 110-170 words, conversational, and contain mandatory paper trading disclaimer."""
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-14",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "RELIANCE.NS",
                    "side": "BUY",
                    "entry_price": 2500.0,
                    "exit_price": 2540.0,
                    "quantity": 100,
                    "gross_pnl": 4050.0,
                    "net_pnl": 4050.0,
                    "charges": 0.0,
                    "agent_id": "ALPHA",
                }
            ],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="5",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Energy sector momentum beat street estimates.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="Risk models approved high-conviction order.",
            prediction_accuracy="",
            best_trade_analysis="Reliance executed cleanly at support.",
            worst_trade_analysis="",
            lessons_learned="Bayesian event weighting correctly amplified signal.",
            tomorrow_watchlist="RELIANCE, HDFCBANK",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        script = pkg.video_script
        words = script.split()
        assert 110 <= len(words) <= 170
        assert "NEXUS" in script
        assert "paper trading" in script.lower() or "not financial advice" in script.lower()
        assert "₹" in script or "rupees" in script.lower() or "4,050" in script

    def test_sha256_deterministic_hash_integrity(self):
        """Content package SHA-256 data hash must be non-empty and deterministic."""
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-15",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "RELIANCE.NS",
                    "side": "BUY",
                    "entry_price": 2500.0,
                    "exit_price": 2510.0,
                    "quantity": 100,
                    "gross_pnl": 1000.0,
                    "net_pnl": 1250.0,
                    "charges": 0.0,
                    "agent_id": "ALPHA",
                }
            ],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="6",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Disciplined session.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="",
            prediction_accuracy="",
            best_trade_analysis="",
            worst_trade_analysis="",
            lessons_learned="",
            tomorrow_watchlist="",
            narration_script="",
        )
        pkg1 = ContentIntelligenceEngine.build_content_package(rec, ai)
        pkg2 = ContentIntelligenceEngine.build_content_package(rec, ai)
        assert pkg1.data_hash == pkg2.data_hash
        assert len(pkg1.data_hash) == 64


# =============================================================================
# 2. Creatomate Video & Thumbnail Generator Suite
# =============================================================================
class TestCreatomateMediaGenerator:
    """Verifies 16:9 thumbnail and 9:16 Short source JSON specifications."""

    def test_thumbnail_source_spec(self):
        """Thumbnail source must be 1280x720, output_format jpg, duration 1.0, and bold elements."""
        service = CreatomateVideoService()
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-16",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "RELIANCE.NS",
                    "side": "BUY",
                    "entry_price": 2500.0,
                    "exit_price": 2554.0,
                    "quantity": 100,
                    "gross_pnl": 5400.0,
                    "net_pnl": 5400.0,
                    "charges": 0.0,
                    "agent_id": "ALPHA",
                }
            ],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="7",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Alpha surge.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="",
            prediction_accuracy="",
            best_trade_analysis="",
            worst_trade_analysis="",
            lessons_learned="",
            tomorrow_watchlist="",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        source = service._build_thumbnail_source(pkg)

        assert source["output_format"] == "jpg"
        assert source["width"] == 1280
        assert source["height"] == 720
        assert source["duration"] == 1.0
        # Check for dominant headline text
        headline_el = next((el for el in source["elements"] if el.get("type") == "text" and el.get("font_size") == 110), None)
        assert headline_el is not None
        assert headline_el["text"] == pkg.thumbnail_headline

    def test_short_video_source_spec(self):
        """Short video source must be 1080x1920, output_format mp4, duration 70.0s, and 8 scenes."""
        service = CreatomateVideoService()
        rec = TradeReconciliationEngine.reconcile_date(
            target_date="2026-09-16",
            custom_trades_fixture=[
                {
                    "trade_id": "T1",
                    "symbol": "TCS.NS",
                    "side": "BUY",
                    "entry_price": 3800.0,
                    "exit_price": 3860.0,
                    "quantity": 50,
                    "gross_pnl": 3000.0,
                    "net_pnl": 3000.0,
                    "charges": 0.0,
                    "agent_id": "ALPHA",
                },
                {
                    "trade_id": "T2",
                    "symbol": "WIPRO.NS",
                    "side": "BUY",
                    "entry_price": 500.0,
                    "exit_price": 493.0,
                    "quantity": 100,
                    "gross_pnl": -700.0,
                    "net_pnl": -700.0,
                    "charges": 0.0,
                    "agent_id": "BETA",
                }
            ],
        )

        ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test",
            ai_request_id="8",
            ai_latency_ms=10,
            ai_tokens={},
            executive_summary="Mixed session with IT outperformance.",
            performance_analysis="",
            strategy_analysis="",
            agent_analysis="",
            risk_analysis="Risk models capped downside on Wipro.",
            prediction_accuracy="",
            best_trade_analysis="TCS long performed as expected.",
            worst_trade_analysis="",
            lessons_learned="Divergence in sector peers requires hedge.",
            tomorrow_watchlist="TCS, INFY",
            narration_script="",
        )
        pkg = ContentIntelligenceEngine.build_content_package(rec, ai)
        source = service._build_storyboard_source(rec, ai, content_package=pkg)

        assert source["output_format"] == "mp4"
        assert source["width"] == 1080
        assert source["height"] == 1920
        assert source["duration"] == 70.0

        # Verify presence of narrative labels across the scenes
        texts = [el.get("text") for el in source["elements"] if el.get("type") == "text"]
        assert any("NEXUS" in t for t in texts if t)
        assert any("STANDOUT TRADE" in t for t in texts if t)
        assert any("WHAT DID AI LEARN" in t for t in texts if t)
        assert any("WHY DID IT WORK" in t for t in texts if t)


# =============================================================================
# 3. YouTube Custom Thumbnail Upload Suite
# =============================================================================
class TestYouTubeThumbnailUpload:
    """Verifies YouTube custom thumbnail upload and independent failure handling."""

    def test_youtube_upload_thumbnail_success(self):
        """When YouTube API accepts custom thumbnail, status is True."""
        service = YouTubePublishService(api_credentials="mock_token")
        with patch.object(service, "get_access_token", return_value=("mock_access_token", None)):
            with patch("urllib.request.urlopen") as mock_url:
                mock_url.return_value.__enter__.return_value.read.return_value = b'{"items": []}'
                ok, err = service.upload_thumbnail(
                    video_id="MOCK_VID_123",
                    thumbnail_url_or_path="https://creatomate.com/mock_thumb.jpg",
                )
                assert ok is True
                assert err is None

    def test_youtube_upload_thumbnail_handles_permissions_failure_gracefully(self):
        """When channel lacks custom thumbnail permissions (403), returns False without crashing."""
        service = YouTubePublishService(api_credentials="mock_token")
        with patch.object(service, "get_access_token", return_value=("mock_access_token", None)):
            with patch("urllib.request.urlopen", side_effect=Exception("HTTP Error 403: Forbidden - custom thumbnails not allowed")):
                ok, err = service.upload_thumbnail(
                    video_id="MOCK_VID_456",
                    thumbnail_url_or_path="https://creatomate.com/mock_thumb.jpg",
                )
                assert ok is False
                assert "Forbidden" in err

    def test_video_upload_with_thumbnail_integration(self):
        """upload_daily_report_video delegates to upload_thumbnail after video insertion."""
        service = YouTubePublishService(api_credentials="mock_token")
        mock_vid_res = {"id": "VID_789"}
        with patch.object(service, "get_access_token", return_value=("mock_access_token", None)):
            with patch("urllib.request.urlopen") as mock_url:
                mock_resp = MagicMock()
                mock_resp.headers = {"Location": "https://upload.googleapis.com/resumable_123"}
                mock_resp.read.return_value = json.dumps(mock_vid_res).encode()
                mock_url.return_value.__enter__.return_value = mock_resp

                with patch.object(service, "upload_thumbnail", return_value=(True, None)):
                    res = service.upload_daily_report_video(
                        video_url_or_path="https://creatomate.com/mock_video.mp4",
                        report_data={"report_date": "2026-09-17"},
                        thumbnail_url_or_path="https://creatomate.com/mock_thumb.jpg",
                    )
                    assert res.status == "SUCCESS"
                    assert res.video_id == "VID_789"
                    assert res.thumbnail_status == "SUCCESS"


# =============================================================================
# 4. End-to-End Orchestration & Ledger Suite
# =============================================================================
class TestDailyTradePipelineIntegration:
    """Verifies end-to-end flow with ContentPackage, Thumbnail, Video, and Ledger persistence."""

    def test_pipeline_full_run_with_thumbnail_and_content_package(self):
        """Pipeline executes all 8 stages, persists thumbnail and content metadata, and updates ledger."""
        init_db()
        fixture = [
            {
                "trade_id": "TRD-E2E-1",
                "symbol": "RELIANCE.NS",
                "side": "BUY",
                "entry_price": 2500.0,
                "exit_price": 2540.0,
                "quantity": 100,
                "gross_pnl": 4000.0,
                "net_pnl": 3820.0,
                "charges": 180.0,
                "agent_id": "ALPHA",
                "strategy_version": "Event_Arbitrage_V1",
                "decision_reason": "Earnings beat expectation",
            }
        ]

        pipeline = DailyTradeReportPipeline()

        # Mock external APIs for deterministic execution
        mock_voice = VoiceGenerationResult(
            status="SUCCESS",
            audio_path="/tmp/mock_audio.mp3",
            audio_url="https://mockcdn.com/audio.mp3",
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            duration_ms=68000,
            file_size_bytes=500000,
        )
        mock_video = VideoRenderResult(
            status="SUCCESS",
            render_id="REND-MOCK-VID",
            video_url="https://creatomate.com/mock_short.mp4",
            duration_seconds=70.0,
        )
        mock_thumb = ThumbnailRenderResult(
            status="SUCCESS",
            render_id="REND-MOCK-THUMB",
            image_url="https://creatomate.com/mock_thumb.jpg",
            template="RESULT",
            headline="+₹3,820",
        )
        mock_yt = YouTubeUploadResult(
            status="SUCCESS",
            video_id="YT-VID-MOCK",
            video_url="https://youtu.be/YT-VID-MOCK",
            title="NEXUS Daily Trade Report — 2026-09-18",
            privacy_status="private",
            thumbnail_status="SUCCESS",
        )

        mock_ai = DailyAIAnalysisResult(
            ai_status="SUCCESS",
            ai_provider="openrouter",
            ai_model="test-mock",
            ai_request_id="REQ-MOCK",
            ai_latency_ms=10,
            ai_tokens={"total_tokens": 100},
            executive_summary="Solid session with Reliance leading momentum alpha.",
            performance_analysis="Positive outcome across disciplined execution.",
            strategy_analysis="Event momentum strategy validated.",
            agent_analysis="Alpha Agent executed cleanly.",
            risk_analysis="TradeGuard 34 gates verified all parameters.",
            prediction_accuracy="98%",
            best_trade_analysis="Reliance breakout was optimal.",
            worst_trade_analysis="None",
            lessons_learned="Maintain disciplined event screening.",
            tomorrow_watchlist="RELIANCE, TCS, INFY",
            narration_script="Disciplined paper trading report.",
        )

        with patch.object(pipeline.ai_analyst, "analyze_daily_performance", return_value=mock_ai), \
             patch.object(pipeline.voice_service, "generate_narration_audio", return_value=mock_voice), \
             patch.object(pipeline.video_service, "create_daily_report_video", return_value=mock_video), \
             patch.object(pipeline.video_service, "create_daily_thumbnail", return_value=mock_thumb), \
             patch.object(pipeline.youtube_service, "upload_daily_report_video", return_value=mock_yt), \
             patch.object(pipeline, "_publish_audio_to_web", return_value="https://nifty50-event-agent.netlify.app/reports/audio/mock.mp3"):

            report = pipeline.run_pipeline(
                report_date="2026-09-18",
                force_regenerate=True,
                custom_trades_fixture=fixture,
                trigger_type="TEST",
            )

            assert report.overall_status in ("SUCCESS", "PARTIAL_SUCCESS")
            assert report.stage_statuses["CONTENT_INTELLIGENCE"] == "SUCCESS"
            assert report.stage_statuses["VIDEO"] == "SUCCESS"
            assert report.stage_statuses["THUMBNAIL"] == "SUCCESS"
            assert report.thumbnail_result is not None
            assert report.thumbnail_result["image_url"] == "https://creatomate.com/mock_thumb.jpg"
            assert report.content_package is not None
            assert report.content_package["content_theme"] in [
                "PROFITABLE_ALPHA",
                "STANDOUT_TRADE",
                "CAPITAL_PROTECTED",
                "AI_CONSENSUS",
                "SIGNAL_FAILURE",
                "NO_TRADE_PRESERVATION",
                "MARKET_CATALYST",
            ]

            # Verify saved record in ledger
            saved = get_daily_trade_report("2026-09-18")
            assert saved is not None
            assert saved["thumbnail_url"] == "https://creatomate.com/mock_thumb.jpg"
            assert saved["thumbnail_template"] == "RESULT"
            assert saved["video_url"] == "https://creatomate.com/mock_short.mp4"
            assert saved["video_duration_seconds"] == 70.0
            assert saved["content_theme"] is not None
            assert saved["provenance_hash"] != "PROVENANCE UNAVAILABLE"
            assert report.data_mode == "TEST_FIXTURE"
            assert saved["data_mode"] == "TEST_FIXTURE"
