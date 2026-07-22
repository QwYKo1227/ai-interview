// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { AxiosHeaders } from 'axios';
import { afterEach, describe, expect, it, vi } from 'vitest';
import request, { getBearerToken } from './request';

const deferred = <T,>() => {
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((_, rejectPromise) => { reject = rejectPromise; });
  return { promise, reject };
};

describe('request authentication failures', () => {
  const originalAdapter = request.defaults.adapter;

  afterEach(() => {
    request.defaults.adapter = originalAdapter;
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('does not clear a newer token when an old authenticated request returns 401', async () => {
    localStorage.setItem('token', 'old-token');
    const failure = deferred<never>();
    let requestConfig: any;
    request.defaults.adapter = (config: any) => {
      requestConfig = config;
      return failure.promise;
    };

    const pending = request.get('/auth/me');
    await vi.waitFor(() => expect(requestConfig.headers.get('Authorization')).toBe('Bearer old-token'));
    localStorage.setItem('token', 'new-token');
    failure.reject({ config: requestConfig, response: { status: 401, data: {} } });

    await expect(pending).rejects.toMatchObject({ response: { status: 401 } });
    expect(localStorage.getItem('token')).toBe('new-token');
    expect(window.location.pathname).not.toBe('/login');
  });

  it('does not clear the current token for a 401 from an anonymous endpoint', async () => {
    localStorage.setItem('token', 'current-token');
    let requestConfig: any;
    request.defaults.adapter = (config: any) => {
      requestConfig = config;
      return Promise.reject({ config, response: { status: 401, data: {} } });
    };

    await expect(request.get('/auth/tenants')).rejects.toMatchObject({ response: { status: 401 } });
    expect(requestConfig.headers.get('Authorization')).toBeUndefined();
    expect(localStorage.getItem('token')).toBe('current-token');
  });

  it.each([
    [{ Authorization: 'Bearer plain-token' }, 'plain-token'],
    [{ authorization: 'bearer lowercase-token' }, 'lowercase-token'],
    [new AxiosHeaders({ authorization: 'Bearer axios-token' }), 'axios-token'],
    [{ AUTHORIZATION: 'Basic ignored' }, null],
  ])('parses request bearer tokens from %o', (headers, expected) => {
    expect(getBearerToken(headers)).toBe(expected);
  });
});
