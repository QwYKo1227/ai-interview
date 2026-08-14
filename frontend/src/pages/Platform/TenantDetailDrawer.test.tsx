// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TenantDetailDrawer from './TenantDetailDrawer';
import platformRequest from '../../utils/platformRequest';

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

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserver);

vi.mock('../../utils/platformRequest', () => ({
  default: { get: vi.fn(), patch: vi.fn() },
}));

const mockGet = vi.mocked(platformRequest.get);
const mockPatch = vi.mocked(platformRequest.patch);

const tenant = {
  id: 'tenant-careray',
  code: 'careray',
  name: '凯锐招聘',
  status: 'active' as const,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
  admins: [
    { id: 'admin-1', email: 'admin@careray.com', full_name: '企业管理员', is_active: true },
  ],
};

describe('TenantDetailDrawer', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockGet.mockReset();
    mockPatch.mockReset();
  });

  it('shows company and administrator details without domain management', async () => {
    mockGet.mockResolvedValueOnce(tenant);

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);

    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
    expect(screen.getByText('admin@careray.com')).toBeInTheDocument();
    expect(screen.queryByText('域名登记')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '新增域名' })).not.toBeInTheDocument();
  });

  it('resets a tenant administrator password', async () => {
    mockGet.mockResolvedValueOnce(tenant);
    mockPatch.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);

    await user.click(await screen.findByRole('button', { name: '重置密码' }));
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'Replacement123' } });
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'Replacement123' } });
    await user.click(screen.getByRole('button', { name: '确认重置' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/platform/tenants/tenant-careray/admins/admin-1/password',
      { new_password: 'Replacement123' },
    ));
    expect(await screen.findByText('已重置 admin@careray.com 的密码')).toBeInTheDocument();
  });

  it('does not submit mismatched administrator passwords', async () => {
    mockGet.mockResolvedValueOnce(tenant);
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);

    await user.click(await screen.findByRole('button', { name: '重置密码' }));
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'Replacement123' } });
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'Replacement124' } });
    await user.click(screen.getByRole('button', { name: '确认重置' }));

    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument();
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('offers a retry when company details fail to load', async () => {
    mockGet.mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValueOnce(tenant);
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);

    await user.click(await screen.findByRole('button', { name: /重新加载/ }));

    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});
