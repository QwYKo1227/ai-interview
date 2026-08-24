import type { Dayjs } from 'dayjs';

export const serializeOfferDate = (value?: Dayjs | null): string | null => (
  value?.format('YYYY-MM-DD') ?? null
);
