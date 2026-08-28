import { describe, expect, it } from 'vitest';
import dayjs from 'dayjs';

import {
  buildInterviewTimePayload,
  formatInterviewRange,
  validateInterviewTimeRange,
} from './interviewSchedule';

describe('interview schedule time range', () => {
  it('formats explicit Beijing-time ranges', () => {
    expect(formatInterviewRange({
      interview_time: '2026-08-01T02:00:00Z',
      interview_end_time: '2026-08-01T03:30:00Z',
    })).toEqual({ text: '2026-08-01 10:00–11:30', estimated: false });
  });

  it('uses a marked one-hour estimate for legacy rows', () => {
    expect(formatInterviewRange({ interview_time: '2026-08-01T02:00:00Z' }))
      .toEqual({ text: '2026-08-01 10:00–11:00', estimated: true });
  });

  it('accepts quarter-hour ranges', () => {
    expect(validateInterviewTimeRange(dayjs('2026-08-01 10:15'), dayjs('2026-08-01 10:45')))
      .toBeNull();
  });

  it('normalizes hidden seconds produced by minute-only picker shortcuts', () => {
    const start = dayjs('2026-08-30 17:00:38.400');
    const end = dayjs('2026-08-30 18:00:38.400');

    expect(validateInterviewTimeRange(start, end)).toBeNull();
    expect(buildInterviewTimePayload({
      interview_time: start,
      interview_end_time: end,
    })).toEqual({
      interview_time: '2026-08-30T09:00:00.000Z',
      interview_end_time: '2026-08-30T10:00:00.000Z',
    });
  });

  it('rejects non-quarter-hour, reversed, and cross-day ranges', () => {
    expect(validateInterviewTimeRange(dayjs('2026-08-01 10:00'), dayjs('2026-08-01 10:10')))
      .toBe('请选择 15 分钟刻度的时间');
    expect(validateInterviewTimeRange(dayjs('2026-08-01 10:00'), dayjs('2026-08-01 09:30')))
      .toBe('结束时间必须晚于开始时间');
    expect(validateInterviewTimeRange(dayjs('2026-08-01 23:30'), dayjs('2026-08-02 00:30')))
      .toBe('开始和结束时间必须在同一天');
  });
});
