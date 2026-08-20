import { describe, expect, it } from 'vitest';
import {
  buildCurrentPositionListParams,
  buildPositionListParams,
  createEmptyPositionListFilters,
  loadPositionListFilters,
  reconcileDepartmentSelection,
  reconcileHiringManagerSelection,
  savePositionListFilters,
} from './filters';
import { createLatestRequestCoordinator } from '../../utils/latestRequest';
import { PRIORITY_OPTIONS } from './options';

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
  it('shows priority options as plain numbers', () => {
    expect(PRIORITY_OPTIONS).toEqual([
      { value: 1, label: '1' },
      { value: 2, label: '2' },
      { value: 3, label: '3' },
      { value: 4, label: '4' },
      { value: 5, label: '5' },
    ]);
  });

  it('omits hiring_manager_id when no manager is selected', () => {
    expect(buildPositionListParams({ title: '', status: undefined, hiringManagerId: undefined }))
      .toEqual({});
  });

  it('combines all position filters', () => {
    expect(buildPositionListParams({
      title: 'Backend',
      department: 'Engineering',
      status: 'published',
      hiringManagerId: 'manager-id',
      priority: 5,
      category: 'domestic_rd',
    })).toEqual({
      title: 'Backend',
      department: 'Engineering',
      status: 'published',
      hiring_manager_id: 'manager-id',
      priority: 5,
      category: 'domestic_rd',
    });
  });

  it('requests only deleted positions in recycle-bin mode', () => {
    expect(buildPositionListParams({ title: '', deletedOnly: true })).toEqual({
      deleted_only: true,
    });
  });

  it('creates an empty filter state for reset', () => {
    expect(createEmptyPositionListFilters()).toEqual({
      title: '',
      department: undefined,
      hiringManagerId: undefined,
      priority: undefined,
      category: undefined,
      status: undefined,
      deletedOnly: false,
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

describe('position list filter memory', () => {
  const createStorage = () => {
    const values = new Map<string, string>();
    return {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
  };

  it('restores each user\'s remembered filters without reopening the recycle bin', () => {
    const storage = createStorage();
    savePositionListFilters(storage, 'user-a', {
      title: 'Backend',
      department: 'Engineering',
      hiringManagerId: 'manager-a',
      priority: 5,
      category: 'domestic_rd',
      status: 'published',
      deletedOnly: true,
    });

    expect(loadPositionListFilters(storage, 'user-a')).toEqual({
      title: 'Backend',
      department: 'Engineering',
      hiringManagerId: 'manager-a',
      priority: 5,
      category: 'domestic_rd',
      status: 'published',
      deletedOnly: false,
    });
    expect(loadPositionListFilters(storage, 'user-b')).toEqual(
      createEmptyPositionListFilters(),
    );
  });

  it('falls back safely when remembered data is malformed', () => {
    const storage = createStorage();
    storage.setItem('position-list-filters:user-a', '{not-json');

    expect(loadPositionListFilters(storage, 'user-a')).toEqual(
      createEmptyPositionListFilters(),
    );
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

describe('reconcileDepartmentSelection', () => {
  it('preserves an available department and clears a missing one', () => {
    expect(reconcileDepartmentSelection('Engineering', ['Engineering']))
      .toBe('Engineering');
    expect(reconcileDepartmentSelection('People', ['Engineering']))
      .toBeUndefined();
  });
});
