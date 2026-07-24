export interface PositionListFilters {
  title: string;
  department?: string;
  hiringManagerId?: string;
  urgency?: string;
  status?: string;
}

export const buildPositionListParams = ({
  title,
  department,
  hiringManagerId,
  urgency,
  status,
}: PositionListFilters) => ({
  ...(title ? { title } : {}),
  ...(department ? { department } : {}),
  ...(hiringManagerId ? { hiring_manager_id: hiringManagerId } : {}),
  ...(urgency ? { urgency } : {}),
  ...(status ? { status } : {}),
});

export const createEmptyPositionListFilters = (): PositionListFilters => ({
  title: '',
  department: undefined,
  hiringManagerId: undefined,
  urgency: undefined,
  status: undefined,
});

export const buildCurrentPositionListParams = (
  filtersRef: { readonly current: PositionListFilters },
) => buildPositionListParams(filtersRef.current);

export const reconcileHiringManagerSelection = (
  selectedId: string | undefined,
  options: ReadonlyArray<{ id: string }>,
): string | undefined => (
  selectedId && options.some(({ id }) => id === selectedId)
    ? selectedId
    : undefined
);

export const reconcileDepartmentSelection = (
  selectedDepartment: string | undefined,
  departments: readonly string[],
): string | undefined => (
  selectedDepartment && departments.includes(selectedDepartment)
    ? selectedDepartment
    : undefined
);
