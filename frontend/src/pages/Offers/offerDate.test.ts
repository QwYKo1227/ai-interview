import dayjs from 'dayjs';
import { describe, expect, it } from 'vitest';

import { serializeOfferDate } from './offerDate';

describe('serializeOfferDate', () => {
  it('preserves the calendar day selected in the China timezone', () => {
    const selectedDate = dayjs('2026-08-31T00:00:00+08:00');

    expect(serializeOfferDate(selectedDate)).toBe('2026-08-31');
  });

  it('serializes an empty date as null', () => {
    expect(serializeOfferDate(null)).toBeNull();
  });
});
