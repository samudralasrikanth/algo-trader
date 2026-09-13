/**
 * services/video-report/youtube.ts
 * YouTube upload service for NEXUS Daily Trade Report.
 */

export interface YouTubeUploadResult {
  status: 'SUCCESS' | 'YOUTUBE_UPLOAD_FAILED' | 'SKIPPED';
  videoId: string | null;
  videoUrl: string | null;
  title: string;
  privacyStatus: string;
  uploadTimestamp: string;
  latencyMs: number;
  errorMessage?: string;
}

export async function uploadDailyReportVideo(
  videoUrlOrPath: string,
  reportData: Record<string, any>
): Promise<YouTubeUploadResult> {
  const publishMode = (process.env.YOUTUBE_PUBLISH_MODE || 'private').toLowerCase();
  const date = reportData.report_date || new Date().toISOString().slice(0, 10);
  const netPnl = Number(reportData.net_pnl || 0);
  const pnlStr = `${netPnl >= 0 ? '+' : ''}₹${netPnl.toLocaleString('en-IN')}`;
  const title = `NEXUS Daily Trade Report — ${date} | P&L ${pnlStr}`;

  const token = process.env.YOUTUBE_ACCESS_TOKEN || (
    process.env.YOUTUBE_API_CREDENTIALS?.startsWith('ya29.') ? process.env.YOUTUBE_API_CREDENTIALS : null
  );

  const startTime = Date.now();

  if (!token) {
    return {
      status: 'YOUTUBE_UPLOAD_FAILED',
      videoId: null,
      videoUrl: null,
      title,
      privacyStatus: publishMode,
      uploadTimestamp: new Date().toISOString(),
      latencyMs: Date.now() - startTime,
      errorMessage: 'OAUTH_AUTHENTICATION_REQUIRED: Valid YouTube OAuth access token required',
    };
  }

  try {
    // 1. Fetch video bytes if URL
    let videoBlob: Blob;
    if (videoUrlOrPath.startsWith('http')) {
      const vidRes = await fetch(videoUrlOrPath);
      videoBlob = await vidRes.blob();
    } else {
      throw new Error('Local file streaming requires Node fs integration');
    }

    const metadata = {
      snippet: {
        title,
        description: `NEXUS AI Investment Intelligence\nDaily automated post-market trade report.\nTrading Mode: PAPER TRADING ONLY\nDate: ${date}\nTrades: ${reportData.total_trades || 0}\nNet P&L: ${pnlStr}\nWin Rate: ${reportData.win_rate || 0}%`,
        tags: ['NEXUS', 'NIFTY', 'Trading', 'Paper Trading', 'Daily Trade Report'],
        categoryId: '27',
      },
      status: {
        privacyStatus: publishMode,
      },
    };

    const initRes = await fetch(
      'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          'X-Upload-Content-Length': String(videoBlob.size),
          'X-Upload-Content-Type': 'video/mp4',
        },
        body: JSON.stringify(metadata),
      }
    );

    if (!initRes.ok) {
      const err = await initRes.text();
      return {
        status: 'YOUTUBE_UPLOAD_FAILED',
        videoId: null,
        videoUrl: null,
        title,
        privacyStatus: publishMode,
        uploadTimestamp: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        errorMessage: `HTTP ${initRes.status}: ${err.slice(0, 200)}`,
      };
    }

    const uploadUrl = initRes.headers.get('Location');
    if (!uploadUrl) {
      throw new Error('No upload location returned by YouTube');
    }

    const uploadRes = await fetch(uploadUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': 'video/mp4',
        'Content-Length': String(videoBlob.size),
      },
      body: videoBlob,
    });

    if (!uploadRes.ok) {
      const err = await uploadRes.text();
      return {
        status: 'YOUTUBE_UPLOAD_FAILED',
        videoId: null,
        videoUrl: null,
        title,
        privacyStatus: publishMode,
        uploadTimestamp: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        errorMessage: `HTTP ${uploadRes.status}: ${err.slice(0, 200)}`,
      };
    }

    const uploadData = await uploadRes.json();
    const videoId = uploadData.id;

    return {
      status: 'SUCCESS',
      videoId,
      videoUrl: `https://youtu.be/${videoId}`,
      title,
      privacyStatus: publishMode,
      uploadTimestamp: new Date().toISOString(),
      latencyMs: Date.now() - startTime,
    };
  } catch (error: any) {
    return {
      status: 'YOUTUBE_UPLOAD_FAILED',
      videoId: null,
      videoUrl: null,
      title,
      privacyStatus: publishMode,
      uploadTimestamp: new Date().toISOString(),
      latencyMs: Date.now() - startTime,
      errorMessage: error?.message || String(error),
    };
  }
}
