import { describe, expect, it } from 'vitest';

import { getInterviewProgress, normalizeInterviewResult } from './List';


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
});
