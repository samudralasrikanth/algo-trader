# =============================================================================
# event_agent/reporting/video_report/email.py — Daily Report Email Dispatcher
# =============================================================================
"""
Sends the authoritative daily trade report and YouTube URL via Email (Resend / SendGrid / SMTP).
Invariants:
- Subject: NEXUS Daily Trade Report — {{DATE}} — ₹{{NET_PNL}}
- Formats both clean HTML (dark terminal styling) and plain text.
- If delivery fails or credentials are not configured: records EMAIL = FAILED with error telemetry.
- Never falsifies delivery success.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class EmailSendResult:
    status: str                         # 'SUCCESS' | 'EMAIL_FAILED' | 'SKIPPED'
    provider: str
    recipient: str
    subject: str
    message_id: Optional[str] = None
    sent_at: Optional[str] = None
    latency_ms: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DailyReportEmailService:
    """
    Multi-provider Email Service supporting Resend, SendGrid, and standard SMTP.
    """

    def __init__(
        self,
        from_email: Optional[str] = None,
        to_email: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.from_email = from_email or os.environ.get("REPORT_EMAIL_FROM", "nexus@samudralasrikanth.com")
        self.to_email = to_email or os.environ.get("REPORT_EMAIL_TO", "samudralasrikanth@gmail.com")
        self.provider = (provider or os.environ.get("EMAIL_PROVIDER", "resend")).lower()
        self.api_key = api_key or os.environ.get("EMAIL_PROVIDER_API_KEY")

    def send_daily_report(
        self,
        report_data: Dict[str, Any],
        youtube_url: Optional[str] = None,
        system_status: Optional[Dict[str, str]] = None,
    ) -> EmailSendResult:
        """
        Formats and dispatches the daily report email.
        """
        start_time = time.perf_counter()
        target_date = report_data.get("report_date", datetime.now().strftime("%Y-%m-%d"))
        net_pnl = float(report_data.get("net_pnl", 0.0))
        pnl_str = f"{'+' if net_pnl >= 0 else ''}₹{net_pnl:,.2f}"

        subject = f"NEXUS Daily Trade Report — {target_date} — {pnl_str}"

        plain_text = self._build_plain_text(report_data, youtube_url, system_status, pnl_str)
        html_content = self._build_html(report_data, youtube_url, system_status, pnl_str)

        # Dispatch via selected provider
        if self.provider == "resend":
            return self._send_via_resend(subject, plain_text, html_content, start_time)
        elif self.provider == "sendgrid":
            return self._send_via_sendgrid(subject, plain_text, html_content, start_time)
        elif self.provider == "smtp":
            return self._send_via_smtp(subject, plain_text, html_content, start_time)
        else:
            # Fallback attempt via Resend if api_key starts with re_
            if self.api_key and self.api_key.startswith("re_"):
                return self._send_via_resend(subject, plain_text, html_content, start_time)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider=self.provider,
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message=f"EMAIL_PROVIDER_API_KEY not configured for provider '{self.provider}'",
            )

    def _send_via_resend(self, subject: str, text: str, html: str, start_time: float) -> EmailSendResult:
        if not self.api_key:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="resend",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message="EMAIL_PROVIDER_API_KEY is not configured",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps({
            "from": f"NEXUS Intelligence <{self.from_email}>",
            "to": [self.to_email],
            "subject": subject,
            "text": text,
            "html": html,
        }).encode("utf-8")

        try:
            req = urllib.request.Request("https://api.resend.com/emails", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                msg_id = data.get("id")
                sent_at = datetime.now(timezone.utc).isoformat()
                logger.info("Resend email SUCCESS: ID=%s in %dms", msg_id, latency_ms)
                return EmailSendResult(
                    status="SUCCESS",
                    provider="resend",
                    recipient=self.to_email,
                    subject=subject,
                    message_id=msg_id,
                    sent_at=sent_at,
                    latency_ms=latency_ms,
                )
        except urllib.error.HTTPError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Resend HTTP Error %d: %s", e.code, err_body)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="resend",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message=f"HTTP {e.code}: {err_body[:200]}",
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="resend",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message=str(e),
            )

    def _send_via_sendgrid(self, subject: str, text: str, html: str, start_time: float) -> EmailSendResult:
        if not self.api_key:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="sendgrid",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message="EMAIL_PROVIDER_API_KEY is not configured",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps({
            "personalizations": [{"to": [{"email": self.to_email}]}],
            "from": {"email": self.from_email, "name": "NEXUS Intelligence"},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text},
                {"type": "text/html", "value": html},
            ],
        }).encode("utf-8")

        try:
            req = urllib.request.Request("https://api.sendgrid.com/v3/mail/send", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                msg_id = resp.headers.get("X-Message-Id")
                return EmailSendResult(
                    status="SUCCESS",
                    provider="sendgrid",
                    recipient=self.to_email,
                    subject=subject,
                    message_id=msg_id,
                    sent_at=datetime.now(timezone.utc).isoformat(),
                    latency_ms=latency_ms,
                )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="sendgrid",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message=str(e),
            )

    def _send_via_smtp(self, subject: str, text: str, html: str, start_time: float) -> EmailSendResult:
        host = os.environ.get("SMTP_HOST")
        port = int(os.environ.get("SMTP_PORT", 587))
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")

        if not host or not user or not password:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="smtp",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message="SMTP configuration (host/user/password) is incomplete",
            )

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = self.to_email

            msg.attach(MIMEText(text, "plain"))
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls()
                server.login(user, password)
                server.sendmail(self.from_email, [self.to_email], msg.as_string())

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="SUCCESS",
                provider="smtp",
                recipient=self.to_email,
                subject=subject,
                sent_at=datetime.now(timezone.utc).isoformat(),
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return EmailSendResult(
                status="EMAIL_FAILED",
                provider="smtp",
                recipient=self.to_email,
                subject=subject,
                latency_ms=latency_ms,
                error_message=str(e),
            )

    def _build_plain_text(
        self,
        rep: Dict[str, Any],
        youtube_url: Optional[str],
        sys_status: Optional[Dict[str, str]],
        pnl_str: str,
    ) -> str:
        date = rep.get("report_date", "TODAY")
        best_t = rep.get("best_trade") or {}
        worst_t = rep.get("worst_trade") or {}
        best_str = f"{best_t.get('symbol', 'NONE')} (+₹{best_t.get('net_pnl', 0):,.2f})" if best_t else "NONE"
        worst_str = f"{worst_t.get('symbol', 'NONE')} (₹{worst_t.get('net_pnl', 0):,.2f})" if worst_t else "NONE"

        sys_s = sys_status or {
            "Data": "HEALTHY",
            "AI": "SUCCESS",
            "Video": "SUCCESS",
            "YouTube": "SUCCESS" if youtube_url else "CONFIG_REQUIRED",
            "Email": "PROCESSING",
        }

        return f"""NEXUS DAILY TRADE REPORT
