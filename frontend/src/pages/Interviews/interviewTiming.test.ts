import { describe, expect, it } from 'vitest';

import { formatStartCountdown, getInterviewStartTiming } from './interviewTiming';

describe('interview start timing', () => {
  it('blocks before the scheduled instant and exposes a countdown', () => {
    const timing = getInterviewStartTiming('2026-08-01T10:00:00.000Z', Date.parse('2026-08-01T09:58:29.500Z'));

    expect(timing.canStart).toBe(false);
    expect(timing.remainingSeconds).toBe(91);
    expect(timing.countdownText).toBe('1分钟 31秒');
  });

  it('allows starting exactly at the scheduled instant', () => {
    expect(getInterviewStartTiming(
      '2026-08-01T10:00:00.000Z',
      Date.parse('2026-08-01T10:00:00.000Z'),
    ).canStart).toBe(true);
  });

  it('formats long waits without dropping the day component', () => {
    expect(formatStartCountdown(90061)).toBe('1天 1小时 1分钟');
  });
});
