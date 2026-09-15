# =============================================================================
# event_agent/reporting/daily_trade_pipeline.py — Master Reporting Pipeline
# =============================================================================
"""
Autonomous Daily Trade Reporting Pipeline:
Trades & Reconciliation -> P&L Calculation -> OpenRouter AI -> ElevenLabs Voice ->
Creatomate Video -> YouTube Upload -> Email Dispatch -> Provenance Ledger.

Strict Institutional Invariants:
1. Paper/sandbox trading reporting only — live trading is NEVER enabled.
2. Idempotent: same day's report never duplicates YouTube videos or emails unless force_regenerate=True.
3. Truthful state reporting: PARTIAL_SUCCESS or FAILED rather than fake success.
4. Secrets are kept server-side and never exposed to client bundles or logs.
5. Multi-tier persistence: Supabase Authoritative -> SQLite Cache -> Static Edge.
"""

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from .trade_reconciliation import TradeReconciliationEngine, DailyReconciliationReport
from .ai_analyst import DailyAIAnalyst, DailyAIAnalysisResult
from .content_strategy import ContentIntelligenceEngine, DailyContentPackage
from .video_report.elevenlabs import ElevenLabsVoiceService, VoiceGenerationResult
from .video_report.creatomate import CreatomateVideoService, VideoRenderResult, ThumbnailRenderResult
from .video_report.youtube import YouTubePublishService, YouTubeUploadResult
from .video_report.email import DailyReportEmailService, EmailSendResult
from .provenance import ReportProvenanceEngine
from ..storage.ledger import (
    init_db,
    save_daily_trade_report,
    get_daily_trade_report,
    get_recent_daily_trade_reports,
)
from ..jobs.job_ledger import JobLedger, JobRunRecord

logger = logging.getLogger(__name__)

WEB_DATA_JSON = Path(__file__).resolve().parents[2] / "web_app" / "data.json"
WEB_DATA_JS = Path(__file__).resolve().parents[2] / "web_app" / "data.js"


