export const PRIORITY_OPTIONS = [1, 2, 3, 4, 5].map((value) => ({
  value,
  label: String(value),
}));

export const POSITION_CATEGORY_OPTIONS = [
  { value: 'uncategorized', label: '未分类' },
  { value: 'campus', label: '校园招聘' },
  { value: 'domestic_functional', label: '国内职能岗位' },
  { value: 'domestic_rd', label: '国内研发岗位' },
  { value: 'overseas', label: '海外岗位' },
  { value: 'executive_expert', label: '高管／关键专家' },
];

export const getCategoryLabel = (category: string) => (
  POSITION_CATEGORY_OPTIONS.find(({ value }) => value === category)?.label || '未分类'
);

export const normalizePositionClassification = <T extends Record<string, unknown>>(values: T) => ({
  ...values,
  priority: values.priority ?? 3,
  category: values.category ?? 'uncategorized',
});

export type PositionStatus = 'open' | 'published' | 'paused' | 'closed' | 'cancelled';

export const POSITION_STATUS_OPTIONS: Array<{ value: PositionStatus; label: string; color: string }> = [
  { value: 'open', label: '待发布', color: 'warning' },
  { value: 'published', label: '招聘中', color: 'processing' },
  { value: 'paused', label: '暂停', color: 'orange' },
  { value: 'closed', label: '已关闭', color: 'success' },
  { value: 'cancelled', label: '已取消', color: 'error' },
];

const STATUS_TRANSITIONS: Record<PositionStatus, PositionStatus[]> = {
  open: ['published', 'cancelled'],
  published: ['paused', 'closed', 'cancelled'],
  paused: ['published', 'closed', 'cancelled'],
  closed: [],
  cancelled: [],
};

export const getStatusOption = (status: string) => {
  const normalizedStatus = status.toLowerCase();
  return POSITION_STATUS_OPTIONS.find(({ value }) => value === normalizedStatus)
    ?? { value: status, label: status, color: 'default' };
};

export const getAllowedStatusOptions = (
  currentStatus: PositionStatus | undefined,
  isAdmin: boolean,
) => {
  if (!currentStatus) return POSITION_STATUS_OPTIONS.filter(({ value }) => ['open', 'published'].includes(value));
  const targets = new Set<PositionStatus>([currentStatus, ...STATUS_TRANSITIONS[currentStatus]]);
  if (isAdmin && ['closed', 'cancelled'].includes(currentStatus)) {
    targets.add('open');
    targets.add('published');
  }
  return POSITION_STATUS_OPTIONS.filter(({ value }) => targets.has(value));
};

export const statusChangeRequiresReason = (
  currentStatus: PositionStatus | undefined,
  targetStatus: PositionStatus | undefined,
) => Boolean(
  currentStatus
  && targetStatus
  && currentStatus !== targetStatus
  && (['paused', 'cancelled'].includes(targetStatus) || ['closed', 'cancelled'].includes(currentStatus)),
);
