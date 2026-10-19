import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { describe, expect, it } from 'vitest';

import { serializeOfferDate } from './offerDate';

dayjs.extend(utc);

describe('serializeOfferDate', () => {
  it('preserves the calendar day selected in the China timezone', () => {
    const selectedDate = dayjs.utc('2026-08-31T00:00:00+08:00').utcOffset(8 * 60);

    expect(serializeOfferDate(selectedDate)).toBe('2026-08-31');
  });

  it('serializes an empty date as null', () => {
    expect(serializeOfferDate(null)).toBeNull();
  });
});
