import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

dayjs.extend(utc);
dayjs.extend(timezone);

const BEIJING_TIMEZONE = 'Asia/Shanghai';
const EXPLICIT_TIMEZONE = /(Z|[+-]\d{2}:?\d{2})$/i;

export const formatOfferDateTime = (value?: string | null) => {
  if (!value) return '-';
  const instant = EXPLICIT_TIMEZONE.test(value) ? dayjs(value) : dayjs.utc(value);
  return instant.tz(BEIJING_TIMEZONE).format('YYYY-MM-DD HH:mm');
};
