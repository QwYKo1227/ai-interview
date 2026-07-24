interface LatestRequestCallbacks<T> {
  onStart?: () => void;
  onSuccess: (data: T) => void;
  onError: (error: unknown) => void;
  onSettled?: () => void;
}

export const startSerialPolling = (
  task: () => Promise<void>,
  intervalMs: number,
): (() => void) => {
  let stopped = false;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const schedule = () => {
    timeoutId = setTimeout(async () => {
      try {
        await task();
      } finally {
        if (!stopped) schedule();
      }
    }, intervalMs);
  };

  schedule();

  return () => {
    stopped = true;
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  };
};

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
