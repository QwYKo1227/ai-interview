import { describe, expect, it } from 'vitest';
import { buildRealtimeSessionStart, realtimeReconnectDelay } from './realtimeTranscription';

describe('buildRealtimeSessionStart', () => {
  it('enables diarization without constraining or biasing speaker discovery', () => {
    const payload = buildRealtimeSessionStart('interview-1');

    expect(payload.audio).toEqual({ encoding: 'pcm_s16le', sample_rate: 16000, channels: 1 });
    expect(payload.options).toEqual({ partial: true, diarization: true });
    expect(payload.options).not.toHaveProperty('expected_speakers');
    expect(payload.options).not.toHaveProperty('hotwords');
  });

  it('backs off repeated short-lived realtime connections', () => {
    expect([0, 1, 2, 3, 4, 5, 6].map(realtimeReconnectDelay)).toEqual([
      1000,
      2000,
      4000,
      8000,
      15000,
      15000,
      15000,
    ]);
  });
});
