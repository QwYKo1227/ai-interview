import { describe, expect, it } from 'vitest';

import { canRecordFullInterview } from './recordingControls';

describe('canRecordFullInterview', () => {
  it('allows every assigned interviewer to start a full interview recording', () => {
    const panelMembers = ['interviewer-1', 'interviewer-2'];

    expect(canRecordFullInterview(panelMembers, 'interviewer-1')).toBe(true);
    expect(canRecordFullInterview(panelMembers, 'interviewer-2')).toBe(true);
  });

  it('does not expose recording controls to an unassigned user', () => {
    expect(
      canRecordFullInterview(
        ['interviewer-1', 'interviewer-2'],
        'interviewer-3',
      ),
    ).toBe(false);
  });

  it('keeps recording available for legacy interviews without a panel list', () => {
    expect(canRecordFullInterview([], 'interviewer-1')).toBe(true);
  });
});
