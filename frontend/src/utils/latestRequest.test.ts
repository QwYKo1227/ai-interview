import { afterEach, describe, expect, it, vi } from 'vitest';
import { startSerialPolling } from './latestRequest';

describe('serial polling', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not start another poll while the current request is pending', async () => {
    vi.useFakeTimers();
    let resolveFirstRequest: (() => void) | undefined;
    const task = vi.fn(() => new Promise<void>((resolve) => {
      resolveFirstRequest = resolve;
    }));
    const stop = startSerialPolling(task, 3000);

    await vi.advanceTimersByTimeAsync(3000);
    expect(task).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(9000);
    expect(task).toHaveBeenCalledTimes(1);

    resolveFirstRequest?.();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(2999);
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(task).toHaveBeenCalledTimes(2);

    stop();
  });
});
