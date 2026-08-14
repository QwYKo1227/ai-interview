import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import RoleProtectedRoute from './RoleProtectedRoute';

const authState = vi.hoisted(() => ({ role: 'interviewer' }));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1', role: authState.role } }),
}));

const renderRoute = (redirectTo?: string) => render(
  <MemoryRouter initialEntries={['/offers']}>
    <Routes>
      <Route path="/dashboard" element={<div>dashboard</div>} />
      <Route path="/resumes/my-reviews" element={<div>my reviews</div>} />
      <Route
        path="/offers"
        element={(
          <RoleProtectedRoute roles={['admin', 'hr']} redirectTo={redirectTo}>
            <div>offers</div>
          </RoleProtectedRoute>
        )}
      />
    </Routes>
  </MemoryRouter>,
);

afterEach(cleanup);

describe('RoleProtectedRoute', () => {
  it('redirects interviewers away from offer management', () => {
    authState.role = 'interviewer';
    renderRoute();

    expect(screen.getByText('dashboard')).toBeInTheDocument();
    expect(screen.queryByText('offers')).not.toBeInTheDocument();
  });

  it.each(['admin', 'hr'])('allows %s users', (role) => {
    authState.role = role;
    renderRoute();

    expect(screen.getByText('offers')).toBeInTheDocument();
  });

  it('supports a role-specific redirect target', () => {
    authState.role = 'interviewer';
    renderRoute('/resumes/my-reviews');

    expect(screen.getByText('my reviews')).toBeInTheDocument();
  });
});
