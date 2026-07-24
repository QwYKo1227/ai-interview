export interface PositionListFilters {
  title: string;
  status?: string;
  hiringManagerId?: string;
}

export const buildPositionListParams = ({
  title,
  status,
  hiringManagerId,
}: PositionListFilters) => ({
  title,
  status,
  ...(hiringManagerId ? { hiring_manager_id: hiringManagerId } : {}),
});

export const buildCurrentPositionListParams = (
  filtersRef: { readonly current: PositionListFilters },
) => buildPositionListParams(filtersRef.current);

interface LatestRequestCallbacks<T> {
  onStart?: () => void;
  onSuccess: (data: T) => void;
  onError: (error: unknown) => void;
  onSettled?: () => void;
}

export const createLatestRequestCoordinator = () => {
  let latestRequestId = 0;

  return {
    async run<T>(
      request: () => Promise<T>,
      callbacks: LatestRequestCallbacks<T>,
    ): Promise<void> {
      const requestId = ++latestRequestId;
      callbacks.onStart?.();

      try {
        const result = await request();
        if (requestId === latestRequestId) {
          callbacks.onSuccess(result);
        }
      } catch (error) {
        if (requestId === latestRequestId) {
          callbacks.onError(error);
        }
      } finally {
        if (requestId === latestRequestId) {
          callbacks.onSettled?.();
        }
      }
    },
  };
};

export const reconcileHiringManagerSelection = (
  selectedId: string | undefined,
  options: ReadonlyArray<{ id: string }>,
): string | undefined => (
  selectedId && options.some(({ id }) => id === selectedId)
    ? selectedId
    : undefined
);