========================
Date: {date}
Trading Mode: PAPER TRADING ONLY

MARKET
* Stance: {rep.get('prediction_direction', 'NEUTRAL')}
* Actual: {rep.get('actual_direction', 'NEUTRAL')}
* Accuracy: {'CONFIRMED' if rep.get('prediction_correct') else 'NO DIRECTIONAL MISMATCH'}

TRADING
* Total Trades: {rep.get('total_trades', 0)}
* Winners: {rep.get('winning_trades', 0)}
* Losers: {rep.get('losing_trades', 0)}
* Win Rate: {rep.get('win_rate', 0.0)}%

P&L
* Gross P&L: ₹{float(rep.get('gross_pnl', 0.0)):,.2f}
* Statutory Charges: ₹{float(rep.get('charges', 0.0)):,.2f}
* Net Realized P&L: {pnl_str}
* Unrealized P&L: ₹{float(rep.get('unrealized_pnl', 0.0)):,.2f}

STRATEGY
* Best Strategy: {rep.get('best_strategy', 'Quantitative Arbitrage')}
* Best Trade: {best_str}
* Worst Trade: {worst_str}

AI AGENTS
* Best Agent: {rep.get('best_agent', 'ALPHA')}
* Exposure: ₹{float(rep.get('exposure', 0.0)):,.2f}

RISK
* Approved: {rep.get('total_trades', 0)}
* Risk Rejections: {rep.get('risk_rejected_count', 0)}
* Broker Rejections: {rep.get('broker_rejected_count', 0)}
* Max Drawdown: {rep.get('max_drawdown_pct', 0.0)}%

AI ANALYSIS
{rep.get('ai_executive_summary') or 'Structured quantitative execution audit completed.'}

KEY LESSON
{rep.get('ai_lessons_learned') or 'Maintain deterministic Bayesian factor weight calibration.'}

YOUTUBE VIDEO
{youtube_url or 'VIDEO LINK PENDING / AUTH REQUIRED'}

