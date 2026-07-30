import { describe, expect, it } from 'vitest';
import { buildRealtimeSessionStart } from './realtimeTranscription';

describe('buildRealtimeSessionStart', () => {
  it('enables diarization without constraining or biasing speaker discovery', () => {
    const payload = buildRealtimeSessionStart('interview-1');

    expect(payload.audio).toEqual({ encoding: 'pcm_s16le', sample_rate: 16000, channels: 1 });
    expect(payload.options).toEqual({ partial: true, diarization: true });
    expect(payload.options).not.toHaveProperty('expected_speakers');
    expect(payload.options).not.toHaveProperty('hotwords');
  });
});
