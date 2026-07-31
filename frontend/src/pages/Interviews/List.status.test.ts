import { describe, expect, it } from 'vitest';

import { buildInterviewSchedulePayload, getInterviewProgress, normalizeInterviewResult } from './List';


describe('interview list status presentation', () => {
  it('shows cancellation even when a legacy status field is stale', () => {
    expect(getInterviewProgress({ lifecycle_state: 'cancelled', status: 'scheduled' })).toBe('cancelled');
    expect(getInterviewProgress({ lifecycle_state: 'scheduled', status: 'cancelled' })).toBe('cancelled');
  });

  it('separates pending decisions from confirmed decisions', () => {
    expect(getInterviewProgress({ lifecycle_state: 'ended', result: 'pending' })).toBe('pending_decision');
    expect(getInterviewProgress({ lifecycle_state: 'ended', final_decision_at: '2026-07-30T00:00:00Z' })).toBe('decided');
  });

  it('normalizes retired interview results for historical records', () => {
    expect(normalizeInterviewResult('hired')).toBe('passed');
    expect(normalizeInterviewResult('waitlist')).toBe('pending');
  });

  it('clears schedule fields that do not apply to the selected interview form', () => {
    const interviewTime = { toISOString: () => '2026-08-01T02:00:00.000Z' };

    expect(buildInterviewSchedulePayload({
      panel_members: ['one'],
      interview_time: interviewTime,
      interview_type: 'video',
      interview_location: '旧办公室',
      meeting_link: 'https://meeting.example.com/new',
    })).toEqual({
      panel_members: ['one'],
      interview_time: '2026-08-01T02:00:00.000Z',
      interview_type: 'video',
      interview_location: null,
      meeting_link: 'https://meeting.example.com/new',
    });
  });
});
