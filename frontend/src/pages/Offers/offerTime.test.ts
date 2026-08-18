import { describe, expect, it } from 'vitest';
import { formatOfferDateTime } from './offerTime';

describe('formatOfferDateTime', () => {
  it('treats legacy timezone-less Offer timestamps as UTC and displays Beijing time', () => {
    expect(formatOfferDateTime('2026-08-17T09:30:24.223602')).toBe('2026-08-17 17:30');
  });

  it('displays timezone-aware timestamps in Beijing time', () => {
    expect(formatOfferDateTime('2026-08-17T09:30:24.223602+00:00')).toBe('2026-08-17 17:30');
  });
});
