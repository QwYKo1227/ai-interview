import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { readPageSize, resolveListReturnPath, updateSearchParams, useListPageState } from './useListPageState';

describe('list page URL state', () => {
  it('only accepts supported page sizes', () => {
    expect(readPageSize('20')).toBe(20);
    expect(readPageSize('17')).toBe(10);
    expect(readPageSize('nope')).toBe(10);
  });

  it('updates owned values while preserving unrelated query parameters', () => {
    const result = updateSearchParams(
      new URLSearchParams('review_id=abc&page=3&status=draft'),
      { page: undefined, status: 'sent', page_size: 50 },
    );
    expect(result.toString()).toBe('review_id=abc&status=sent&page_size=50');
  });

  it('reads pagination from the URL and replaces the current history entry', () => {
    window.history.replaceState(null, '', '/offers?status=sent&page=3&page_size=20');
    const historyLength = window.history.length;
    const { result } = renderHook(() => useListPageState());

    expect(result.current.page).toBe(3);
    expect(result.current.pageSize).toBe(20);

    act(() => result.current.setPagination(4, 50));

    expect(window.location.search).toContain('status=sent');
    expect(window.location.search).toContain('page=1');
    expect(window.location.search).toContain('page_size=50');
    expect(window.history.length).toBe(historyLength);
  });

  it('returns to an internal remembered list and rejects unsafe targets', () => {
    expect(resolveListReturnPath('/resumes?status=pending&page=2', '/resumes'))
      .toBe('/resumes?status=pending&page=2');
    expect(resolveListReturnPath('//example.com', '/resumes')).toBe('/resumes');
    expect(resolveListReturnPath(undefined, '/resumes')).toBe('/resumes');
  });
});
