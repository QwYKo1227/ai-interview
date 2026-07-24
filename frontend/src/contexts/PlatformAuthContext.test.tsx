// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { PlatformAuthProvider, usePlatformAuth } from './PlatformAuthContext';

const PlatformAuthProbe = () => {
  const { isAuthenticated, login, logout } = usePlatformAuth();
  return <>
    <span data-testid="platform-auth-state">{isAuthenticated ? 'authenticated' : 'anonymous'}</span>
    <button onClick={() => login('platform-token')}>login</button>
    <button onClick={logout}>logout</button>
  </>;
};

const MissingProviderProbe = () => {
  usePlatformAuth();
  return null;
};

describe('PlatformAuthContext', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('uses only the platform token to determine its initial authentication state', () => {
    localStorage.setItem('token', 'tenant-token');

    render(<PlatformAuthProvider><PlatformAuthProbe /></PlatformAuthProvider>);

    expect(screen.getByTestId('platform-auth-state')).toHaveTextContent('anonymous');
  });

  it('reports a clear Chinese error when used outside the provider', () => {
    expect(() => render(<MissingProviderProbe />)).toThrow(
      'usePlatformAuth 必须在 PlatformAuthProvider 内使用',
    );
  });

  it('starts authenticated when a platform token exists', () => {
    localStorage.setItem('platform_token', 'platform-token');

    render(<PlatformAuthProvider><PlatformAuthProbe /></PlatformAuthProvider>);

    expect(screen.getByTestId('platform-auth-state')).toHaveTextContent('authenticated');
  });

  it('writes only the platform token on login', () => {
    localStorage.setItem('token', 'tenant-token');
    render(<PlatformAuthProvider><PlatformAuthProbe /></PlatformAuthProvider>);

    fireEvent.click(screen.getByRole('button', { name: 'login' }));

    expect(localStorage.getItem('platform_token')).toBe('platform-token');
    expect(localStorage.getItem('token')).toBe('tenant-token');
    expect(screen.getByTestId('platform-auth-state')).toHaveTextContent('authenticated');
  });

  it('removes only the platform token on logout', () => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'platform-token');
    render(<PlatformAuthProvider><PlatformAuthProbe /></PlatformAuthProvider>);

    fireEvent.click(screen.getByRole('button', { name: 'logout' }));

    expect(localStorage.getItem('platform_token')).toBeNull();
    expect(localStorage.getItem('token')).toBe('tenant-token');
    expect(screen.getByTestId('platform-auth-state')).toHaveTextContent('anonymous');
  });
});
