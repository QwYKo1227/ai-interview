// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import platformRequest from './platformRequest';

const deferred = <T,>() => {
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((_, rejectPromise) => { reject = rejectPromise; });
  return { promise, reject };
};

describe('platformRequest', () => {
  const originalAdapter = platformRequest.defaults.adapter;

  afterEach(() => {
    platformRequest.defaults.adapter = originalAdapter;
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('sends only the platform token to protected platform endpoints', async () => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'platform-token');
    let authorization: string | undefined;
    platformRequest.defaults.adapter = async (config: any) => {
      authorization = config.headers.get('Authorization');
      return { data: [], status: 200, statusText: 'OK', headers: {}, config };
    };
    await platformRequest.get('/platform/tenants');
    expect(authorization).toBe('Bearer platform-token');
  });

  it('does not send a token to platform login', async () => {
    localStorage.setItem('platform_token', 'stale-token');
    let authorization: string | undefined;
    platformRequest.defaults.adapter = async (config: any) => {
      authorization = config.headers.get('Authorization');
      return { data: { access_token: 'new-token' }, status: 200, statusText: 'OK', headers: {}, config };
    };
    await platformRequest.post('/platform/auth/login', { email: 'admin@example.com', password: 'Password1234' });
    expect(authorization).toBeUndefined();
  });

  it.each([401, 403])('clears only the matching platform token after a %s', async (status) => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'old-platform-token');
    platformRequest.defaults.adapter = (config: any) => Promise.reject({
      config,
      response: { status, data: {} },
    });
    await expect(platformRequest.get('/platform/tenants')).rejects.toBeTruthy();
    expect(localStorage.getItem('platform_token')).toBeNull();
    expect(localStorage.getItem('token')).toBe('tenant-token');
  });

  it('does not clear a newer platform token when an old request returns 403', async () => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'old-platform-token');
    const failure = deferred<never>();
    let requestConfig: any;
    platformRequest.defaults.adapter = (config: any) => {
      requestConfig = config;
      return failure.promise;
    };

    const pending = platformRequest.get('/platform/tenants');
    await vi.waitFor(() => expect(requestConfig.headers.get('Authorization')).toBe('Bearer old-platform-token'));
    localStorage.setItem('platform_token', 'new-platform-token');
    failure.reject({ config: requestConfig, response: { status: 403, data: {} } });

    await expect(pending).rejects.toMatchObject({ response: { status: 403 } });
    expect(localStorage.getItem('platform_token')).toBe('new-platform-token');
    expect(localStorage.getItem('token')).toBe('tenant-token');
  });

  it.each([401, 403])('does not clear the current platform token for a %s from platform login', async (status) => {
    localStorage.setItem('platform_token', 'current-platform-token');
    let requestConfig: any;
    platformRequest.defaults.adapter = (config: any) => {
      requestConfig = config;
      return Promise.reject({ config, response: { status, data: {} } });
    };

    await expect(platformRequest.post('/platform/auth/login', {
      email: 'admin@example.com',
      password: 'Password1234',
    })).rejects.toMatchObject({ response: { status } });
    expect(requestConfig.headers.get('Authorization')).toBeUndefined();
    expect(localStorage.getItem('platform_token')).toBe('current-platform-token');
  });
});
