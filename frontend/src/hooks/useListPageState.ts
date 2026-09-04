import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

type QueryValue = string | number | boolean | null | undefined;
type QueryUpdates = Record<string, QueryValue>;

const positiveInteger = (value: string | null, fallback: number) => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
};

export const readPageSize = (value: string | null, fallback = 10) => {
  const parsed = positiveInteger(value, fallback);
  return PAGE_SIZE_OPTIONS.includes(parsed) ? parsed : fallback;
};

export const updateSearchParams = (
  current: URLSearchParams,
  updates: QueryUpdates,
) => {
  const next = new URLSearchParams(current);
  Object.entries(updates).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '' || value === false) {
      next.delete(key);
    } else {
      next.set(key, String(value));
    }
  });
  return next;
};

const QUERY_CHANGE_EVENT = 'list-query-change';

const useBrowserSearchParams = () => {
  const [searchParams, setSearchParams] = useState(
    () => new URLSearchParams(window.location.search),
  );

  useEffect(() => {
    const sync = () => setSearchParams(new URLSearchParams(window.location.search));
    window.addEventListener('popstate', sync);
    window.addEventListener(QUERY_CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener(QUERY_CHANGE_EVENT, sync);
    };
  }, []);

  return [searchParams, setSearchParams] as const;
};

export const useListPageState = () => {
  const [searchParams, setSearchParams] = useBrowserSearchParams();
  const page = positiveInteger(searchParams.get('page'), 1);
  const pageSize = readPageSize(searchParams.get('page_size'));

  const setQuery = useCallback((updates: QueryUpdates) => {
    const next = updateSearchParams(new URLSearchParams(window.location.search), updates);
    const search = next.toString();
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`,
    );
    setSearchParams(next);
    window.dispatchEvent(new Event(QUERY_CHANGE_EVENT));
  }, [setSearchParams]);

  const setPagination = useCallback((nextPage: number, nextPageSize: number) => {
    setQuery({
      page: nextPageSize === pageSize ? nextPage : 1,
      page_size: nextPageSize === 10 ? undefined : nextPageSize,
    });
  }, [pageSize, setQuery]);

  return { page, pageSize, searchParams, setPagination, setQuery };
};

export const useDebouncedQueryValue = (
  name: string,
  value: string,
  setQuery: (updates: QueryUpdates) => void,
  delay = 300,
) => {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (draft === value) return undefined;
    const timer = window.setTimeout(() => {
      setQuery({ [name]: draft.trim() || undefined, page: undefined });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [delay, draft, name, setQuery, value]);

  return [draft, setDraft] as const;
};

const scrollKey = (pathname: string, search: string) => `list-scroll:${pathname}${search}`;

export const useListScrollRestoration = () => {
  const [searchParams] = useBrowserSearchParams();
  const pathname = window.location.pathname;
  const search = searchParams.toString();
  const normalizedSearch = search ? `?${search}` : '';

  useEffect(() => {
    const key = scrollKey(pathname, normalizedSearch);
    let saved = 0;
    try {
      saved = Number(sessionStorage.getItem(key)) || 0;
    } catch {
      // Session storage can be unavailable in privacy-restricted contexts.
    }
    const restore = () => window.scrollTo(0, saved);
    const frame = window.requestAnimationFrame(restore);
    const retries = saved > 0
      ? [100, 500, 1500].map((delay) => window.setTimeout(restore, delay))
      : [];
    return () => {
      window.cancelAnimationFrame(frame);
      retries.forEach((timer) => window.clearTimeout(timer));
      try {
        sessionStorage.setItem(key, String(window.scrollY));
      } catch {
        // Navigation must continue even if storage is unavailable.
      }
    };
  }, [normalizedSearch, pathname]);
};

export const useNavigateFromList = () => {
  const navigate = useNavigate();
  return useCallback((to: string) => {
    navigate(to, { state: { returnTo: `${window.location.pathname}${window.location.search}` } });
  }, [navigate]);
};

export const resolveListReturnPath = (returnTo: unknown, fallback: string) => (
  typeof returnTo === 'string'
  && returnTo.startsWith('/')
  && !returnTo.startsWith('//')
    ? returnTo
    : fallback
);

export const useReturnToList = (fallback: string) => {
  const navigate = useNavigate();
  return useCallback(() => {
    const routerState = window.history.state?.usr as { returnTo?: unknown } | undefined;
    const returnTo = routerState?.returnTo ?? window.history.state?.returnTo;
    navigate(resolveListReturnPath(returnTo, fallback));
  }, [fallback, navigate]);
};
