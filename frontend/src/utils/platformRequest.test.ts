// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import platformRequest from './platformRequest';

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

  it('clears only the matching platform token after a 401', async () => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'old-platform-token');
    platformRequest.defaults.adapter = (config: any) => Promise.reject({
      config,
      response: { status: 401, data: {} },
    });
    await expect(platformRequest.get('/platform/tenants')).rejects.toBeTruthy();
    expect(localStorage.getItem('platform_token')).toBeNull();
    expect(localStorage.getItem('token')).toBe('tenant-token');
  });
});
