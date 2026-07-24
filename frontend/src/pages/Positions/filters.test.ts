import { describe, expect, it } from 'vitest';
import {
  buildCurrentPositionListParams,
  buildPositionListParams,
  createLatestRequestCoordinator,
  reconcileHiringManagerSelection,
} from './filters';

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
};

describe('buildPositionListParams', () => {
  it('omits hiring_manager_id when no manager is selected', () => {
    expect(buildPositionListParams({ title: '', status: undefined, hiringManagerId: undefined }))
      .toEqual({ title: '', status: undefined });
  });

  it('combines hiring manager with title and status', () => {
    expect(buildPositionListParams({
      title: 'Backend',
      status: 'published',
      hiringManagerId: 'manager-id',
    })).toEqual({
      title: 'Backend',
      status: 'published',
      hiring_manager_id: 'manager-id',
    });
  });
});

describe('buildCurrentPositionListParams', () => {
  it('lets a stable refresh read the latest filters at invocation time', () => {
    const filtersRef = {
      current: {
        title: 'Filter A',
        status: 'open',
        hiringManagerId: 'manager-a',
      },
    };
    const stableRefresh = () => buildCurrentPositionListParams(filtersRef);

    filtersRef.current = {
      title: 'Filter B',
      status: 'published',
      hiringManagerId: 'manager-b',
    };

    expect(stableRefresh()).toEqual({
      title: 'Filter B',
      status: 'published',
      hiring_manager_id: 'manager-b',
    });
  });
});

describe('createLatestRequestCoordinator', () => {
  it('only lets the latest request update data, loading, and errors when responses arrive out of order', async () => {
    const first = deferred<string[]>();
    const second = deferred<string[]>();
    const third = deferred<string[]>();
    const fourth = deferred<string[]>();
    const coordinator = createLatestRequestCoordinator();
    const dataUpdates: string[][] = [];
    const loadingUpdates: boolean[] = [];
    const errors: string[] = [];
    const callbacks = {
      onStart: () => loadingUpdates.push(true),
      onSuccess: (data: string[]) => dataUpdates.push(data),
      onError: () => errors.push('failed'),
      onSettled: () => loadingUpdates.push(false),
    };

    const firstRun = coordinator.run(() => first.promise, callbacks);
    const secondRun = coordinator.run(() => second.promise, callbacks);

    second.resolve(['new result']);
    await secondRun;
    first.resolve(['stale result']);
    await firstRun;

    const thirdRun = coordinator.run(() => third.promise, callbacks);
    const fourthRun = coordinator.run(() => fourth.promise, callbacks);

    fourth.resolve(['newest result']);
    await fourthRun;
    third.reject(new Error('stale failure'));
    await thirdRun;

    expect(dataUpdates).toEqual([['new result'], ['newest result']]);
    expect(loadingUpdates).toEqual([true, true, false, true, true, false]);
    expect(errors).toEqual([]);
  });
});

describe('reconcileHiringManagerSelection', () => {
  const managers = [
    { id: 'manager-a' },
    { id: 'manager-b' },
  ];

  it('preserves the selected manager while it remains available', () => {
    expect(reconcileHiringManagerSelection('manager-b', managers)).toBe('manager-b');
  });

  it('clears the selected manager after it disappears', () => {
    expect(reconcileHiringManagerSelection('manager-c', managers)).toBeUndefined();
  });
});
