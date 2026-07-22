// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import AppLayout from './index';

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

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { email: 'admin@example.com', full_name: '管理员', role: 'admin' },
    companyName: '凯锐招聘',
    logout: vi.fn(),
  }),
}));

describe('AppLayout', () => {
  it('shows the current company identity without a company switcher', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route path="dashboard" element={<div>仪表盘内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('凯锐招聘')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '公司' })).not.toBeInTheDocument();
  });
});
