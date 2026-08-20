import { describe, expect, it } from 'vitest';
import dayjs from 'dayjs';

import {
  buildInterviewSchedulePayload,
  createEmptyInterviewListFilters,
  getInterviewMemberIds,
  getInterviewProgress,
  mergeSchedulableResumes,
  matchesInterviewFilters,
  normalizeInterviewResult,
  SCHEDULABLE_RESUME_STATUSES,
} from './List';


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

  it('filters interviews by candidate, position, and any assigned interviewer', () => {
    const interview = {
      resume_id: 'resume-1',
      position_id: 'position-1',
      panel_members: ['interviewer-1'],
      panels: [{ interviewer_id: 'interviewer-2' }],
      lifecycle_state: 'scheduled',
      result: 'pending',
    };

    expect(getInterviewMemberIds(interview)).toEqual(['interviewer-1', 'interviewer-2']);
    expect(matchesInterviewFilters(interview, {
      candidateId: 'resume-1',
      positionId: 'position-1',
      interviewerId: 'interviewer-2',
    })).toBe(true);
    expect(matchesInterviewFilters(interview, { candidateId: 'resume-2' })).toBe(false);
    expect(matchesInterviewFilters(interview, { positionId: 'position-2' })).toBe(false);
    expect(matchesInterviewFilters(interview, { interviewerId: 'interviewer-3' })).toBe(false);
  });

  it('resets every interview filter', () => {
    expect(createEmptyInterviewListFilters()).toEqual({});
  });

  it('includes both first-round and next-round candidates when scheduling', () => {
    expect(SCHEDULABLE_RESUME_STATUSES).toEqual([
      'pending_interview',
      'pending_next_interview',
    ]);
    expect(mergeSchedulableResumes([
      [{ id: 'first-round', status: 'pending_interview' }],
      [
        { id: 'next-round', status: 'pending_next_interview' },
        { id: 'first-round', status: 'pending_interview' },
      ],
    ])).toEqual([
      { id: 'first-round', status: 'pending_interview' },
      { id: 'next-round', status: 'pending_next_interview' },
    ]);
  });

  it('clears schedule fields that do not apply to the selected interview form', () => {
    const interviewTime = dayjs('2026-08-01T10:00:00');
    const interviewEndTime = dayjs('2026-08-01T11:00:00');

    expect(buildInterviewSchedulePayload({
      panel_members: ['one'],
      interview_time: interviewTime,
      interview_end_time: interviewEndTime,
      interview_type: 'video',
      interview_location: '旧办公室',
      meeting_link: 'https://meeting.example.com/new',
    })).toEqual({
      panel_members: ['one'],
      interview_time: '2026-08-01T02:00:00.000Z',
      interview_end_time: '2026-08-01T03:00:00.000Z',
      interview_type: 'video',
      interview_location: null,
      meeting_link: 'https://meeting.example.com/new',
    });
  });
});