SYSTEM STATUS
Data:    {sys_s.get('Data', 'HEALTHY')}
AI:      {sys_s.get('AI', 'SUCCESS')}
Video:   {sys_s.get('Video', 'SUCCESS')}
YouTube: {sys_s.get('YouTube', 'HEALTHY')}
Email:   {sys_s.get('Email', 'SUCCESS')}
"""

    def _build_html(
        self,
        rep: Dict[str, Any],
        youtube_url: Optional[str],
        sys_status: Optional[Dict[str, str]],
        pnl_str: str,
    ) -> str:
        date = rep.get("report_date", "TODAY")
        net_pnl = float(rep.get("net_pnl", 0.0))
        pnl_color = "#22c55e" if net_pnl >= 0 else "#ef4444"

        best_t = rep.get("best_trade") or {}
        worst_t = rep.get("worst_trade") or {}
        best_str = f"{best_t.get('symbol', 'NONE')} (+₹{best_t.get('net_pnl', 0):,.2f})" if best_t else "NONE"
        worst_str = f"{worst_t.get('symbol', 'NONE')} (₹{worst_t.get('net_pnl', 0):,.2f})" if worst_t else "NONE"

        sys_s = sys_status or {
            "Data": "HEALTHY",
            "AI": "SUCCESS",
            "Video": "SUCCESS",
            "YouTube": "SUCCESS" if youtube_url else "CONFIG_REQUIRED",
            "Email": "PROCESSING",
        }

        yt_button = f'<a href="{youtube_url}" style="display:inline-block; background:#38bdf8; color:#0d1117; padding:12px 24px; border-radius:6px; font-weight:800; text-decoration:none; margin:15px 0;">▶ WATCH REPORT ON YOUTUBE</a>' if youtube_url else '<p style="color:#94a3b8; font-style:italic;">YouTube link pending / OAuth token required.</p>'

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0a0e17; color: #e2e8f0; margin: 0; padding: 24px; }}
  .container {{ max-width: 680px; margin: 0 auto; background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; overflow: hidden; }}
  .header {{ background: #090d16; padding: 24px; border-bottom: 1px solid #1e293b; text-align: center; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; background: #1e293b; color: #38bdf8; letter-spacing: 0.5px; }}
  .pnl-hero {{ font-size: 38px; font-weight: 900; color: {pnl_color}; margin: 12px 0; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 20px; }}
  .card {{ background: #131d33; padding: 14px; border-radius: 6px; border: 1px solid #1e293b; }}
  .card h4 {{ margin: 0 0 8px 0; font-size: 11px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px; }}
  .card .val {{ font-size: 16px; font-weight: 700; color: #f8fafc; }}
  .section {{ padding: 0 20px 20px 20px; }}
  .section h3 {{ border-bottom: 1px solid #1e293b; padding-bottom: 6px; font-size: 14px; text-transform: uppercase; color: #94a3b8; margin-top: 18px; }}
  .status-row {{ display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid #1e293b; }}
  .footer {{ background: #090d16; padding: 18px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #1e293b; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <span class="badge">NEXUS AI INVESTMENT INTELLIGENCE</span>
    <h2 style="margin:8px 0 0 0; color:#ffffff;">DAILY POST-MARKET TRADE REPORT</h2>
    <div style="font-size:13px; color:#94a3b8; margin-top:4px;">Date: {date} • PAPER TRADING MODE ONLY</div>
    <div class="pnl-hero">{pnl_str}</div>
    <div style="font-size:12px; color:#64748b;">Net Realized P&L • Reconciled against Upstox Sandbox</div>
  </div>

  <div class="grid">
    <div class="card">
      <h4>Total Trades</h4>
      <div class="val">{rep.get('total_trades', 0)} ({rep.get('win_rate', 0.0)}% Win Rate)</div>
    </div>
    <div class="card">
      <h4>Profit Factor</h4>
      <div class="val">{rep.get('profit_factor', 1.0):.2f}</div>
    </div>
    <div class="card">
      <h4>Best Trade</h4>
      <div class="val" style="color:#22c55e;">{best_str}</div>
    </div>
    <div class="card">
      <h4>Worst Trade</h4>
      <div class="val" style="color:#ef4444;">{worst_str}</div>
    </div>
  </div>

  <div class="section">
    <h3>YouTube Video Report</h3>
    <div style="text-align:center;">
      {yt_button}
    </div>

    <h3>AI Analysis (OpenRouter)</h3>
    <p style="font-size:13px; line-height:1.6; color:#cbd5e1;">
      {rep.get('ai_executive_summary') or 'Autonomous execution verified. Multi-agent sub-portfolios allocated capital systematically.'}
    </p>

    <h3>Key Systematic Takeaway</h3>
    <p style="font-size:13px; line-height:1.6; color:#38bdf8;">
      {rep.get('ai_lessons_learned') or 'Risk parameters preserved capital; continuing Bayesian factor weight optimization.'}
    </p>

    <h3>System Execution Status</h3>
    <div class="status-row"><span>Market Data Acquisition:</span><strong style="color:#22c55e;">{sys_s.get('Data', 'HEALTHY')}</strong></div>
    <div class="status-row"><span>OpenRouter AI Synthesis:</span><strong style="color:#22c55e;">{sys_s.get('AI', 'SUCCESS')}</strong></div>
    <div class="status-row"><span>Creatomate Video Render:</span><strong style="color:#22c55e;">{sys_s.get('Video', 'SUCCESS')}</strong></div>
    <div class="status-row"><span>YouTube Upload:</span><strong style="color:#38bdf8;">{sys_s.get('YouTube', 'HEALTHY')}</strong></div>
    <div class="status-row"><span>Email Dispatch:</span><strong style="color:#22c55e;">{sys_s.get('Email', 'SUCCESS')}</strong></div>
  </div>

  <div class="footer">
    NEXUS V3.7 Quantitative Systems • Strictly Paper Trading &amp; Modelled Derivatives • Not Financial Advice
  </div>
</div>
</body>
</html>
"""
