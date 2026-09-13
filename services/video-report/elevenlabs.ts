/**
 * services/video-report/elevenlabs.ts
 * ElevenLabs voice narration generation service for NEXUS Daily Trade Report.
 */

export interface VoiceGenerationResult {
  status: 'SUCCESS' | 'VOICE_GENERATION_FAILED';
  audioPath: string | null;
  audioUrl: string | null;
  voiceId: string;
  durationMs: number;
  fileSizeBytes: number;
  provider: 'elevenlabs';
  requestId?: string;
  latencyMs: number;
  errorMessage?: string;
  generatedAt: string;
}

export async function generateNarrationAudio(
  scriptText: string,
  voiceId: string = process.env.ELEVENLABS_VOICE_ID || 'JBFqnCBsd6RMkjVDRZzb'
): Promise<VoiceGenerationResult> {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) {
    return {
      status: 'VOICE_GENERATION_FAILED',
      audioPath: null,
      audioUrl: null,
      voiceId,
      durationMs: 0,
      fileSizeBytes: 0,
      provider: 'elevenlabs',
      latencyMs: 0,
      errorMessage: 'ELEVENLABS_API_KEY is not configured',
      generatedAt: new Date().toISOString(),
    };
  }

  const startTime = Date.now();
  try {
    const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`, {
      method: 'POST',
      headers: {
        'xi-api-key': apiKey,
        'Content-Type': 'application/json',
        Accept: 'audio/mpeg',
      },
      body: JSON.stringify({
        text: scriptText,
        model_id: 'eleven_turbo_v2_5',
        voice_settings: {
          stability: 0.5,
          similarity_boost: 0.75,
        },
      }),
    });

    const latencyMs = Date.now() - startTime;
    if (!res.ok) {
      const errText = await res.text();
      return {
        status: 'VOICE_GENERATION_FAILED',
        audioPath: null,
        audioUrl: null,
        voiceId,
        durationMs: 0,
        fileSizeBytes: 0,
        provider: 'elevenlabs',
        requestId: res.headers.get('request-id') || undefined,
        latencyMs,
        errorMessage: `HTTP ${res.status}: ${errText.slice(0, 200)}`,
        generatedAt: new Date().toISOString(),
      };
    }

    const buffer = await res.arrayBuffer();
    const durationMs = Math.round((buffer.byteLength / 16000) * 1000);

    return {
      status: 'SUCCESS',
      audioPath: null,
      audioUrl: null,
      voiceId,
      durationMs,
      fileSizeBytes: buffer.byteLength,
      provider: 'elevenlabs',
      requestId: res.headers.get('request-id') || undefined,
      latencyMs,
      generatedAt: new Date().toISOString(),
    };
  } catch (error: any) {
    return {
      status: 'VOICE_GENERATION_FAILED',
      audioPath: null,
      audioUrl: null,
      voiceId,
      durationMs: 0,
      fileSizeBytes: 0,
      provider: 'elevenlabs',
      latencyMs: Date.now() - startTime,
      errorMessage: error?.message || String(error),
      generatedAt: new Date().toISOString(),
    };
  }
}
