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
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..trade_reconciliation import DailyReconciliationReport
from ..ai_analyst import DailyAIAnalysisResult
from ..content_strategy import ContentIntelligenceEngine, DailyContentPackage

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
