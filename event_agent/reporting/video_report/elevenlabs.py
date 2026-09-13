# =============================================================================
# event_agent/reporting/video_report/elevenlabs.py — ElevenLabs Voice Generator
# =============================================================================
"""
Converts daily narration script into professional financial-news audio using ElevenLabs.
Invariants:
- Never substitutes fake audio.
- On error: status = 'VOICE_GENERATION_FAILED' with full error telemetry.
- Default premade voice: 'JBFqnCBsd6RMkjVDRZzb' (George - Professional News).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

AUDIO_DIR = Path(__file__).resolve().parents[3] / "data" / "reports" / "audio"


@dataclass
class VoiceGenerationResult:
    status: str                         # 'SUCCESS' | 'VOICE_GENERATION_FAILED'
    audio_path: Optional[str]
    audio_url: Optional[str]
    voice_id: str
    duration_ms: int
    file_size_bytes: int
    provider: str = "elevenlabs"
    request_id: Optional[str] = None
    latency_ms: int = 0
    error_message: Optional[str] = None
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ElevenLabsVoiceService:
    """
    ElevenLabs API v1 client for daily financial news narration.
    """

    DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George (premade professional voice)
    MODEL_ID = "eleven_turbo_v2_5"

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or self.DEFAULT_VOICE_ID
        self.output_dir = output_dir or AUDIO_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model_id = self.MODEL_ID

    def generate_narration_audio(
        self,
        script_text: str,
        filename_prefix: str = "daily_report",
    ) -> VoiceGenerationResult:
        """
        Generate MP3 audio from narration text.
        """
        if not self.api_key:
            return VoiceGenerationResult(
                status="VOICE_GENERATION_FAILED",
                audio_path=None,
                audio_url=None,
                voice_id=self.voice_id,
                duration_ms=0,
                file_size_bytes=0,
                error_message="ELEVENLABS_API_KEY is not configured",
            )

        if not script_text or "DATA UNAVAILABLE" in script_text:
            return VoiceGenerationResult(
                status="VOICE_GENERATION_FAILED",
                audio_path=None,
                audio_url=None,
                voice_id=self.voice_id,
                duration_ms=0,
                file_size_bytes=0,
                error_message="Script text is empty or unavailable",
            )

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body = json.dumps({
            "text": script_text,
            "model_id": self.MODEL_ID,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.15,
                "use_speaker_boost": True,
            },
        }).encode("utf-8")

        start_t = time.perf_counter()
        req_id = None
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                audio_bytes = resp.read()
                req_id = resp.headers.get("request-id") or resp.headers.get("x-request-id")

                # Save audio to local disk
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                filename = f"{filename_prefix}_{ts}.mp3"
                file_path = self.output_dir / filename
                with open(file_path, "wb") as f:
                    f.write(audio_bytes)

                # Estimate duration: MP3 @ 128kbps = 16000 bytes/sec
                est_duration_ms = int((len(audio_bytes) / 16000.0) * 1000)

                logger.info(
                    "ElevenLabs audio generated successfully: %s (%d bytes, ~%d ms)",
                    file_path.name, len(audio_bytes), est_duration_ms
                )

                return VoiceGenerationResult(
                    status="SUCCESS",
                    audio_path=str(file_path),
                    audio_url=None,
                    voice_id=self.voice_id,
                    duration_ms=est_duration_ms,
                    file_size_bytes=len(audio_bytes),
                    request_id=req_id,
                    latency_ms=latency_ms,
                )

        except urllib.error.HTTPError as e:
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            err_msg = e.read().decode("utf-8", errors="ignore")
            logger.error("ElevenLabs HTTP %d: %s", e.code, err_msg)
            return VoiceGenerationResult(
                status="VOICE_GENERATION_FAILED",
                audio_path=None,
                audio_url=None,
                voice_id=self.voice_id,
                duration_ms=0,
                file_size_bytes=0,
                request_id=req_id,
                latency_ms=latency_ms,
                error_message=f"HTTP {e.code}: {err_msg[:200]}",
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            logger.error("ElevenLabs error: %s", e)
            return VoiceGenerationResult(
                status="VOICE_GENERATION_FAILED",
                audio_path=None,
                audio_url=None,
                voice_id=self.voice_id,
                duration_ms=0,
                file_size_bytes=0,
                latency_ms=latency_ms,
                error_message=str(e),
            )
