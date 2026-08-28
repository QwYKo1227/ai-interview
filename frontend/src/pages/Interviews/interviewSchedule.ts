import dayjs, { type Dayjs } from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

dayjs.extend(utc);
dayjs.extend(timezone);

export const BEIJING_TIMEZONE = 'Asia/Shanghai';
export const LEGACY_INTERVIEW_MINUTES = 60;
export const INTERVIEW_MINUTE_STEP = 15;

export const normalizeInterviewTime = (value: Dayjs) => value.second(0).millisecond(0);

export const toBeijingTime = (value?: string | Date | Dayjs | null) => {
  if (!value) return null;
  return dayjs(value).tz(BEIJING_TIMEZONE);
};

export const toBeijingIso = (value: Dayjs) => (
  value.tz(BEIJING_TIMEZONE, true).toISOString()
);

export const getInterviewEnd = (record: any) => {
  const explicitEnd = toBeijingTime(record?.interview_end_time);
  if (explicitEnd) return { value: explicitEnd, estimated: false };
  const start = toBeijingTime(record?.interview_time);
  return {
    value: start?.add(LEGACY_INTERVIEW_MINUTES, 'minute') || null,
    estimated: Boolean(start),
  };
};

export const formatInterviewRange = (record: any) => {
  const start = toBeijingTime(record?.interview_time);
  const { value: end, estimated } = getInterviewEnd(record);
  if (!start || !end) return { text: '-', estimated: false };
  const sameDay = start.format('YYYY-MM-DD') === end.format('YYYY-MM-DD');
  const text = sameDay
    ? `${start.format('YYYY-MM-DD HH:mm')}–${end.format('HH:mm')}`
    : `${start.format('YYYY-MM-DD HH:mm')}–${end.format('YYYY-MM-DD HH:mm')}`;
  return { text, estimated };
};

export const validateInterviewTimeRange = (start?: Dayjs | null, end?: Dayjs | null) => {
  if (!start || !end) return null;
  const startCn = normalizeInterviewTime(start.tz(BEIJING_TIMEZONE, true));
  const endCn = normalizeInterviewTime(end.tz(BEIJING_TIMEZONE, true));
  if (!endCn.isAfter(startCn)) return '结束时间必须晚于开始时间';
  if (startCn.format('YYYY-MM-DD') !== endCn.format('YYYY-MM-DD')) return '开始和结束时间必须在同一天';
  if ([startCn, endCn].some((value) => value.minute() % INTERVIEW_MINUTE_STEP !== 0)) {
    return '请选择 15 分钟刻度的时间';
  }
  return null;
};

export const buildInterviewTimePayload = (values: any) => ({
  interview_time: toBeijingIso(normalizeInterviewTime(values.interview_time)),
  interview_end_time: toBeijingIso(normalizeInterviewTime(values.interview_end_time)),
});

export const defaultInterviewEnd = (start: Dayjs) => (
  normalizeInterviewTime(start).add(LEGACY_INTERVIEW_MINUTES, 'minute')
);

export const getScheduleErrorMessage = (error: unknown, fallback: string) => {
  const detail = (error as any)?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (!detail || typeof detail !== 'object') return fallback;
  const conflicts = Array.isArray(detail.conflicts) ? detail.conflicts : [];
  if (!conflicts.length) return detail.message || fallback;
  const conflictText = conflicts.slice(0, 3).map((conflict: any) => {
    const start = toBeijingTime(conflict.interview_time)?.format('MM-DD HH:mm');
    const end = toBeijingTime(conflict.interview_end_time)?.format('HH:mm');
    const reasons = Array.isArray(conflict.reasons) ? conflict.reasons.join('、') : '时间';
    return `${conflict.candidate_name || '候选人'} ${start || ''}–${end || ''}（${reasons}冲突）`;
  }).join('；');
  return `${detail.message || fallback}：${conflictText}`;
};
