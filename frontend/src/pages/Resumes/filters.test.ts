import { describe, expect, it } from 'vitest';
import {
  buildCurrentResumeListParams,
  buildResumeListParams,
  createEmptyResumeListFilters,
} from './filters';

describe('resume filters', () => {
  it('combines candidate, position, status, and reviewer filters', () => {
    expect(buildResumeListParams({
      candidateName: 'Alice',
      positionId: 'position-id',
      status: 'pending_review',
    }, 'reviewer-id')).toEqual({
      candidate_name: 'Alice',
      position_id: 'position-id',
      status: 'pending_review',
      reviewer_id: 'reviewer-id',
    });
  });

  it('creates an empty three-field filter state for reset', () => {
    expect(createEmptyResumeListFilters()).toEqual({
      candidateName: '',
      positionId: undefined,
      status: undefined,
    });
  });

  it('reads the latest filters when a stable refresh is invoked', () => {
    const ref = { current: createEmptyResumeListFilters() };
    const refresh = () => buildCurrentResumeListParams(ref, undefined);
    ref.current = {
      candidateName: 'Bob',
      positionId: 'new-position',
      status: 'completed',
    };

    expect(refresh()).toEqual({
      candidate_name: 'Bob',
      position_id: 'new-position',
      status: 'completed',
    });
  });
});
