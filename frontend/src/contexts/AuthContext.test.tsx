// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './AuthContext';
import request from '../utils/request';

vi.mock('../utils/request', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(request.get);

const tenantResponse = (name: string, code: string) => ({
  id: `user-${code}`,
  email: `${code}@example.com`,
  full_name: '管理员',
  role: 'admin' as const,
  is_active: true,
  tenant: {
    id: `tenant-${code}`,
    code,
    name,
    logo_url: null,
    primary_domain: `${code}.example.com`,
  },
});

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
};

const AuthProbe = () => {
  const { companyName, isAuthenticated, login, logout } = useAuth();
  return <>
    <span data-testid="auth-state">{isAuthenticated ? companyName || '缺少公司' : '已退出'}</span>
    <button onClick={logout}>退出</button>
    <button onClick={() => void login('new-token')}>登录新公司</button>
  </>;
};

describe('AuthContext', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('keeps the current company from /auth/me and clears it on logout', async () => {
    localStorage.setItem('token', 'valid-token');
    mockGet.mockResolvedValueOnce(tenantResponse('凯锐招聘', 'careray'));
    const user = userEvent.setup();

    render(<AuthProvider><AuthProbe /></AuthProvider>);

    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '退出' }));

    await waitFor(() => expect(screen.getByText('已退出')).toBeInTheDocument());
    expect(localStorage.getItem('token')).toBeNull();
  });

  it('ignores a pending /auth/me response after logout', async () => {
    localStorage.setItem('token', 'old-token');
    const oldRequest = deferred<ReturnType<typeof tenantResponse>>();
    mockGet.mockReturnValueOnce(oldRequest.promise);
    const user = userEvent.setup();

    render(<AuthProvider><AuthProbe /></AuthProvider>);
    await user.click(screen.getByRole('button', { name: '退出' }));

    await act(async () => { oldRequest.resolve(tenantResponse('旧公司', 'old')); });

    expect(screen.getByTestId('auth-state')).toHaveTextContent('已退出');
    expect(localStorage.getItem('token')).toBeNull();
  });

  it('does not let an old company response overwrite a later login', async () => {
    localStorage.setItem('token', 'old-token');
    const oldRequest = deferred<ReturnType<typeof tenantResponse>>();
    const newRequest = deferred<ReturnType<typeof tenantResponse>>();
    mockGet.mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise);
    const user = userEvent.setup();

    render(<AuthProvider><AuthProbe /></AuthProvider>);
    await user.click(screen.getByRole('button', { name: '登录新公司' }));
    await act(async () => { newRequest.resolve(tenantResponse('新公司', 'new')); });
    expect(await screen.findByText('新公司')).toBeInTheDocument();

    await act(async () => { oldRequest.resolve(tenantResponse('旧公司', 'old')); });
    expect(screen.getByTestId('auth-state')).toHaveTextContent('新公司');
  });

  it('does not write auth state after the provider unmounts', async () => {
    localStorage.setItem('token', 'valid-token');
    const pendingRequest = deferred<ReturnType<typeof tenantResponse>>();
    mockGet.mockReturnValueOnce(pendingRequest.promise);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const { unmount } = render(<AuthProvider><AuthProbe /></AuthProvider>);
    const signal = mockGet.mock.calls[0][1]?.signal;
    expect(signal).toBeInstanceOf(AbortSignal);
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { pendingRequest.resolve(tenantResponse('已卸载公司', 'unmounted')); });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
