/**
 * services/video-report/email.ts
 * Email dispatch service for NEXUS Daily Trade Report.
 */

export interface EmailSendResult {
  status: 'SUCCESS' | 'EMAIL_FAILED' | 'SKIPPED';
  provider: string;
  recipient: string;
  subject: string;
  messageId?: string;
  sentAt?: string;
  latencyMs: number;
  errorMessage?: string;
}

export async function sendDailyReportEmail(
  reportData: Record<string, any>,
  youtubeUrl?: string
): Promise<EmailSendResult> {
  const fromEmail = process.env.REPORT_EMAIL_FROM || 'nexus@samudralasrikanth.com';
  const toEmail = process.env.REPORT_EMAIL_TO || 'samudralasrikanth@gmail.com';
  const provider = (process.env.EMAIL_PROVIDER || 'resend').toLowerCase();
  const apiKey = process.env.EMAIL_PROVIDER_API_KEY;

  const date = reportData.report_date || new Date().toISOString().slice(0, 10);
  const netPnl = Number(reportData.net_pnl || 0);
  const pnlStr = `${netPnl >= 0 ? '+' : ''}₹${netPnl.toLocaleString('en-IN')}`;
  const subject = `NEXUS Daily Trade Report — ${date} — ${pnlStr}`;

  const startTime = Date.now();

  if (!apiKey && provider === 'resend') {
    return {
      status: 'EMAIL_FAILED',
      provider,
      recipient: toEmail,
      subject,
      latencyMs: Date.now() - startTime,
      errorMessage: 'EMAIL_PROVIDER_API_KEY is not configured',
    };
  }

  const textBody = `NEXUS DAILY TRADE REPORT
Date: ${date}
Net P&L: ${pnlStr}
Trades: ${reportData.total_trades || 0}
Win Rate: ${reportData.win_rate || 0}%
YouTube: ${youtubeUrl || 'Pending / OAuth required'}
`;

  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: `NEXUS Intelligence <${fromEmail}>`,
        to: [toEmail],
        subject,
        text: textBody,
      }),
    });

    const latencyMs = Date.now() - startTime;
    if (!res.ok) {
      const err = await res.text();
      return {
        status: 'EMAIL_FAILED',
        provider,
        recipient: toEmail,
        subject,
        latencyMs,
        errorMessage: `HTTP ${res.status}: ${err.slice(0, 200)}`,
      };
    }

    const data = await res.json();
    return {
      status: 'SUCCESS',
      provider,
      recipient: toEmail,
      subject,
      messageId: data.id,
      sentAt: new Date().toISOString(),
      latencyMs,
    };
  } catch (error: any) {
    return {
      status: 'EMAIL_FAILED',
      provider,
      recipient: toEmail,
      subject,
      latencyMs: Date.now() - startTime,
      errorMessage: error?.message || String(error),
    };
  }
}
