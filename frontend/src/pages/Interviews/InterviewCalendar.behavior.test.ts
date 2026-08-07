import { describe, expect, it } from 'vitest';

import {
  getCalendarEventClass,
  formatCalendarTitle,
  getOverflowDayRecords,
  MONTH_DAY_MAX_EVENTS,
} from './InterviewCalendar';

describe('interview calendar month presentation', () => {
  it('uses an adaptive event limit instead of a fixed three-event cap', () => {
    expect(MONTH_DAY_MAX_EVENTS).toBe(true);
  });

  it('maps interview progress to a visible event status class', () => {
    expect(getCalendarEventClass({ lifecycle_state: 'scheduled' })).toContain('interview-event--scheduled');
    expect(getCalendarEventClass({ lifecycle_state: 'in_progress' })).toContain('interview-event--in_progress');
    expect(getCalendarEventClass({ lifecycle_state: 'ended' })).toContain('interview-event--pending_decision');
    expect(getCalendarEventClass({ lifecycle_state: 'cancelled' })).toContain('interview-event--cancelled');
  });

  it('deduplicates all interviews shown in the overflow dialog', () => {
    const first = { id: 'one' };
    const second = { id: 'two' };
    const info = {
      allSegs: [
        { event: { extendedProps: { record: first } } },
        { event: { extendedProps: { record: first } } },
        { event: { extendedProps: { record: second } } },
      ],
    } as any;

    expect(getOverflowDayRecords(info)).toEqual([first, second]);
  });

  it('shows the complete Monday-to-Sunday range in the week title', () => {
    expect(formatCalendarTitle(
      'timeGridWeek',
      new Date('2026-08-02T16:00:00.000Z'),
      new Date('2026-08-09T16:00:00.000Z'),
      '2026年8月',
    )).toBe('2026年8月3日 - 2026年8月9日');
    expect(formatCalendarTitle(
      'dayGridMonth',
      new Date('2026-07-26T16:00:00.000Z'),
      new Date('2026-09-06T16:00:00.000Z'),
      '2026年8月',
    )).toBe('2026年8月');
  });
});