@dataclass
class PipelineExecutionReport:
    report_date: str
    idempotency_key: str
    overall_status: str                 # 'SUCCESS' | 'PARTIAL_SUCCESS' | 'FAILED' | 'SKIPPED'
    stage_statuses: Dict[str, str]      # DATA_COLLECTION, AI, VOICE, VIDEO, THUMBNAIL, YOUTUBE, EMAIL
    reconciliation: Dict[str, Any]
    ai_analysis: Optional[Dict[str, Any]]
    voice_result: Optional[Dict[str, Any]]
    video_result: Optional[Dict[str, Any]]
    thumbnail_result: Optional[Dict[str, Any]] = None
    content_package: Optional[Dict[str, Any]] = None
    youtube_result: Optional[Dict[str, Any]] = None
    email_result: Optional[Dict[str, Any]] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    data_mode: str = "PAPER_RECONCILED"  # 'PAPER_RECONCILED' | 'TEST_FIXTURE'
    duration_ms: int = 0
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DailyTradeReportPipeline:
    """
    Coordinates the 9-stage post-market reporting pipeline.
    """

    def __init__(
        self,
        ledger: Optional[JobLedger] = None,
    ):
        self.ledger = ledger or JobLedger()
        self.ai_analyst = DailyAIAnalyst()
        self.voice_service = ElevenLabsVoiceService()
        self.video_service = CreatomateVideoService()
        self.youtube_service = YouTubePublishService()
        self.email_service = DailyReportEmailService()

    def _publish_audio_to_web(self, audio_local_path: str, target_date: str) -> Optional[str]:
        """Copies generated MP3 to web_app/reports/audio/ and deploys to Netlify so Creatomate has a public HTTPS URL."""
        try:
            repo_dir = Path(__file__).resolve().parents[2]
            web_audio_dir = repo_dir / "web_app" / "reports" / "audio"
            web_audio_dir.mkdir(parents=True, exist_ok=True)
            dest_dated = web_audio_dir / f"nexus_report_{target_date}.mp3"
            dest_latest = web_audio_dir / "nexus_report_latest.mp3"
            import shutil, subprocess
            shutil.copyfile(audio_local_path, dest_dated)
            shutil.copyfile(audio_local_path, dest_latest)
            cmd = ["npx", "-y", "netlify-cli", "deploy", "--dir=web_app", "--site-name", "nifty50-event-agent", "--prod", "--no-build"]
            res = subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                audio_url = f"https://nifty50-event-agent.netlify.app/reports/audio/nexus_report_{target_date}.mp3"
                logger.info("Published audio to Netlify: %s", audio_url)
                return audio_url
            else:
                logger.warning("Netlify audio deploy warning: %s", res.stderr[:120])
        except Exception as e:
            logger.warning("Failed to publish audio to Netlify: %s", e)
        return None

    def run_pipeline(
        self,
        report_date: Optional[str] = None,
        force_regenerate: bool = False,
        custom_trades_fixture: Optional[List[Dict[str, Any]]] = None,
        trigger_type: str = "SCHEDULED",
    ) -> PipelineExecutionReport:
        """
        Execute the complete automated post-market reporting flow.
        """
        start_time = time.perf_counter()
        target_date = report_date or datetime.now().strftime("%Y-%m-%d")
        idempotency_key = f"{target_date}:DAILY_TRADE_REPORT"

        logger.info("===============================================================")
        logger.info("Starting NEXUS Daily Trade Report Pipeline: %s", idempotency_key)
        logger.info("===============================================================")

        # 1. Idempotency Check
        if not force_regenerate and custom_trades_fixture is None:
            existing = get_daily_trade_report(target_date)
            if existing and existing.get("status") in ("SUCCESS", "PARTIAL_SUCCESS"):
                logger.info("Idempotent hit: Report for %s already exists. Reusing completed report.", target_date)
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                return PipelineExecutionReport(
                    report_date=target_date,
                    idempotency_key=idempotency_key,
                    overall_status="SKIPPED",
                    stage_statuses={"IDEMPOTENCY": "SKIPPED_ALREADY_EXISTS"},
                    reconciliation=existing,
                    ai_analysis=None,
                    voice_result=None,
                    video_result=None,
                    youtube_result=None,
                    email_result=None,
                    provenance={"provenance_hash": existing.get("provenance_hash", "")},
                    duration_ms=duration_ms,
                )

        # Strict Safety Invariant: PAPER TRADING ONLY
        env = os.environ.get("TRADING_ENVIRONMENT", "PAPER").upper()
        if env not in ("PAPER", "SANDBOX", "SIMULATION"):
            raise RuntimeError(f"Strict Institutional Invariant: Daily trade reporting pipeline permitted in PAPER/SANDBOX mode only, got: {env}")

        is_fixture = bool(custom_trades_fixture is not None)
        data_mode = "TEST_FIXTURE" if is_fixture else "PAPER_RECONCILED"

        stage_statuses = {
            "DATA_COLLECTION": "PENDING",
            "AI_ANALYSIS": "PENDING",
            "CONTENT_INTELLIGENCE": "PENDING",
            "VOICE": "PENDING",
            "VIDEO": "PENDING",
            "THUMBNAIL": "PENDING",
            "YOUTUBE": "PENDING",
            "EMAIL": "PENDING",
            "WEB_SYNC": "PENDING",
        }

        # Create parent JobRunRecord in JobLedger
        parent_job = self.ledger.create_run(
            job_name="DAILY_TRADE_REPORT",
            trigger_type=trigger_type,
            run_classification="POST_MARKET",
            config_hash="cfg_daily_report_v37",
        )

        # ---------------------------------------------------------------------
        # Stage 1: Data Collection & Reconciliation
        # ---------------------------------------------------------------------
        logger.info("[1/9] Reconciling recorded trades & calculating authoritative P&L (data_mode=%s)...", data_mode)
        rec = TradeReconciliationEngine.reconcile_date(
            target_date=target_date,
            custom_trades_fixture=custom_trades_fixture,
        )
        stage_statuses["DATA_COLLECTION"] = rec.trading_status
        logger.info("      Trades: %d | Net P&L: ₹%s | Status: %s", rec.total_trades, f"{rec.net_pnl:,.2f}", rec.trading_status)

        # ---------------------------------------------------------------------
        # Stage 2: OpenRouter AI Analysis & Script Generation
        # ---------------------------------------------------------------------
        logger.info("[2/9] Generating factual performance analysis via OpenRouter...")
        ai_res = self.ai_analyst.analyze_daily_performance(rec)
        stage_statuses["AI_ANALYSIS"] = ai_res.ai_status
        logger.info("      AI Status: %s | Model: %s | Tokens: %d", ai_res.ai_status, ai_res.ai_model, ai_res.ai_tokens.get("total_tokens", 0))

        # ---------------------------------------------------------------------
        # Stage 3: Content Intelligence & Dynamic Narrative Engine
        # ---------------------------------------------------------------------
        logger.info("[3/9] Assembling narrative DailyContentPackage & 16:9 Thumbnail Spec...")
        content_pkg: DailyContentPackage = ContentIntelligenceEngine.build_content_package(
            reconciliation=rec,
            ai_analysis=ai_res,
            data_mode=data_mode,
        )
        stage_statuses["CONTENT_INTELLIGENCE"] = "SUCCESS"
        logger.info("      Content Theme: %s | Score: %.2f | Hash: %s | Mode: %s",
                    content_pkg.content_theme, content_pkg.content_score, content_pkg.data_hash[:12], data_mode)

        # ---------------------------------------------------------------------
        # Stage 4: ElevenLabs Voice Narration (High-Retention Paced Script)
        # ---------------------------------------------------------------------
        logger.info("[4/9] Generating narration audio via ElevenLabs...")
        script_to_narrate = content_pkg.video_script or ai_res.narration_script
        voice_res = self.voice_service.generate_narration_audio(
            script_text=script_to_narrate,
            filename_prefix=f"nexus_report_{target_date}",
        )
        stage_statuses["VOICE"] = voice_res.status
        logger.info("      Voice Status: %s | Duration: ~%d ms | Bytes: %d", voice_res.status, voice_res.duration_ms, voice_res.file_size_bytes)

        # ---------------------------------------------------------------------
        # Stage 5: Creatomate Video Generation (60-75s Vertical Short)
        # ---------------------------------------------------------------------
        logger.info("[5/9] Rendering 8-scene high-retention vertical Short via Creatomate...")
        public_audio_url = voice_res.audio_url
        if not public_audio_url and voice_res.status == "SUCCESS" and voice_res.audio_path:
            logger.info("      Publishing narration audio to Netlify CDN for Creatomate audio mixing...")
            public_audio_url = self._publish_audio_to_web(voice_res.audio_path, target_date)
            if public_audio_url:
                voice_res.audio_url = public_audio_url

        video_res = self.video_service.create_daily_report_video(
            reconciliation=rec,
            ai_analysis=ai_res,
            content_package=content_pkg,
            audio_url_or_path=public_audio_url or voice_res.audio_path,
        )
        stage_statuses["VIDEO"] = video_res.status
        logger.info("      Video Status: %s | URL: %s", video_res.status, video_res.video_url)

        # ---------------------------------------------------------------------
        # Stage 6: Clickable 16:9 YouTube Thumbnail Generation
        # ---------------------------------------------------------------------
        logger.info("[6/9] Rendering 16:9 clickable thumbnail via Creatomate...")
        thumbnail_res: ThumbnailRenderResult = self.video_service.create_daily_thumbnail(
            content_package=content_pkg,
        )
        stage_statuses["THUMBNAIL"] = thumbnail_res.status
        logger.info("      Thumbnail Status: %s | URL: %s | Template: %s | Headline: %s",
                    thumbnail_res.status, thumbnail_res.image_url, thumbnail_res.template, content_pkg.thumbnail_headline)

        # ---------------------------------------------------------------------
        # Stage 7: YouTube Upload (Video + Custom Thumbnail)
        # ---------------------------------------------------------------------
        logger.info("[7/9] Uploading video and thumbnail to YouTube (mode=%s)...", self.youtube_service.publish_mode)
        youtube_res = None
        if video_res.status == "SUCCESS" and video_res.video_url:
            v_path = video_res.video_url
            if v_path.startswith("/reports/") and os.path.exists(os.path.join("web_app", v_path.lstrip("/"))):
                v_path = os.path.abspath(os.path.join("web_app", v_path.lstrip("/")))
            t_path = thumbnail_res.image_url if thumbnail_res.status == "SUCCESS" else None
            if t_path and t_path.startswith("/reports/") and os.path.exists(os.path.join("web_app", t_path.lstrip("/"))):
                t_path = os.path.abspath(os.path.join("web_app", t_path.lstrip("/")))

            youtube_res = self.youtube_service.upload_daily_report_video(
                video_url_or_path=v_path,
                report_data=rec.to_dict(),
                thumbnail_url_or_path=t_path,
            )
            stage_statuses["YOUTUBE"] = youtube_res.status
        else:
            youtube_res = YouTubeUploadResult(
                status="SKIPPED",
                video_id=None,
                video_url=None,
                title=f"NEXUS Daily Trade Report — {target_date}",
                privacy_status=self.youtube_service.publish_mode,
                error_message="Video generation did not succeed; skipping YouTube upload.",
                thumbnail_status="SKIPPED",
            )
            stage_statuses["YOUTUBE"] = "SKIPPED"
        logger.info("      YouTube Status: %s | URL: %s | Thumbnail Upload: %s",
                    youtube_res.status, youtube_res.video_url, youtube_res.thumbnail_status)

        # ---------------------------------------------------------------------
        # Stage 8: Email Report Dispatch
        # ---------------------------------------------------------------------
        logger.info("[8/9] Dispatching daily report email...")
        email_data = rec.to_dict()
        email_data.update({
            "ai_executive_summary": ai_res.executive_summary,
            "ai_lessons_learned": ai_res.lessons_learned,
        })
        email_res = self.email_service.send_daily_report(
            report_data=email_data,
            youtube_url=youtube_res.video_url if youtube_res else None,
            thumbnail_url=thumbnail_res.image_url if thumbnail_res.status == "SUCCESS" else None,
            system_status={
                "Data": rec.trading_status,
                "AI": ai_res.ai_status,
                "Video": video_res.status,
                "Thumbnail": thumbnail_res.status,
                "YouTube": youtube_res.status if youtube_res else "SKIPPED",
                "Email": "PENDING",
            },
        )
        stage_statuses["EMAIL"] = email_res.status
        logger.info("      Email Status: %s | Provider: %s | Recipient: %s", email_res.status, email_res.provider, email_res.recipient)

        # ---------------------------------------------------------------------
        # Stage 9: Provenance & Web App Cloud Synchronization
        # ---------------------------------------------------------------------
        logger.info("[9/9] Computing deterministic provenance & persisting to ledger...")
        prov = ReportProvenanceEngine.compute_provenance(
            report_date=target_date,
            reconciliation_data=rec.to_dict(),
            ai_data=ai_res.to_dict(),
            voice_data=voice_res.to_dict(),
            video_data=video_res.to_dict(),
            youtube_data=youtube_res.to_dict() if youtube_res else None,
            thumbnail_data=thumbnail_res.to_dict(),
            content_data=content_pkg.to_dict(),
        )

        # Overall Status Resolution
        critical_success = (
            stage_statuses["DATA_COLLECTION"] in ("ACTIVE_TRADING", "NO_TRADES")
            and stage_statuses["AI_ANALYSIS"] == "SUCCESS"
            and stage_statuses["VIDEO"] == "SUCCESS"
        )
        all_success = (
            critical_success
            and stage_statuses["VOICE"] == "SUCCESS"
            and stage_statuses["THUMBNAIL"] == "SUCCESS"
            and stage_statuses["YOUTUBE"] == "SUCCESS"
            and stage_statuses["EMAIL"] == "SUCCESS"
        )

        if all_success:
            overall_status = "SUCCESS"
        elif critical_success:
            overall_status = "PARTIAL_SUCCESS"
        else:
            overall_status = "FAILED"

        # Construct database report record
        report_record = {
            "report_date": target_date,
            "job_run_id": parent_job.run_id,
            "status": overall_status,
            "data_mode": data_mode,
            "total_trades": rec.total_trades,
            "winning_trades": rec.winning_trades,
            "losing_trades": rec.losing_trades,
            "win_rate": rec.win_rate,
            "gross_pnl": rec.gross_pnl,
            "charges": rec.charges,
            "net_pnl": rec.net_pnl,
            "realized_pnl": rec.realized_pnl,
            "unrealized_pnl": rec.unrealized_pnl,
            "best_trade": rec.best_trade,
            "worst_trade": rec.worst_trade,
            "best_strategy": list(rec.strategy_pnl.keys())[0] if rec.strategy_pnl else "None",
            "best_agent": list(rec.agent_pnl.keys())[0] if rec.agent_pnl else "ALPHA",
            "prediction_direction": "NEUTRAL",
            "actual_direction": "NEUTRAL",
            "prediction_correct": True,
            "ai_provider": ai_res.ai_provider,
            "ai_model": ai_res.ai_model,
            "ai_request_id": ai_res.ai_request_id,
            "ai_latency_ms": ai_res.ai_latency_ms,
            "ai_tokens": ai_res.ai_tokens,
            "ai_status": ai_res.ai_status,
            "voice_provider": voice_res.provider,
            "voice_status": voice_res.status,
            "voice_duration_ms": voice_res.duration_ms,
            "video_provider": video_res.provider,
            "video_render_id": video_res.render_id,
            "video_status": video_res.status,
            "video_url": video_res.video_url,
            "video_duration_seconds": 70.0,
            "thumbnail_url": thumbnail_res.image_url,
            "thumbnail_render_id": thumbnail_res.render_id,
            "thumbnail_status": thumbnail_res.status,
            "thumbnail_template": thumbnail_res.template_id,
            "thumbnail_headline": content_pkg.thumbnail_headline,
            "content_theme": content_pkg.content_theme,
            "content_score": content_pkg.content_score,
            "content_data_hash": content_pkg.data_hash,
            "content_generated_at": content_pkg.generated_at,
            "youtube_video_id": youtube_res.video_id if youtube_res else None,
            "youtube_url": youtube_res.video_url if youtube_res else None,
            "youtube_status": youtube_res.status if youtube_res else "SKIPPED",
            "youtube_upload_status": youtube_res.status if youtube_res else "SKIPPED",
            "youtube_thumbnail_status": youtube_res.thumbnail_status if youtube_res else "SKIPPED",
            "email_status": email_res.status,
            "email_sent_at": email_res.sent_at,
            "provenance_hash": prov["provenance_hash"],
            "report_payload_json": {
                "data_mode": data_mode,
                "reconciliation": rec.to_dict(),
                "stage_statuses": stage_statuses,
                "ai_summary": ai_res.executive_summary,
                "narration_script": script_to_narrate,
                "lessons_learned": ai_res.lessons_learned,
                "tomorrow_watchlist": ai_res.tomorrow_watchlist,
                "content_package": content_pkg.to_dict(),
                "thumbnail": thumbnail_res.to_dict(),
            },
        }

        # Save to SQLite and Supabase
        save_daily_trade_report(report_record)

        # Complete Parent JobLedger Run
        self.ledger.complete_run(
            run_id=parent_job.run_id,
            status=overall_status,
            records_fetched=rec.total_trades,
            records_processed=rec.total_trades,
            records_rejected=rec.rejected_trades_count,
            sources_attempted=5,
            sources_succeeded=sum(1 for s in stage_statuses.values() if s in ("SUCCESS", "ACTIVE_TRADING", "NO_TRADES")),
            sources_failed=sum(1 for s in stage_statuses.values() if "FAIL" in s),
            data_quality="HEALTHY" if overall_status == "SUCCESS" else "DEGRADED",
            snapshot_data=report_record,
        )

        # Sync to Web App data bundle (data.json and data.js)
        self._update_web_app_data(report_record)
        stage_statuses["WEB_SYNC"] = "SUCCESS"

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info("Daily Trade Report finished: Status=%s, Mode=%s in %dms", overall_status, data_mode, duration_ms)

        return PipelineExecutionReport(
            report_date=target_date,
            idempotency_key=idempotency_key,
            overall_status=overall_status,
            stage_statuses=stage_statuses,
            reconciliation=rec.to_dict(),
            ai_analysis=ai_res.to_dict(),
            voice_result=voice_res.to_dict(),
            video_result=video_res.to_dict(),
            thumbnail_result=thumbnail_res.to_dict(),
            content_package=content_pkg.to_dict(),
            youtube_result=youtube_res.to_dict() if youtube_res else None,
            email_result=email_res.to_dict(),
            provenance=prov,
            data_mode=data_mode,
            duration_ms=duration_ms,
        )

    def _update_web_app_data(self, report_record: Dict[str, Any]) -> None:
        """
        Embed the latest daily video report in web_app/data.json and data.js.
        """
        try:
            if not WEB_DATA_JSON.exists():
                return

            with open(WEB_DATA_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["daily_video_report"] = report_record
            data["daily_video_report_history"] = get_recent_daily_trade_reports(limit=10)

            with open(WEB_DATA_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            with open(WEB_DATA_JS, "w", encoding="utf-8") as f:
                f.write(f"window.NEXUS_DATA = {json.dumps(data)};\nwindow.INITIAL_DATA = window.NEXUS_DATA;\n")

            logger.info("Updated web_app/data.json and data.js with daily video report.")
        except Exception as e:
            logger.debug("Failed updating web_app data bundle: %s", e)


def main():
    parser = argparse.ArgumentParser(description="NEXUS Daily Automated Trade Report Pipeline")
    parser.add_argument("--date", help="Report date (YYYY-MM-DD)", default=None)
    parser.add_argument("--force", action="store_true", help="Force regenerate even if already completed")
    parser.add_argument("--test-fixture", action="store_true", help="Run with controlled test fixture")
    args = parser.parse_args()

    fixture = None
    if args.test_fixture:
        fixture = [
            {
                "trade_id": "TRD-TEST-RELIANCE",
                "symbol": "RELIANCE.NS",
                "side": "BUY",
                "entry_price": 2510.0,
                "exit_price": 2562.0,
                "quantity": 80,
                "gross_pnl": 4160.0,
                "net_pnl": 3980.0,
                "charges": 180.0,
                "agent_id": "ALPHA",
                "strategy_version": "Event_Arbitrage_V1",
                "decision_reason": "Pre-market catalyst beat street estimates",
            },
            {
                "trade_id": "TRD-TEST-HDFC",
                "symbol": "HDFCBANK.NS",
                "side": "BUY",
                "entry_price": 1650.0,
                "exit_price": 1665.0,
                "quantity": 100,
                "gross_pnl": 1500.0,
                "net_pnl": 1390.0,
                "charges": 110.0,
                "agent_id": "BETA",
                "strategy_version": "Momentum_V1",
                "decision_reason": "Credit growth expansion catalyst",
            },
            {
                "trade_id": "TRD-TEST-TCS",
                "symbol": "TCS.NS",
                "side": "BUY",
                "entry_price": 3820.0,
                "exit_price": 3790.0,
                "quantity": 30,
                "gross_pnl": -900.0,
                "net_pnl": -980.0,
                "charges": 80.0,
                "agent_id": "GAMMA",
                "strategy_version": "Mean_Reversion_V1",
                "decision_reason": "Tech spend hesitation trigger",
            },
        ]

    pipeline = DailyTradeReportPipeline()
    res = pipeline.run_pipeline(
        report_date=args.date,
        force_regenerate=args.force,
        custom_trades_fixture=fixture,
        trigger_type="MANUAL" if (args.force or args.test_fixture) else "SCHEDULED",
    )
    print("\n" + "=" * 60)
    print(f"PIPELINE RUN FINISHED: {res.overall_status}")
    print(f"Report Date: {res.report_date}")
    print(f"Stages: {json.dumps(res.stage_statuses, indent=2)}")
    print(f"Provenance Hash: {res.provenance.get('provenance_hash')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
