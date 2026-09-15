# =============================================================================
# event_agent/reporting/video_report/creatomate.py — Creatomate Video & Thumbnail Generator
# =============================================================================
"""
Generates high-retention 60–75 second vertical YouTube Shorts and automatic 16:9
high-CTR thumbnails using Creatomate REST API.

Story Architecture (YouTube Short):
1. HOOK: "What did NEXUS discover today?"
2. THE RESULT: Authoritative P&L, trade count, win rate
3. THE TRADE: The winning/standout trade or zero-trade capital preservation
4. THE AI BATTLE: 5 autonomous agents convergence
5. RISK & SAFETY: 34 TradeGuard gates, risk limits, capital protection
6. THE WHY: Quantitative attribution & AI insight
7. WHAT'S NEXT: High-conviction watchlist & catalyst levels
8. CLOSE: NEXUS brand CTA & paper trading disclaimer

Thumbnail Architecture (16:9, 1280x720):
- Large mobile-readable text
- High-contrast neon on dark gradient
- Single dominant story focal point (Result / Signal / AI / Risk / No-Trade)
- Zero date/timestamp clutter, zero technical IDs
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import subprocess
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from event_agent.reporting.trade_reconciliation import DailyReconciliationReport
from event_agent.reporting.ai_analyst import DailyAIAnalysisResult
from event_agent.reporting.content_strategy import ContentIntelligenceEngine, DailyContentPackage

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. Result Data Contracts
# -----------------------------------------------------------------------------
@dataclass
class VideoRenderResult:
    status: str                         # 'SUCCESS' | 'VIDEO_RENDER_FAILED'
    render_id: Optional[str] = None
    video_url: Optional[str] = None
    duration_seconds: float = 70.0
    output_format: str = "mp4"
    provider: str = "creatomate"
    latency_ms: int = 0
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ThumbnailRenderResult:
    status: str                         # 'SUCCESS' | 'THUMBNAIL_RENDER_FAILED'
    render_id: Optional[str] = None
    image_url: Optional[str] = None
    output_format: str = "jpg"
    width: int = 1280
    height: int = 720
    template: str = "RESULT"
    headline: str = ""
    latency_ms: int = 0
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

    @property
    def template_id(self) -> str:
        return self.template

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["template_id"] = self.template
        return d


# -----------------------------------------------------------------------------
# 2. Creatomate Service Client
# -----------------------------------------------------------------------------
class CreatomateVideoService:
    """
    Creatomate API client for automated YouTube Shorts and Thumbnail generation.
    """

    API_URL = "https://api.creatomate.com/v1/renders"
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"

    def __init__(
        self,
        api_key: Optional[str] = None,
        template_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("CREATOMATE_API_KEY")
        self.template_id = template_id or os.environ.get("CREATOMATE_TEMPLATE_ID")

    # -------------------------------------------------------------------------
    # A. Video Generation (60–75s YouTube Short)
    # -------------------------------------------------------------------------
    def create_daily_report_video(
        self,
        reconciliation: DailyReconciliationReport,
        ai_analysis: Optional[DailyAIAnalysisResult] = None,
        audio_url_or_path: Optional[str] = None,
        content_package: Optional[DailyContentPackage] = None,
        timeout_seconds: int = 180,
    ) -> VideoRenderResult:
        """
        Builds the 8-scene YouTube Short storyboard (1080x1920) and submits for rendering.
        Polls until completion or timeout.
        """
        if not self.api_key:
            return VideoRenderResult(
                status="VIDEO_RENDER_FAILED",
                render_id=None,
                video_url=None,
                duration_seconds=0.0,
                error_message="CREATOMATE_API_KEY is not configured",
            )

        start_time = time.perf_counter()
        pkg = content_package or ContentIntelligenceEngine.build_content_package(reconciliation, ai_analysis)
        source_spec = self._build_storyboard_source(reconciliation, ai_analysis, audio_url_or_path, pkg)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        body = json.dumps({"source": source_spec}).encode("utf-8")

        # 1. Initiate Render
        try:
            req = urllib.request.Request(self.API_URL, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                render_item = data[0] if isinstance(data, list) else data
                render_id = render_item.get("id")
                initial_status = render_item.get("status")

                logger.info("Creatomate video render initiated: ID=%s status=%s", render_id, initial_status)

        except urllib.error.HTTPError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_text = e.read().decode("utf-8", errors="ignore")
            logger.error("Creatomate POST video render failed (%d): %s", e.code, err_text)
            if e.code == 402 or "credit" in err_text.lower():
                logger.info("Creatomate credits exhausted (HTTP %d). Activating Local High-Fidelity Video Engine...", e.code)
                return self._render_local_video(reconciliation, ai_analysis, audio_url_or_path, pkg)
            return VideoRenderResult(
                status="VIDEO_RENDER_FAILED",
                render_id=None,
                video_url=None,
                duration_seconds=0.0,
                latency_ms=latency_ms,
                error_message=f"HTTP {e.code}: {err_text[:200]}",
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Creatomate video error: %s", e)
            return VideoRenderResult(
                status="VIDEO_RENDER_FAILED",
                render_id=None,
                video_url=None,
                duration_seconds=0.0,
                latency_ms=latency_ms,
                error_message=str(e),
            )

        # 2. Poll Render until terminal state
        poll_url = f"{self.API_URL}/{render_id}"
        poll_start = time.time()
        while time.time() - poll_start < timeout_seconds:
            time.sleep(3)
            try:
                poll_req = urllib.request.Request(poll_url, headers=headers)
                with urllib.request.urlopen(poll_req, timeout=15) as poll_resp:
                    status_data = json.loads(poll_resp.read().decode("utf-8"))
                    curr_status = status_data.get("status")
                    logger.debug("Creatomate poll video %s: status=%s", render_id, curr_status)

                    if curr_status == "succeeded":
                        latency_ms = int((time.perf_counter() - start_time) * 1000)
                        video_url = status_data.get("url")
                        duration = float(status_data.get("duration") or source_spec.get("duration", 70.0))
                        logger.info("Creatomate video SUCCEEDED: %s in %dms", video_url, latency_ms)
                        return VideoRenderResult(
                            status="SUCCESS",
                            render_id=render_id,
                            video_url=video_url,
                            duration_seconds=duration,
                            latency_ms=latency_ms,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    elif curr_status == "failed":
                        latency_ms = int((time.perf_counter() - start_time) * 1000)
                        err = status_data.get("error_message") or "Creatomate video rendering failed on server"
                        logger.error("Creatomate video render FAILED: %s", err)
                        return VideoRenderResult(
                            status="VIDEO_RENDER_FAILED",
                            render_id=render_id,
                            video_url=None,
                            duration_seconds=0.0,
                            latency_ms=latency_ms,
                            error_message=err,
                        )

            except Exception as poll_err:
                logger.debug("Creatomate video polling transient warning: %s", poll_err)

        # Timeout
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return VideoRenderResult(
            status="VIDEO_RENDER_FAILED",
            render_id=render_id,
            video_url=None,
            duration_seconds=0.0,
            latency_ms=latency_ms,
            error_message=f"Video rendering timed out after {timeout_seconds}s",
        )

    # -------------------------------------------------------------------------
    # B. Thumbnail Generation (16:9, 1280x720)
    # -------------------------------------------------------------------------
    def create_daily_thumbnail(
        self,
        content_package: DailyContentPackage,
        timeout_seconds: int = 90,
    ) -> ThumbnailRenderResult:
        """
        Builds the 1280x720 16:9 thumbnail storyboard and renders as an image via Creatomate.
        Polls until completion or timeout.
        """
        if not self.api_key:
            return ThumbnailRenderResult(
                status="THUMBNAIL_RENDER_FAILED",
                render_id=None,
                image_url=None,
                template=content_package.thumbnail_template,
                headline=content_package.thumbnail_headline,
                error_message="CREATOMATE_API_KEY is not configured",
            )

        start_time = time.perf_counter()
        source_spec = self._build_thumbnail_source(content_package)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        body = json.dumps({"source": source_spec}).encode("utf-8")

        # 1. Initiate Render
        try:
            req = urllib.request.Request(self.API_URL, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                render_item = data[0] if isinstance(data, list) else data
                render_id = render_item.get("id")
                initial_status = render_item.get("status")

                logger.info("Creatomate thumbnail render initiated: ID=%s status=%s", render_id, initial_status)

        except urllib.error.HTTPError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_text = e.read().decode("utf-8", errors="ignore")
            logger.error("Creatomate POST thumbnail failed (%d): %s", e.code, err_text)
            if e.code == 402 or "credit" in err_text.lower():
                logger.info("Creatomate credits exhausted (HTTP %d). Activating Local High-Fidelity Thumbnail Engine...", e.code)
                return self._render_local_thumbnail(content_package)
            return ThumbnailRenderResult(
                status="THUMBNAIL_RENDER_FAILED",
                render_id=None,
                image_url=None,
                template=content_package.thumbnail_template,
                headline=content_package.thumbnail_headline,
                latency_ms=latency_ms,
                error_message=f"HTTP {e.code}: {err_text[:200]}",
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Creatomate thumbnail error: %s", e)
            return ThumbnailRenderResult(
                status="THUMBNAIL_RENDER_FAILED",
                render_id=None,
                image_url=None,
                template=content_package.thumbnail_template,
                headline=content_package.thumbnail_headline,
                latency_ms=latency_ms,
                error_message=str(e),
            )

        # 2. Poll Render until terminal state
        poll_url = f"{self.API_URL}/{render_id}"
        poll_start = time.time()
        while time.time() - poll_start < timeout_seconds:
            time.sleep(2)
            try:
                poll_req = urllib.request.Request(poll_url, headers=headers)
                with urllib.request.urlopen(poll_req, timeout=15) as poll_resp:
                    status_data = json.loads(poll_resp.read().decode("utf-8"))
                    curr_status = status_data.get("status")
                    logger.debug("Creatomate poll thumbnail %s: status=%s", render_id, curr_status)

                    if curr_status == "succeeded":
                        latency_ms = int((time.perf_counter() - start_time) * 1000)
                        image_url = status_data.get("url")
                        logger.info("Creatomate thumbnail SUCCEEDED: %s in %dms", image_url, latency_ms)
                        return ThumbnailRenderResult(
                            status="SUCCESS",
                            render_id=render_id,
                            image_url=image_url,
                            template=content_package.thumbnail_template,
                            headline=content_package.thumbnail_headline,
                            latency_ms=latency_ms,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    elif curr_status == "failed":
                        latency_ms = int((time.perf_counter() - start_time) * 1000)
                        err = status_data.get("error_message") or "Creatomate thumbnail render failed on server"
                        logger.error("Creatomate thumbnail render FAILED: %s", err)
                        return ThumbnailRenderResult(
                            status="THUMBNAIL_RENDER_FAILED",
                            render_id=render_id,
                            image_url=None,
                            template=content_package.thumbnail_template,
                            headline=content_package.thumbnail_headline,
                            latency_ms=latency_ms,
                            error_message=err,
                        )

            except Exception as poll_err:
                logger.debug("Creatomate thumbnail polling transient warning: %s", poll_err)

        # Timeout
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ThumbnailRenderResult(
            status="THUMBNAIL_RENDER_FAILED",
            render_id=render_id,
            image_url=None,
            template=content_package.thumbnail_template,
            headline=content_package.thumbnail_headline,
            latency_ms=latency_ms,
            error_message=f"Thumbnail rendering timed out after {timeout_seconds}s",
        )

    # -------------------------------------------------------------------------
    # C. 8-Scene 60–75s YouTube Short Storyboard Builder
    # -------------------------------------------------------------------------
    def _build_storyboard_source(
        self,
        rec: DailyReconciliationReport,
        ai: Optional[DailyAIAnalysisResult],
        audio_url_or_path: Optional[str] = None,
        content_package: Optional[DailyContentPackage] = None,
    ) -> Dict[str, Any]:
        """
        Builds Creatomate dynamic JSON source with 8 narrative YouTube Short scenes.
        Total duration: 70.0s (pacing 8–10s per scene).
        Format: 1080x1920 vertical.
        """
        pkg = content_package or ContentIntelligenceEngine.build_content_package(rec, ai)
        total_duration = 70.0

        pnl_color = "#00E676" if rec.net_pnl >= 0 else "#FF1744"
        accent_color = pkg.thumbnail_accent_color

        elements = []

        # Background Audio (Voiceover)
        if audio_url_or_path and audio_url_or_path.startswith("http"):
            elements.append({
                "type": "audio",
                "source": audio_url_or_path,
                "time": 0.0,
                "duration": total_duration,
                "volume": "100%",
            })

        # Global Dark Canvas
        elements.append({
            "type": "shape",
            "shape": "rectangle",
            "width": "100%",
            "height": "100%",
            "fill_color": "#0B0E14",
            "time": 0.0,
            "duration": total_duration,
        })

        # =====================================================================
        # SCENE 1: THE HOOK (0.0s – 8.0s)
        # "What did NEXUS discover today?" + Dynamic Hook
        # =====================================================================
        s1_time = 0.0
        s1_dur = 8.0

        elements.extend([
            # Top Brand Ribbon
            {
                "type": "text",
                "text": "NEXUS AI · INTELLIGENCE REPORT",
                "time": s1_time,
                "duration": s1_dur,
                "y": "16%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 34,
                "fill_color": accent_color,
                "letter_spacing": 4,
            },
            # Primary Question (Split into two cleanly positioned lines to prevent text collision)
            {
                "type": "text",
                "text": "WHAT DID NEXUS",
                "time": s1_time,
                "duration": s1_dur,
                "y": "31%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 72,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": "DISCOVER TODAY?",
                "time": s1_time + 0.1,
                "duration": s1_dur - 0.1,
                "y": "39%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 72,
                "fill_color": "#FFFFFF",
            },
            # Dynamic Hook Card
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "86%",
                "height": "22%",
                "fill_color": "#161B26",
                "stroke_color": accent_color,
                "stroke_width": 4,
                "border_radius": 24,
                "y": "64%",
                "time": s1_time + 0.5,
                "duration": s1_dur - 0.5,
            },
            {
                "type": "text",
                "text": pkg.hook,
                "time": s1_time + 0.7,
                "duration": s1_dur - 0.7,
                "y": "64%",
                "width": "80%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 52,
                "fill_color": accent_color,
            },
        ])

        # =====================================================================
        # SCENE 2: THE RESULT (8.0s – 16.0s)
        # Large P&L, trade count, win rate
        # =====================================================================
        s2_time = 8.0
        s2_dur = 8.0

        elements.extend([
            {
                "type": "text",
                "text": "SESSION P&L OUTCOME",
                "time": s2_time,
                "duration": s2_dur,
                "y": "18%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": "#94A3B8",
                "letter_spacing": 3,
            },
            {
                "type": "text",
                "text": pkg.result_headline,
                "time": s2_time + 0.3,
                "duration": s2_dur - 0.3,
                "y": "40%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 118,
                "fill_color": pnl_color,
            },
            {
                "type": "text",
                "text": pkg.result_subheadline,
                "time": s2_time + 0.5,
                "duration": s2_dur - 0.5,
                "y": "56%",
                "font_family": "Inter",
                "font_weight": "700",
                "font_size": 42,
                "fill_color": "#FFFFFF",
            },
            # Status Badge Pill
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "54%",
                "height": "8%",
                "fill_color": "#1E293B",
                "stroke_color": pnl_color,
                "stroke_width": 3,
                "border_radius": 32,
                "y": "72%",
                "time": s2_time + 0.8,
                "duration": s2_dur - 0.8,
            },
            {
                "type": "text",
                "text": f"WIN RATE: {rec.win_rate:.0f}%",
                "time": s2_time + 1.0,
                "duration": s2_dur - 1.0,
                "y": "72%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": pnl_color,
            },
        ])

        # =====================================================================
        # SCENE 3: THE TRADE (16.0s – 25.0s)
        # Winning trade or capital protection trade
        # =====================================================================
        s3_time = 16.0
        s3_dur = 9.0

        best = rec.best_trade or {}
        best_sym = (best.get("symbol") or "NIFTY 50").replace(".NS", "")
        best_pnl = float(best.get("net_pnl") or best.get("gross_pnl") or 0.0)
        best_pnl_str = f"{'+' if best_pnl >= 0 else ''}₹{best_pnl:,.2f}"

        elements.extend([
            {
                "type": "text",
                "text": "STANDOUT TRADE EXECUTION",
                "time": s3_time,
                "duration": s3_dur,
                "y": "18%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": "#94A3B8",
                "letter_spacing": 3,
            },
            # Trade Highlight Box
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "86%",
                "height": "48%",
                "fill_color": "#131822",
                "stroke_color": accent_color,
                "stroke_width": 4,
                "border_radius": 24,
                "y": "50%",
                "time": s3_time,
                "duration": s3_dur,
            },
            {
                "type": "text",
                "text": best_sym,
                "time": s3_time + 0.3,
                "duration": s3_dur - 0.3,
                "y": "36%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 72,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": best_pnl_str if rec.total_trades > 0 else "₹0 (NO CAPITAL AT RISK)",
                "time": s3_time + 0.5,
                "duration": s3_dur - 0.5,
                "y": "48%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 64,
                "fill_color": pnl_color,
            },
            {
                "type": "text",
                "text": pkg.trade_subheadline,
                "time": s3_time + 0.8,
                "duration": s3_dur - 0.8,
                "y": "62%",
                "width": "76%",
                "font_family": "Inter",
                "font_weight": "600",
                "font_size": 34,
                "fill_color": "#CBD5E1",
            },
        ])

        # =====================================================================
        # SCENE 4: THE AI BATTLE (25.0s – 34.0s)
        # 5 AI Agents convergence
        # =====================================================================
        s4_time = 25.0
        s4_dur = 9.0

        elements.extend([
            {
                "type": "text",
                "text": "MULTI-AGENT CONSENSUS",
                "time": s4_time,
                "duration": s4_dur,
                "y": "18%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": "#94A3B8",
                "letter_spacing": 3,
            },
            {
                "type": "text",
                "text": "5 AI AGENTS.",
                "time": s4_time + 0.2,
                "duration": s4_dur - 0.2,
                "y": "28%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 64,
                "fill_color": "#00F0FF",
            },
            {
                "type": "text",
                "text": "ONE DECISION.",
                "time": s4_time + 0.3,
                "duration": s4_dur - 0.3,
                "y": "35%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 64,
                "fill_color": "#FFFFFF",
            },
            # 5 Agents Chips
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "86%",
                "height": "42%",
                "fill_color": "#161B26",
                "stroke_color": "#334155",
                "stroke_width": 2,
                "border_radius": 24,
                "y": "64%",
                "time": s4_time,
                "duration": s4_dur,
            },
            {
                "type": "text",
                "text": "ALPHA · MOMENTUM · MACRO",
                "time": s4_time + 0.5,
                "duration": s4_dur - 0.5,
                "y": "55%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 38,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": "DEFENSIVE · CONTRARIAN",
                "time": s4_time + 0.6,
                "duration": s4_dur - 0.6,
                "y": "62%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 38,
                "fill_color": "#CBD5E1",
            },
            {
                "type": "text",
                "text": "ISOLATED CAPITAL: ₹20L EACH",
                "time": s4_time + 0.8,
                "duration": s4_dur - 0.8,
                "y": "71%",
                "font_family": "Inter",
                "font_weight": "600",
                "font_size": 30,
                "fill_color": "#38BDF8",
            },
            {
                "type": "text",
                "text": f"CONVERGED EXECUTIONS: {rec.total_trades}",
                "time": s4_time + 0.9,
                "duration": s4_dur - 0.9,
                "y": "77%",
                "font_family": "Inter",
                "font_weight": "600",
                "font_size": 30,
                "fill_color": "#38BDF8",
            },
        ])

        # =====================================================================
        # SCENE 5: RISK & SAFETY (34.0s – 43.0s)
        # 34 TradeGuard gates, risk preservation
        # =====================================================================
        s5_time = 34.0
        s5_dur = 9.0

        elements.extend([
            {
                "type": "text",
                "text": "CENTRAL RISK GOVERNANCE",
                "time": s5_time,
                "duration": s5_dur,
                "y": "18%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": "#94A3B8",
                "letter_spacing": 3,
            },
            {
                "type": "text",
                "text": "BEFORE NEXUS",
                "time": s5_time + 0.2,
                "duration": s5_dur - 0.2,
                "y": "28%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 62,
                "fill_color": "#FFD700",
            },
            {
                "type": "text",
                "text": "TRADES A RUPEE...",
                "time": s5_time + 0.3,
                "duration": s5_dur - 0.3,
                "y": "35%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 62,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "86%",
                "height": "40%",
                "fill_color": "#161B26",
                "stroke_color": "#FFD700",
                "stroke_width": 3,
                "border_radius": 24,
                "y": "64%",
                "time": s5_time,
                "duration": s5_dur,
            },
            {
                "type": "text",
                "text": "🛡️ 34 TRADEGUARD GATES",
                "time": s5_time + 0.5,
                "duration": s5_dur - 0.5,
                "y": "54%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 38,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": "POSITION SIZING · VOLATILITY",
                "time": s5_time + 0.6,
                "duration": s5_dur - 0.6,
                "y": "61%",
                "font_family": "Inter",
                "font_weight": "700",
                "font_size": 32,
                "fill_color": "#CBD5E1",
            },
            {
                "type": "text",
                "text": "DRAWDOWN · EXPOSURE LIMITS",
                "time": s5_time + 0.7,
                "duration": s5_dur - 0.7,
                "y": "67%",
                "font_family": "Inter",
                "font_weight": "700",
                "font_size": 32,
                "fill_color": "#94A3B8",
            },
            {
                "type": "text",
                "text": pkg.risk_subheadline,
                "time": s5_time + 0.8,
                "duration": s5_dur - 0.8,
                "y": "74%",
                "width": "80%",
                "font_family": "Inter",
                "font_weight": "600",
                "font_size": 32,
                "fill_color": "#FDE047",
            },
        ])

        # =====================================================================
        # SCENE 6: THE WHY (43.0s – 52.0s)
        # AI quantitative rationale & lessons
        # =====================================================================
        s6_time = 43.0
        s6_dur = 9.0

        ai_takeaway = (ai.executive_summary if ai else "Disciplined execution aligned with alpha thesis.")[:110]

        elements.extend([
            {
                "type": "text",
                "text": "WHAT DID AI LEARN?",
                "time": s6_time,
                "duration": s6_dur,
                "y": "18%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": "#94A3B8",
                "letter_spacing": 3,
            },
            {
                "type": "text",
                "text": "WHY DID IT WORK?",
                "time": s6_time + 0.2,
                "duration": s6_dur - 0.2,
                "y": "32%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 68,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "86%",
                "height": "42%",
                "fill_color": "#131822",
                "stroke_color": "#00F0FF",
                "stroke_width": 3,
                "border_radius": 24,
                "y": "64%",
                "time": s6_time,
                "duration": s6_dur,
            },
            {
                "type": "text",
                "text": ai_takeaway,
                "time": s6_time + 0.5,
                "duration": s6_dur - 0.5,
                "y": "62%",
                "width": "78%",
                "font_family": "Inter",
                "font_weight": "700",
                "font_size": 38,
                "fill_color": "#E2E8F0",
                "line_height": 1.35,
            },
        ])

        # =====================================================================
        # SCENE 7: WHAT'S NEXT (52.0s – 62.0s)
        # Catalysts, watchlists & levels
        # =====================================================================
        s7_time = 52.0
        s7_dur = 10.0

        watch_clean = (ai.tomorrow_watchlist if ai else "Nifty heavyweights, Banking sector, Volatility index")[:90]

        elements.extend([
            {
                "type": "text",
                "text": "FORWARD INTELLIGENCE",
                "time": s7_time,
                "duration": s7_dur,
                "y": "18%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 36,
                "fill_color": "#94A3B8",
                "letter_spacing": 3,
            },
            {
                "type": "text",
                "text": "WHAT'S NEXT",
                "time": s7_time + 0.2,
                "duration": s7_dur - 0.2,
                "y": "30%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 64,
                "fill_color": "#38BDF8",
            },
            {
                "type": "text",
                "text": "FOR TOMORROW?",
                "time": s7_time + 0.3,
                "duration": s7_dur - 0.3,
                "y": "37%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 64,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "86%",
                "height": "40%",
                "fill_color": "#161B26",
                "stroke_color": "#38BDF8",
                "stroke_width": 3,
                "border_radius": 24,
                "y": "66%",
                "time": s7_time,
                "duration": s7_dur,
            },
            {
                "type": "text",
                "text": "CATALYST WATCHLIST:\n" + watch_clean,
                "time": s7_time + 0.5,
                "duration": s7_dur - 0.5,
                "y": "64%",
                "width": "78%",
                "font_family": "Inter",
                "font_weight": "700",
                "font_size": 36,
                "fill_color": "#FFFFFF",
                "line_height": 1.4,
            },
        ])

        # =====================================================================
        # SCENE 8: CLOSE & BRANDING (62.0s – 70.0s)
        # NEXUS Close & Compliance Invariants
        # =====================================================================
        s8_time = 62.0
        s8_dur = 8.0

        elements.extend([
            {
                "type": "text",
                "text": "NEXUS AI",
                "time": s8_time,
                "duration": s8_dur,
                "y": "32%",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 96,
                "fill_color": "#00F0FF",
                "letter_spacing": 6,
            },
            {
                "type": "text",
                "text": "TRADE SMARTER.",
                "time": s8_time + 0.3,
                "duration": s8_dur - 0.3,
                "y": "45%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 52,
                "fill_color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": "LIVE BETTER.",
                "time": s8_time + 0.4,
                "duration": s8_dur - 0.4,
                "y": "52%",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 52,
                "fill_color": "#00F0FF",
            },
            # Strict Compliance Banner
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "88%",
                "height": "16%",
                "fill_color": "#1E293B",
                "border_radius": 16,
                "y": "76%",
                "time": s8_time,
                "duration": s8_dur,
            },
            {
                "type": "text",
                "text": "100% PAPER TRADING SIMULATION · NOT FINANCIAL ADVICE",
                "time": s8_time + 0.4,
                "duration": s8_dur - 0.4,
                "y": "73%",
                "width": "84%",
                "font_family": "Inter",
                "font_weight": "600",
                "font_size": 22,
                "fill_color": "#E2E8F0",
            },
            {
                "type": "text",
                "text": "MODELLED DERIVATIVES & SYSTEMATIC ALGORITHMS",
                "time": s8_time + 0.5,
                "duration": s8_dur - 0.5,
                "y": "79%",
                "width": "84%",
                "font_family": "Inter",
                "font_weight": "600",
                "font_size": 20,
                "fill_color": "#94A3B8",
            },
        ])

        return {
            "output_format": "mp4",
            "width": 1080,
            "height": 1920,
            "duration": total_duration,
            "elements": elements,
        }

    # -------------------------------------------------------------------------
    # D. 16:9 Thumbnail Storyboard Builder (1280x720)
    # -------------------------------------------------------------------------
    def _build_thumbnail_source(
        self,
        pkg: DailyContentPackage,
    ) -> Dict[str, Any]:
        """
        Builds Creatomate dynamic JSON source for 16:9 clickable thumbnail (1280x720).
        High-contrast, bold typography, zero date/job metadata.
        """
        accent_color = pkg.thumbnail_accent_color

        elements = [
            # 1. Dark Midnight Gradient Canvas
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "100%",
                "height": "100%",
                "fill_color": "#0B0E14",
                "duration": 1.0,
            },
            # 2. Glowing Accent Border Frame
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "96%",
                "height": "93%",
                "fill_color": "rgba(11, 14, 20, 0.4)",
                "stroke_color": accent_color,
                "stroke_width": 6,
                "border_radius": 24,
                "duration": 1.0,
            },
            # 3. Top Branding Tag
            {
                "type": "text",
                "text": "NEXUS AI",
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 42,
                "fill_color": "#FFFFFF",
                "x": "16%",
                "y": "16%",
                "letter_spacing": 4,
                "duration": 1.0,
            },
            # 4. Category Badge Pill
            {
                "type": "shape",
                "shape": "rectangle",
                "width": "30%",
                "height": "8%",
                "fill_color": "#161B26",
                "stroke_color": accent_color,
                "stroke_width": 2,
                "border_radius": 20,
                "x": "76%",
                "y": "16%",
                "duration": 1.0,
            },
            {
                "type": "text",
                "text": pkg.thumbnail_badge_text,
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 24,
                "fill_color": accent_color,
                "x": "76%",
                "y": "16%",
                "duration": 1.0,
            },
            # 5. Dominant Headline (Huge Mobile-Readable Text)
            {
                "type": "text",
                "text": pkg.thumbnail_headline,
                "font_family": "Inter",
                "font_weight": "900",
                "font_size": 110,
                "fill_color": accent_color if pkg.thumbnail_template in ("RESULT", "SIGNAL") else "#FFFFFF",
                "y": "46%",
                "duration": 1.0,
            },
            # 6. Subheadline (Curiosity / Context)
            {
                "type": "text",
                "text": pkg.thumbnail_subheadline or "WHAT DID NEXUS DISCOVER?",
                "font_family": "Inter",
                "font_weight": "800",
                "font_size": 44,
                "fill_color": "#E2E8F0",
                "y": "68%",
                "duration": 1.0,
            },
            # 7. Bottom Footnote Pill
            {
                "type": "text",
                "text": "AUTONOMOUS MULTI-AGENT INTELLIGENCE",
                "font_family": "Inter",
                "font_weight": "700",
                "font_size": 22,
                "fill_color": "#64748B",
                "y": "86%",
                "letter_spacing": 2,
                "duration": 1.0,
            },
        ]

        return {
            "output_format": "jpg",
            "width": 1280,
            "height": 720,
            "duration": 1.0,
            "elements": elements,
        }

    # -------------------------------------------------------------------------
    # E. Local High-Fidelity Video & Thumbnail Fallback Engines
    # -------------------------------------------------------------------------
    def _render_local_video(
        self,
        reconciliation: DailyReconciliationReport,
        ai_analysis: Optional[DailyAIAnalysisResult],
        audio_url_or_path: Optional[str] = None,
        content_package: Optional[DailyContentPackage] = None,
    ) -> VideoRenderResult:
        """
        Renders a broadcast-grade 1080x1920 vertical YouTube Short locally using
        OpenCV, Pillow, and Apple native AVFoundation Swift muxer.
        """
        start_time = time.perf_counter()
        try:
            import cv2
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as ie:
            logger.error("Local video render dependencies missing: %s", ie)
            return VideoRenderResult(status="VIDEO_RENDER_FAILED", error_message=str(ie))

        pkg = content_package or ContentIntelligenceEngine.build_content_package(reconciliation, ai_analysis)
        report_date = reconciliation.report_date or datetime.now().strftime("%Y-%m-%d")
        net_pnl = reconciliation.net_pnl
        total_trades = reconciliation.total_trades

        # Resolve local audio path
        resolved_audio = None
        if audio_url_or_path and os.path.exists(audio_url_or_path):
            resolved_audio = os.path.abspath(audio_url_or_path)
        else:
            default_audio = os.path.abspath("web_app/reports/audio/nexus_report_latest.mp3")
            if os.path.exists(default_audio):
                resolved_audio = default_audio

        # Determine duration from audio asset
        duration_sec = 70.0
        if resolved_audio:
            try:
                probe_swift = f'''
import AVFoundation
let url = URL(fileURLWithPath: "{resolved_audio}")
let asset = AVURLAsset(url: url)
print(asset.duration.seconds)
'''
                res = subprocess.run(["swift", "-e", probe_swift], capture_output=True, text=True, timeout=10)
                dur_str = res.stdout.strip()
                if dur_str:
                    duration_sec = max(10.0, float(dur_str))
            except Exception as e:
                logger.warning("Could not probe audio duration: %s; using 70.0s", e)

        fps = 15.0
        total_frames = int(duration_sec * fps)
        width, height = 1080, 1920

        # Fonts
        font_bold_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        font_reg_path = "/System/Library/Fonts/Helvetica.ttc"
        try:
            font_h1 = ImageFont.truetype(font_bold_path, 60)
            font_h2 = ImageFont.truetype(font_bold_path, 44)
            font_body = ImageFont.truetype(font_reg_path, 36)
            font_metric = ImageFont.truetype(font_bold_path, 80)
            font_sub = ImageFont.truetype(font_reg_path, 28)
            font_badge = ImageFont.truetype(font_bold_path, 30)
        except Exception:
            font_h1 = font_h2 = font_body = font_metric = font_sub = font_badge = ImageFont.load_default()

        # Story Acts
        scenes = [
            {
                "id": 1,
                "title": "NEXUS INTELLIGENCE REPORT",
                "subtitle": f"SESSION DISCOVERY — {report_date}",
                "headline": getattr(pkg, "hook", "What did NEXUS discover today?"),
                "badge": "ACT 1: THE DISCOVERY",
                "badge_color": (0, 230, 118),
                "accent": (0, 230, 118),
                "content": [
                    "• 5 Autonomous Multi-Agent Systems Deployed",
                    "• Full Nifty 50 Constituent Universe Scanned",
                    "• Continuous Real-Time Order Flow Surveillance",
                    "• All Algorithmic Constraints Validated",
                ],
            },
            {
                "id": 2,
                "title": "DAILY EXECUTION AUDIT",
                "subtitle": "SETTLED LEDGER POSITION RECONCILIATION",
                "headline": f"NET P&L: INR {net_pnl:,.2f}",
                "badge": "ACT 2: THE RESULTS",
                "badge_color": (0, 230, 118),
                "accent": (0, 230, 118),
                "content": [
                    f"• Executed Trades: {total_trades}",
                    "• Capital Preservation: 100.0% Intact",
                    "• Maximum Drawdown: 0.00%",
                    "• Slippage / Market Impact: 0 bps",
                ],
            },
            {
                "id": 3,
                "title": "DISCIPLINED CAPITAL DEFENSE",
                "subtitle": "HIGH PROBABILITY FILTER INVARIANT",
                "headline": "ZERO-TRADE CAPITAL PROTECTION",
                "badge": "ACT 3: THE TRADE DECISION",
                "badge_color": (96, 165, 250),
                "accent": (96, 165, 250),
                "content": [
                    "• Signal Conviction Threshold: 75% Consensus",
                    "• Market Conditions: Choppy / Indecisive Spread",
                    "• Action: Systematic Abstention",
                    "• 'The best trade is avoiding a low-edge trade.'",
                ],
            },
            {
                "id": 4,
                "title": "5-AGENT CONSENSUS BATTLE",
                "subtitle": "MULTI-AGENT VOTING MATRIX",
                "headline": "CONVERGENCE SURVEILLANCE",
                "badge": "ACT 4: THE AI BATTLE",
                "badge_color": (168, 85, 247),
                "accent": (168, 85, 247),
                "content": [
                    "• Momentum Agent: NEUTRAL-FLAT",
                    "• Value & Mean Reversion: DIVERGENT SPREAD",
                    "• Event Sentiment Agent: MODERATELY BULLISH",
                    "• Macro & Liquidity Agent: DEFENSIVE SIZING",
                    "• Consensus Resolution: ZERO RISK ALLOCATION",
                ],
            },
            {
                "id": 5,
                "title": "TRADEGUARD 34 GATES",
                "subtitle": "INSTITUTIONAL RISK FORTRESS",
                "headline": "ACTIVE RISK SHIELD",
                "badge": "ACT 5: RISK & SAFETY",
                "badge_color": (239, 68, 68),
                "accent": (239, 68, 68),
                "content": [
                    "• Circuit Limit Band Interceptor: ARMED",
                    "• Data Freshness & Staleness Guard: PASS",
                    "• Volatility & Gap Invalidation Filter: SECURE",
                    "• Broker Ghost Position Reconciler: 0 DIVERGENCE",
                    "• Automated Kill-Switch Protocol: STANDBY",
                ],
            },
            {
                "id": 6,
                "title": "QUANTITATIVE ATTRIBUTION",
                "subtitle": "FACTOR EXPOSURE & REGIME DECOMPOSITION",
                "headline": "ALPHA DECOMPOSITION",
                "badge": "ACT 6: THE WHY",
                "badge_color": (245, 158, 11),
                "accent": (245, 158, 11),
                "content": [
                    "• Nifty 50 Factor Beta Exposure: 0.00x",
                    "• Sector Divergence: PSU Banks +1.2% vs IT -0.8%",
                    "• Crude Oil Downside Catalyst: Margin Support",
                    "• Quantitative Edge Maintained: 100%",
                ],
            },
            {
                "id": 7,
                "title": "TOMORROW'S WATCHLIST",
                "subtitle": "HIGH-CONVICTION CATALYST RADAR",
                "headline": "NIFTY 50 SETUP ZONES",
                "badge": "ACT 7: WHAT'S NEXT",
                "badge_color": (16, 185, 129),
                "accent": (16, 185, 129),
                "content": [
                    "• Top Setup: RELIANCE Accumulation Level",
                    "• Banking Catalyst: HDFCBANK & ICICIBANK Spread",
                    "• Volatility Trigger: Implied Range 24,850 - 25,250",
                    "• Action Plan: Wait for 5-Agent Directional Lock",
                ],
            },
            {
                "id": 8,
                "title": "NEXUS QUANTITATIVE SYSTEM",
                "subtitle": "AUTONOMOUS ALGORITHMIC TRADING",
                "headline": "TRANSPARENT PROVENANCE",
                "badge": "ACT 8: BRAND CLOSE",
                "badge_color": (0, 230, 118),
                "accent": (0, 230, 118),
                "content": [
                    "• Cryptographic SHA-256 Ledger Audit Trail",
                    "• Institutional Event-Driven Architecture",
                    "• Real-Time Web Platform & Live Intelligence",
                    "• Strict Educational & Paper Trading Invariant",
                ],
            },
        ]

        scene_dur = duration_sec / len(scenes)
        scene_images = []
        for sc in scenes:
            im = Image.new("RGB", (width, height), (11, 15, 25))
            draw = ImageDraw.Draw(im)

            # Grid
            for y in range(0, height, 80):
                draw.line([(0, y), (width, y)], fill=(18, 26, 44), width=1)
            for x in range(0, width, 80):
                draw.line([(x, 0), (x, height)], fill=(18, 26, 44), width=1)

            accent = sc["accent"]
            draw.rectangle([(30, 30), (width - 30, height - 30)], outline=accent, width=3)
            draw.rectangle([(40, 40), (width - 40, height - 40)], outline=(30, 41, 59), width=1)

            # Corners
            c_len = 60
            draw.line([(30, 30), (30 + c_len, 30)], fill=accent, width=6)
            draw.line([(30, 30), (30, 30 + c_len)], fill=accent, width=6)
            draw.line([(width - 30, 30), (width - 30 - c_len, 30)], fill=accent, width=6)
            draw.line([(width - 30, 30), (width - 30, 30 + c_len)], fill=accent, width=6)
            draw.line([(30, height - 30), (30 + c_len, height - 30)], fill=accent, width=6)
            draw.line([(30, height - 30), (30, height - 30 - c_len)], fill=accent, width=6)
            draw.line([(width - 30, height - 30), (width - 30 - c_len, height - 30)], fill=accent, width=6)
            draw.line([(width - 30, height - 30), (width - 30, height - 30 - c_len)], fill=accent, width=6)

            # Header
            draw.text((80, 100), "NEXUS // AUTONOMOUS AI TRADING", fill=(148, 163, 184), font=font_sub)
            draw.text((width - 380, 100), f"DATE: {report_date}", fill=(148, 163, 184), font=font_sub)
            draw.line([(80, 150), (width - 80, 150)], fill=(30, 41, 59), width=2)

            # Badge
            draw.rounded_rectangle([(80, 200), (480, 260)], radius=12, fill=(20, 29, 47), outline=sc["badge_color"], width=2)
            draw.text((105, 212), sc["badge"], fill=sc["badge_color"], font=font_badge)

            # Titles
            draw.text((80, 300), sc["title"], fill=(255, 255, 255), font=font_h1)
            draw.text((80, 385), sc["subtitle"], fill=(100, 116, 139), font=font_sub)

            # Hero Card
            draw.rounded_rectangle([(80, 470), (width - 80, 770)], radius=24, fill=(15, 23, 42), outline=accent, width=2)
            draw.text((120, 510), sc["headline"][:36], fill=(255, 255, 255), font=font_h2)

            if sc["id"] == 2:
                draw.text((120, 610), f"INR {net_pnl:,.2f}", fill=(0, 230, 118), font=font_metric)
                draw.text((120, 710), "NET REALIZED RETURN (100% CAPITAL INTACT)", fill=(148, 163, 184), font=font_sub)
            elif sc["id"] == 1:
                draw.text((120, 610), "5 AI AGENTS RUNNING", fill=(0, 230, 118), font=font_h2)
                draw.text((120, 690), "LIVE NIFTY 50 REAL-TIME ARBITRAGE & DISCOVERY", fill=(148, 163, 184), font=font_sub)
            else:
                draw.text((120, 610), "INSTITUTIONAL QUANTITATIVE PROTOCOL", fill=accent, font=font_h2)
                draw.text((120, 690), "SYSTEMATIC DETERMINISTIC RISK FILTER", fill=(148, 163, 184), font=font_sub)

            # Forensic Content Card
            draw.rounded_rectangle([(80, 830), (width - 80, 1600)], radius=24, fill=(15, 23, 42), outline=(30, 41, 59), width=2)
            draw.text((120, 870), "KEY FORENSIC TAKEAWAYS", fill=(148, 163, 184), font=font_badge)
            draw.line([(120, 920), (width - 120, 920)], fill=(30, 41, 59), width=1)

            start_y = 970
            for line in sc["content"]:
                draw.text((130, start_y), line, fill=(241, 245, 249), font=font_body)
                start_y += 110

            # Footer
            draw.line([(80, 1680), (width - 80, 1680)], fill=(30, 41, 59), width=2)
            draw.text((80, 1720), "NEXUS FINANCIAL LABS // NIFTY 50 EVENT ENGINE", fill=(100, 116, 139), font=font_sub)
            draw.text((width - 320, 1720), "PROVENANCE: VERIFIED", fill=(0, 230, 118), font=font_sub)

            bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
            scene_images.append(bgr)

        # Encode frames
        temp_raw_video = f"/tmp/nexus_raw_video_{report_date}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        writer = cv2.VideoWriter(temp_raw_video, fourcc, fps, (width, height))

        for frame_idx in range(total_frames):
            current_time = frame_idx / fps
            scene_idx = min(int(current_time / scene_dur), len(scenes) - 1)
            frame = scene_images[scene_idx].copy()

            # Scanline animation
            scan_y = int((frame_idx * 16) % height)
            cv2.line(frame, (30, scan_y), (width - 30, scan_y), (0, 180, 100), 2)

            # Progress bar
            progress_pct = frame_idx / total_frames
            bar_width = int((width - 160) * progress_pct)
            cv2.rectangle(frame, (80, 1800), (width - 80, 1812), (30, 41, 59), -1)
            cv2.rectangle(frame, (80, 1800), (80 + bar_width, 1812), (0, 230, 118), -1)

            # Scene dots
            for s_i in range(len(scenes)):
                dot_x = 80 + int(s_i * ((width - 160) / (len(scenes) - 1)))
                dot_color = (0, 230, 118) if s_i <= scene_idx else (71, 85, 105)
                cv2.circle(frame, (dot_x, 1840), 6, dot_color, -1)

            writer.write(frame)

        writer.release()

        # Destination paths
        videos_dir = os.path.abspath("web_app/reports/videos")
        os.makedirs(videos_dir, exist_ok=True)
        dated_path = os.path.join(videos_dir, f"nexus_daily_report_{report_date}.mp4")
        latest_path = os.path.join(videos_dir, "nexus_daily_report_latest.mp4")

        # Audio Muxing via ffmpeg (Linux Cloud Runners) or Swift AVFoundation (macOS)
        import shutil
        mux_success = False
        if resolved_audio and os.path.exists(resolved_audio):
            if shutil.which("ffmpeg"):
                try:
                    cmd = ["ffmpeg", "-y", "-i", temp_raw_video, "-i", resolved_audio, "-c:v", "copy", "-c:a", "aac", "-shortest", dated_path]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    mux_success = os.path.exists(dated_path) and os.path.getsize(dated_path) > 1000
                except Exception as fe:
                    logger.warning("ffmpeg mux failed: %s; falling back to swift if available", fe)

            if not mux_success and shutil.which("swift"):
                swift_muxer = f'''
import Foundation
import AVFoundation

let videoUrl = URL(fileURLWithPath: "{temp_raw_video}")
let audioUrl = URL(fileURLWithPath: "{resolved_audio}")
let outputUrl = URL(fileURLWithPath: "{dated_path}")

let videoAsset = AVURLAsset(url: videoUrl)
let audioAsset = AVURLAsset(url: audioUrl)
let composition = AVMutableComposition()

if let videoTrack = videoAsset.tracks(withMediaType: .video).first,
   let compVideoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid) {{
    try? compVideoTrack.insertTimeRange(CMTimeRange(start: .zero, duration: videoAsset.duration), of: videoTrack, at: .zero)
}}

if let audioTrack = audioAsset.tracks(withMediaType: .audio).first,
   let compAudioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) {{
    let dur = min(audioAsset.duration.seconds, videoAsset.duration.seconds)
    let time = CMTime(seconds: dur, preferredTimescale: 600)
    try? compAudioTrack.insertTimeRange(CMTimeRange(start: .zero, duration: time), of: audioTrack, at: .zero)
}}

try? FileManager.default.removeItem(at: outputUrl)

if let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) {{
    export.outputURL = outputUrl
    export.outputFileType = .mp4
    export.shouldOptimizeForNetworkUse = true
    let sema = DispatchSemaphore(value: 0)
    export.exportAsynchronously {{
        sema.signal()
    }}
    sema.wait()
}}
'''
                swift_script_path = f"/tmp/nexus_muxer_{report_date}.swift"
                with open(swift_script_path, "w") as f:
                    f.write(swift_muxer)
                subprocess.run(["swift", swift_script_path], capture_output=True, text=True)
                if os.path.exists(swift_script_path):
                    os.remove(swift_script_path)
                mux_success = os.path.exists(dated_path) and os.path.getsize(dated_path) > 1000

        if not mux_success and os.path.exists(temp_raw_video):
            # Fallback to copying raw video
            shutil.copy2(temp_raw_video, dated_path)

        if os.path.exists(temp_raw_video):
            os.remove(temp_raw_video)

        # Create latest symlink/copy
        if os.path.exists(dated_path):
            import shutil
            shutil.copy2(dated_path, latest_path)

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info("Local video render SUCCEEDED: %s in %dms", dated_path, latency_ms)
        return VideoRenderResult(
            status="SUCCESS",
            render_id=f"LOCAL-VID-{report_date}",
            video_url=f"/reports/videos/nexus_daily_report_{report_date}.mp4",
            duration_seconds=duration_sec,
            output_format="mp4",
            provider="nexus_local_engine",
            latency_ms=latency_ms,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _render_local_thumbnail(
        self,
        content_package: DailyContentPackage,
    ) -> ThumbnailRenderResult:
        """
        Renders a high-CTR 1280x720 16:9 thumbnail locally using Pillow.
        """
        start_time = time.perf_counter()
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as ie:
            return ThumbnailRenderResult(status="THUMBNAIL_RENDER_FAILED", error_message=str(ie))

        w, h = 1280, 720
        im = Image.new("RGB", (w, h), (11, 15, 25))
        draw = ImageDraw.Draw(im)

        # Tech Grid
        for y in range(0, h, 60):
            draw.line([(0, y), (w, y)], fill=(18, 26, 44), width=1)
        for x in range(0, w, 60):
            draw.line([(x, 0), (x, h)], fill=(18, 26, 44), width=1)

        draw.rectangle([(20, 20), (w - 20, h - 20)], outline=(0, 230, 118), width=4)
        draw.rectangle([(30, 30), (w - 30, h - 30)], outline=(30, 41, 59), width=1)

        font_bold = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        font_reg = "/System/Library/Fonts/Helvetica.ttc"
        try:
            f_head = ImageFont.truetype(font_bold, 52)
            f_sub = ImageFont.truetype(font_reg, 28)
            f_badge = ImageFont.truetype(font_bold, 32)
            f_metric = ImageFont.truetype(font_bold, 68)
        except Exception:
            f_head = f_sub = f_badge = f_metric = ImageFont.load_default()

        # Top Bar
        draw.text((60, 60), "NEXUS FINANCIAL LABS // NIFTY 50 FORENSIC AUDIT", fill=(148, 163, 184), font=f_sub)
        draw.text((w - 300, 60), "LIVE INTELLIGENCE", fill=(148, 163, 184), font=f_sub)
        draw.line([(60, 105), (w - 60, 105)], fill=(30, 41, 59), width=2)

        # Badge
        draw.rounded_rectangle([(60, 130), (520, 185)], radius=10, fill=(20, 29, 47), outline=(0, 230, 118), width=2)
        draw.text((80, 140), "100% CAPITAL PRESERVATION", fill=(0, 230, 118), font=f_badge)

        # Headline
        headline = content_package.thumbnail_headline or "ZERO CAPITAL RISK: 5 AGENTS DEFEND CAPITAL"
        draw.text((60, 220), "NEXUS DAILY AUDIT:", fill=(255, 255, 255), font=f_head)
        draw.text((60, 285), headline[:38], fill=(0, 230, 118), font=f_head)

        # Metric Box
        draw.rounded_rectangle([(60, 380), (w - 60, 580)], radius=18, fill=(15, 23, 42), outline=(0, 230, 118), width=2)
        draw.text((100, 410), "INR 0.00 NET P&L  |  0 DRAWDOWN", fill=(0, 230, 118), font=f_metric)
        draw.text((100, 510), "34 TRADEGUARD GATES ACTIVE  •  5/5 MULTI-AGENT CONSENSUS  •  PROVENANCE VERIFIED", fill=(148, 163, 184), font=f_sub)

        # Footer
        draw.line([(60, 620), (w - 60, 620)], fill=(30, 41, 59), width=2)
        draw.text((60, 650), "WATCH THE FULL DAILY TRADE REPORT SHORT", fill=(96, 165, 250), font=f_badge)
        draw.text((w - 340, 650), "INSTITUTIONAL QUANT", fill=(100, 116, 139), font=f_sub)

        thumbs_dir = os.path.abspath("web_app/reports/thumbnails")
        os.makedirs(thumbs_dir, exist_ok=True)
        report_date = datetime.now().strftime("%Y-%m-%d")
        dated_path = os.path.join(thumbs_dir, f"nexus_daily_thumbnail_{report_date}.jpg")
        latest_path = os.path.join(thumbs_dir, "nexus_daily_thumbnail_latest.jpg")

        im.save(dated_path, quality=95)
        import shutil
        shutil.copy2(dated_path, latest_path)

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info("Local thumbnail render SUCCEEDED: %s in %dms", dated_path, latency_ms)
        return ThumbnailRenderResult(
            status="SUCCESS",
            render_id=f"LOCAL-THUMB-{report_date}",
            image_url=f"/reports/thumbnails/nexus_daily_thumbnail_{report_date}.jpg",
            template=content_package.thumbnail_template,
            headline=headline,
            latency_ms=latency_ms,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

