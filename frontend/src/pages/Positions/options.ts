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
