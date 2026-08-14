export interface PositionListFilters {
  title: string;
  department?: string;
  hiringManagerId?: string;
  priority?: number;
  category?: string;
  status?: string;
}

export const buildPositionListParams = ({
  title,
  department,
  hiringManagerId,
  priority,
  category,
  status,
}: PositionListFilters) => ({
  ...(title ? { title } : {}),
  ...(department ? { department } : {}),
  ...(hiringManagerId ? { hiring_manager_id: hiringManagerId } : {}),
  ...(priority ? { priority } : {}),
  ...(category ? { category } : {}),
  ...(status ? { status } : {}),
});

export const createEmptyPositionListFilters = (): PositionListFilters => ({
  title: '',
  department: undefined,
  hiringManagerId: undefined,
  priority: undefined,
  category: undefined,
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
