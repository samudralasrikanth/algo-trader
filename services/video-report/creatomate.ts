/**
 * services/video-report/creatomate.ts
 * Creatomate video generation service for NEXUS Daily Trade Report.
 */

export interface VideoRenderResult {
  status: 'SUCCESS' | 'VIDEO_RENDER_FAILED';
  renderId: string | null;
  videoUrl: string | null;
  durationSeconds: number;
  outputFormat: string;
  provider: 'creatomate';
  latencyMs: number;
  errorMessage?: string;
  createdAt: string;
  completedAt?: string;
}

export async function createDailyReportVideo(
  reportData: Record<string, any>,
  audioUrlOrPath?: string,
  timeoutSeconds = 180
): Promise<VideoRenderResult> {
  const apiKey = process.env.CREATOMATE_API_KEY;
  if (!apiKey) {
    return {
      status: 'VIDEO_RENDER_FAILED',
      renderId: null,
      videoUrl: null,
      durationSeconds: 0,
      outputFormat: 'mp4',
      provider: 'creatomate',
      latencyMs: 0,
      errorMessage: 'CREATOMATE_API_KEY is not configured',
      createdAt: new Date().toISOString(),
    };
  }

  const startTime = Date.now();
  const netPnl = Number(reportData.net_pnl || 0);
  const pnlStr = `${netPnl >= 0 ? '+' : ''}₹${netPnl.toLocaleString('en-IN')}`;

  const sourceSpec = {
    output_format: 'mp4',
    width: 1920,
    height: 1080,
    duration: 45,
    elements: [
      {
        type: 'shape',
        shape: 'rectangle',
        fill_color: '#0a0e17',
        width: '100%',
        height: '100%',
      },
      {
        type: 'text',
        text: 'NEXUS DAILY TRADE REPORT',
        font_family: 'Montserrat',
        font_weight: '800',
        font_size: '50 vmin',
        fill_color: '#ffffff',
        y: '25%',
      },
      {
        type: 'text',
        text: pnlStr,
        font_family: 'Montserrat',
        font_weight: '900',
        font_size: '80 vmin',
        fill_color: netPnl >= 0 ? '#22c55e' : '#ef4444',
        y: '50%',
      },
      {
        type: 'text',
        text: 'PAPER TRADING ONLY • RECONCILED POST-MARKET',
        font_family: 'Montserrat',
        font_weight: '600',
        font_size: '22 vmin',
        fill_color: '#64748b',
        y: '85%',
      },
    ],
  };

  try {
    const res = await fetch('https://api.creatomate.com/v1/renders', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      },
      body: JSON.stringify({ source: sourceSpec }),
    });

    if (!res.ok) {
      const errText = await res.text();
      return {
        status: 'VIDEO_RENDER_FAILED',
        renderId: null,
        videoUrl: null,
        durationSeconds: 0,
        outputFormat: 'mp4',
        provider: 'creatomate',
        latencyMs: Date.now() - startTime,
        errorMessage: `HTTP ${res.status}: ${errText.slice(0, 200)}`,
        createdAt: new Date().toISOString(),
      };
    }

    const data = await res.json();
    const renderItem = Array.isArray(data) ? data[0] : data;
    const renderId = renderItem.id;

    // Poll until complete
    const pollStart = Date.now();
    while (Date.now() - pollStart < timeoutSeconds * 1000) {
      await new Promise(r => setTimeout(r, 3000));
      const pollRes = await fetch(`https://api.creatomate.com/v1/renders/${renderId}`, {
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        },
      });

      if (pollRes.ok) {
        const pollData = await pollRes.json();
        if (pollData.status === 'succeeded') {
          return {
            status: 'SUCCESS',
            renderId,
            videoUrl: pollData.url,
            durationSeconds: Number(pollData.duration || 45),
            outputFormat: 'mp4',
            provider: 'creatomate',
            latencyMs: Date.now() - startTime,
            createdAt: new Date().toISOString(),
            completedAt: new Date().toISOString(),
          };
        } else if (pollData.status === 'failed') {
          return {
            status: 'VIDEO_RENDER_FAILED',
            renderId,
            videoUrl: null,
            durationSeconds: 0,
            outputFormat: 'mp4',
            provider: 'creatomate',
            latencyMs: Date.now() - startTime,
            errorMessage: pollData.error_message || 'Creatomate render failed',
            createdAt: new Date().toISOString(),
          };
        }
      }
    }

    return {
      status: 'VIDEO_RENDER_FAILED',
      renderId,
      videoUrl: null,
      durationSeconds: 0,
      outputFormat: 'mp4',
      provider: 'creatomate',
      latencyMs: Date.now() - startTime,
      errorMessage: `Render polling timed out after ${timeoutSeconds}s`,
      createdAt: new Date().toISOString(),
    };
  } catch (error: any) {
    return {
      status: 'VIDEO_RENDER_FAILED',
      renderId: null,
      videoUrl: null,
      durationSeconds: 0,
      outputFormat: 'mp4',
      provider: 'creatomate',
      latencyMs: Date.now() - startTime,
      errorMessage: error?.message || String(error),
      createdAt: new Date().toISOString(),
    };
  }
}
