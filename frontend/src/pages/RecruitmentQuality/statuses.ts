export const statuses = {
  complete: { label: '按时完成', color: 'success', description: '所需事项均已在规定时间内完成。' },
  not_applicable: { label: '无需处理', color: 'default', description: '当前流程不要求处理这项事项。' },
  pending: { label: '进行中', color: 'processing', description: '仍有事项待完成，目前未逾期。' },
  missing: { label: '逾期未完成', color: 'error', description: '已超过规定时间，仍有事项未完成。' },
  unknown: { label: '缺少时间记录', color: 'default', description: '缺少操作时间，无法判断是否按时完成，不代表未处理。' },
  late: { label: '逾期后完成', color: 'warning', description: '事项已完成，但曾超过规定时间，逾期记录仍保留。' },
  paused: { label: '已暂停', color: 'warning', description: '候选人列为备选，恢复跟进后重新计时；已有逾期记录保留。' },
  future: { label: '未开始', color: 'default', description: '流程尚未进行到这一步。' },
};

export const statusFilters = [
  { value: 'attention', label: '需要关注', description: '查看待处理、已暂停或缺少时间记录的事项。' },
  { value: 'all', label: '全部状态', description: '查看所有候选人的流程。' },
  { value: 'overdue', label: '有逾期记录', description: '查看曾经逾期的事项，包括尚未完成和逾期后完成。' },
  ...Object.entries(statuses).filter(([value]) => value !== 'future').map(([value, status]) => ({ value, ...status })),
];

export const legendStates = ['complete', 'pending', 'missing', 'late', 'paused', 'unknown'] as const;
