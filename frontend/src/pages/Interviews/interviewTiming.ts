export type InterviewStartTiming = {
  canStart: boolean;
  isEarlyStart: boolean;
  remainingSeconds: number;
  countdownText: string;
};

export const INTERVIEW_EARLY_START_WINDOW_MS = 15 * 60 * 1000;

export const formatStartCountdown = (totalSeconds: number): string => {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  if (days > 0) return `${days}天 ${hours}小时 ${minutes}分钟`;
  if (hours > 0) return `${hours}小时 ${minutes}分钟 ${remainingSeconds}秒`;
  if (minutes > 0) return `${minutes}分钟 ${remainingSeconds}秒`;
  return `${remainingSeconds}秒`;
};

export const getInterviewStartTiming = (
  interviewTime?: string | null,
  nowMs = Date.now(),
): InterviewStartTiming => {
  if (!interviewTime) {
    return { canStart: true, isEarlyStart: false, remainingSeconds: 0, countdownText: '可以开始' };
  }
  const scheduledMs = new Date(interviewTime).getTime();
  if (!Number.isFinite(scheduledMs) || nowMs >= scheduledMs) {
    return { canStart: true, isEarlyStart: false, remainingSeconds: 0, countdownText: '可以开始' };
  }

  const startAvailableMs = scheduledMs - INTERVIEW_EARLY_START_WINDOW_MS;
  if (nowMs >= startAvailableMs) {
    return { canStart: true, isEarlyStart: true, remainingSeconds: 0, countdownText: '可以开始' };
  }

  const remainingSeconds = Math.ceil((startAvailableMs - nowMs) / 1000);
  return {
    canStart: false,
    isEarlyStart: false,
    remainingSeconds,
    countdownText: formatStartCountdown(remainingSeconds),
  };
};
