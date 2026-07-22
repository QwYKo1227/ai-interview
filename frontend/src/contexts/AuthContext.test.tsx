// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './AuthContext';
import request from '../utils/request';

vi.mock('../utils/request', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(request.get);

const AuthProbe = () => {
  const { companyName, logout } = useAuth();
  return <>
    <span>{companyName || '未选择公司'}</span>
    <button onClick={logout}>退出</button>
  </>;
};

describe('AuthContext', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('keeps the current company from /auth/me and clears it on logout', async () => {
    localStorage.setItem('token', 'valid-token');
    mockGet.mockResolvedValueOnce({
      id: 'user-1',
      email: 'admin@example.com',
      full_name: '管理员',
      role: 'admin',
      is_active: true,
      tenant: {
        id: 'tenant-1',
        code: 'careray',
        name: '凯锐招聘',
        logo_url: null,
        primary_domain: 'login.careray.example',
      },
    });
    const user = userEvent.setup();

    render(<AuthProvider><AuthProbe /></AuthProvider>);

    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '退出' }));

    await waitFor(() => expect(screen.getByText('未选择公司')).toBeInTheDocument());
    expect(localStorage.getItem('token')).toBeNull();
  });
});
