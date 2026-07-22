// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Login from './index';
import request from '../../utils/request';

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

const mockLogin = vi.fn().mockResolvedValue(true);

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ login: mockLogin, isAuthenticated: false, loading: false }),
}));

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

const mockGet = vi.mocked(request.get);
const mockPost = vi.mocked(request.post);

const renderLogin = () => render(<MemoryRouter><Login /></MemoryRouter>);

describe('Login', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('submits company code, email, and password', async () => {
    mockGet.mockResolvedValueOnce([
      { id: '1', code: 'careray', name: '凯锐招聘' },
    ]);
    mockPost.mockResolvedValueOnce({ access_token: 'token' });
    const user = userEvent.setup();

    renderLogin();

    await user.selectOptions(await screen.findByLabelText('公司'), 'careray');
    await user.type(screen.getByLabelText('邮箱'), 'admin@example.com');
    await user.type(screen.getByLabelText('密码'), 'Password123');
    await user.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/auth/login', {
      tenant_code: 'careray',
      email: 'admin@example.com',
      password: 'Password123',
    }));
  });

  it('shows a retry action when the company list cannot be loaded', async () => {
    mockGet.mockRejectedValueOnce(new Error('network unavailable'));
    mockGet.mockResolvedValueOnce([
      { id: '1', code: 'careray', name: '凯锐招聘' },
    ]);
    const user = userEvent.setup();

    renderLogin();

    await user.click(await screen.findByRole('button', { name: '重新加载公司列表' }));

    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});
