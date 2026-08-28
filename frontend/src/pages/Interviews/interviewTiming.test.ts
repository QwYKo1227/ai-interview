import { describe, expect, it } from 'vitest';

import { formatStartCountdown, getInterviewStartTiming } from './interviewTiming';

describe('interview start timing', () => {
  it('blocks until the early-start window and exposes a countdown to unlock', () => {
    const timing = getInterviewStartTiming('2026-08-01T10:00:00.000Z', Date.parse('2026-08-01T09:43:29.500Z'));

    expect(timing.canStart).toBe(false);
    expect(timing.isEarlyStart).toBe(false);
    expect(timing.remainingSeconds).toBe(91);
    expect(timing.countdownText).toBe('1分钟 31秒');
  });

  it('allows starting exactly 15 minutes early and marks it for confirmation', () => {
    const timing = getInterviewStartTiming(
      '2026-08-01T10:00:00.000Z',
      Date.parse('2026-08-01T09:45:00.000Z'),
    );

    expect(timing.canStart).toBe(true);
    expect(timing.isEarlyStart).toBe(true);
  });

  it('allows starting at the scheduled instant without marking it as early', () => {
    const timing = getInterviewStartTiming(
      '2026-08-01T10:00:00.000Z',
      Date.parse('2026-08-01T10:00:00.000Z'),
    );

    expect(timing.canStart).toBe(true);
    expect(timing.isEarlyStart).toBe(false);
  });

  it('formats long waits without dropping the day component', () => {
    expect(formatStartCountdown(90061)).toBe('1天 1小时 1分钟');
  });
});
