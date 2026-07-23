// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PlatformProtectedRoute from './PlatformProtectedRoute';
import PlatformLayout from './PlatformLayout';

const mockLogout = vi.fn();
const mockPlatformAuth = { isAuthenticated: false, logout: mockLogout };

vi.mock('../../contexts/PlatformAuthContext', () => ({
  usePlatformAuth: () => mockPlatformAuth,
}));

const renderProtectedRoute = () => render(
  <MemoryRouter initialEntries={['/platform/tenants']}>
    <Routes>
      <Route path="/platform/login" element={<p>平台登录页</p>} />
      <Route
        path="/platform/tenants"
        element={(
          <PlatformProtectedRoute>
            <p>受保护的公司注册表</p>
          </PlatformProtectedRoute>
        )}
      />
    </Routes>
  </MemoryRouter>,
);

describe('PlatformProtectedRoute', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPlatformAuth.isAuthenticated = false;
  });

  it('redirects an unauthenticated visitor to platform login', () => {
    renderProtectedRoute();

    expect(screen.getByText('平台登录页')).toBeInTheDocument();
  });

  it('renders children for an authenticated administrator', () => {
    mockPlatformAuth.isAuthenticated = true;

    renderProtectedRoute();

    expect(screen.getByText('受保护的公司注册表')).toBeInTheDocument();
  });
});

describe('PlatformLayout', () => {
  it('logs out the platform session and returns to platform login', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/platform/tenants']}>
        <Routes>
          <Route path="/platform/login" element={<p>平台登录页</p>} />
          <Route path="/platform" element={<PlatformLayout />}>
            <Route path="tenants" element={<p>公司管理</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('button', { name: /退出登录/ }));

    expect(mockLogout).toHaveBeenCalledOnce();
    expect(screen.getByText('平台登录页')).toBeInTheDocument();
  });
});
