// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { RouterProvider } from 'react-router-dom';
import PlatformTenants from './Tenants';
import router from '../../router';
import { PlatformAuthProvider } from '../../contexts/PlatformAuthContext';
import { AuthProvider } from '../../contexts/AuthContext';

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({
    matches: false,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
  }),
});

describe('PlatformTenants', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    window.history.pushState({}, '', '/');
  });

  it('shows the company management heading', () => {
    render(<PlatformTenants />);

    expect(screen.getByRole('heading', { name: '公司管理' })).toBeInTheDocument();
  });

  it('renders company management through the protected platform tenant route', async () => {
    localStorage.setItem('platform_token', 'platform-token');
    await router.navigate('/platform/tenants');

    render(
      <AuthProvider>
        <PlatformAuthProvider>
          <RouterProvider router={router} />
        </PlatformAuthProvider>
      </AuthProvider>,
    );

    expect(await screen.findByRole('heading', { name: '公司管理' })).toBeInTheDocument();
  });
});
