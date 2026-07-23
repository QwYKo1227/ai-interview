// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PlatformLogin from './Login';
import platformRequest from '../../utils/platformRequest';

const mockNavigate = vi.fn();
const mockPlatformLogin = vi.fn();
const mockPlatformAuth = {
  isAuthenticated: false,
  login: mockPlatformLogin,
};

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

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock('../../contexts/PlatformAuthContext', () => ({
  usePlatformAuth: () => mockPlatformAuth,
}));

vi.mock('../../utils/platformRequest', () => ({
  default: { post: vi.fn() },
}));

const mockPost = vi.mocked(platformRequest.post);

describe('PlatformLogin', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPlatformAuth.isAuthenticated = false;
  });

  it('submits platform credentials and enters the tenant registry', async () => {
    mockPost.mockResolvedValueOnce({ access_token: 'platform-token' });
    const user = userEvent.setup();

    render(<PlatformLogin />);

    await user.type(screen.getByLabelText('邮箱'), 'platform@example.com');
    await user.type(screen.getByLabelText('密码'), 'Password1234');
    await user.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/auth/login', {
      email: 'platform@example.com',
      password: 'Password1234',
    }));
    expect(mockPlatformLogin).toHaveBeenCalledWith('platform-token');
    expect(mockNavigate).toHaveBeenCalledWith('/platform/tenants', { replace: true });
  });

  it('shows the unified Chinese error when platform login fails', async () => {
    mockPost.mockRejectedValueOnce(new Error('invalid credentials'));
    const user = userEvent.setup();

    render(<PlatformLogin />);

    await user.type(screen.getByLabelText('邮箱'), 'platform@example.com');
    await user.type(screen.getByLabelText('密码'), 'Password1234');
    await user.click(screen.getByRole('button', { name: /登\s*录/ }));

    expect(await screen.findByText('登录失败，请检查邮箱和密码')).toBeInTheDocument();
  });

  it('redirects an authenticated administrator to the tenant registry', async () => {
    mockPlatformAuth.isAuthenticated = true;

    render(<PlatformLogin />);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/platform/tenants', { replace: true }));
  });
});
