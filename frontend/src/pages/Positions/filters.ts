export interface PositionListFilters {
  title: string;
  department?: string;
  hiringManagerId?: string;
  priority?: number;
  category?: string;
  status?: string;
  deletedOnly?: boolean;
}

const POSITION_LIST_FILTERS_STORAGE_PREFIX = 'position-list-filters';

type PositionListFilterStorage = Pick<Storage, 'getItem' | 'setItem'>;

const getPositionListFiltersStorageKey = (userId: string) => (
  `${POSITION_LIST_FILTERS_STORAGE_PREFIX}:${userId}`
);

export const buildPositionListParams = ({
  title,
  department,
  hiringManagerId,
  priority,
  category,
  status,
  deletedOnly,
}: PositionListFilters) => ({
  ...(title ? { title } : {}),
  ...(department ? { department } : {}),
  ...(hiringManagerId ? { hiring_manager_id: hiringManagerId } : {}),
  ...(priority ? { priority } : {}),
  ...(category ? { category } : {}),
  ...(status ? { status } : {}),
  ...(deletedOnly ? { deleted_only: true } : {}),
});

export const createEmptyPositionListFilters = (): PositionListFilters => ({
  title: '',
  department: undefined,
  hiringManagerId: undefined,
  priority: undefined,
  category: undefined,
  status: undefined,
  deletedOnly: false,
});

export const loadPositionListFilters = (
  storage: PositionListFilterStorage,
  userId: string,
): PositionListFilters => {
  const emptyFilters = createEmptyPositionListFilters();

  try {
    const storedValue = storage.getItem(getPositionListFiltersStorageKey(userId));
    if (!storedValue) return emptyFilters;

    const parsed = JSON.parse(storedValue) as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return emptyFilters;

    return {
      title: typeof parsed.title === 'string' ? parsed.title : '',
      department: typeof parsed.department === 'string' ? parsed.department : undefined,
      hiringManagerId: typeof parsed.hiringManagerId === 'string'
        ? parsed.hiringManagerId
        : undefined,
      priority: typeof parsed.priority === 'number'
        && Number.isInteger(parsed.priority)
        && parsed.priority >= 1
        && parsed.priority <= 5
        ? parsed.priority
        : undefined,
      category: typeof parsed.category === 'string' ? parsed.category : undefined,
      status: typeof parsed.status === 'string' ? parsed.status : undefined,
      // The recycle bin is a page mode, not a remembered filter.
      deletedOnly: false,
    };
  } catch {
    return emptyFilters;
  }
};

export const savePositionListFilters = (
  storage: PositionListFilterStorage,
  userId: string,
  filters: PositionListFilters,
) => {
  try {
    const { deletedOnly: _deletedOnly, ...rememberedFilters } = filters;
    storage.setItem(
      getPositionListFiltersStorageKey(userId),
      JSON.stringify(rememberedFilters),
    );
  } catch {
    // Filtering should keep working when storage is unavailable or full.
  }
};

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
