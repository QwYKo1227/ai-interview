// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RouterProvider } from 'react-router-dom';
import PlatformTenants from './Tenants';
import platformRequest from '../../utils/platformRequest';
import router from '../../router';
import { PlatformAuthProvider } from '../../contexts/PlatformAuthContext';
import { AuthProvider } from '../../contexts/AuthContext';

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

const nativeGetComputedStyle = window.getComputedStyle;
vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element));

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserver);

vi.mock('../../utils/platformRequest', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

const mockGet = vi.mocked(platformRequest.get);
const mockPost = vi.mocked(platformRequest.post);
const mockPatch = vi.mocked(platformRequest.patch);

const tenants = [
  {
    id: 'tenant-careray',
    code: 'careray',
    name: '凯锐招聘',
    primary_domain: 'interview.careray.com',
    status: 'active',
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
  },
  {
    id: 'tenant-photonthix',
    code: 'photonthix',
    name: 'Photonthix',
    primary_domain: 'interview.photonthix.com',
    status: 'inactive',
    created_at: '2026-07-02T00:00:00Z',
    updated_at: '2026-07-02T00:00:00Z',
  },
];

describe('PlatformTenants', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
    localStorage.clear();
    window.history.pushState({}, '', '/');
  });

  it('loads the registry with aggregate counts and Chinese statuses', async () => {
    mockGet.mockResolvedValueOnce(tenants);

    render(<PlatformTenants />);

    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
    expect(screen.getByText('Photonthix')).toBeInTheDocument();
    expect(screen.getByText('careray')).toBeInTheDocument();
    expect(screen.getByText('photonthix')).toBeInTheDocument();
    expect(screen.getByText('interview.careray.com')).toBeInTheDocument();
    expect(screen.getByText('interview.photonthix.com')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '创建时间' })).toBeInTheDocument();
    expect(screen.getByText('2026-07-01T00:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('2026-07-02T00:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('公司总数 2')).toBeInTheDocument();
    expect(screen.getByText('已启用 1')).toBeInTheDocument();
    expect(screen.getByText('已停用 1')).toBeInTheDocument();
    expect(screen.getByText('启用中')).toBeInTheDocument();
    expect(screen.getByText('已停用')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/platform/tenants');
  });

  it('exposes a company detail entry with its tenant id', async () => {
    mockGet.mockResolvedValueOnce(tenants);
    const onOpenTenant = vi.fn();
    const user = userEvent.setup();

    render(<PlatformTenants onOpenTenant={onOpenTenant} />);

    await user.click((await screen.findAllByRole('button', { name: '查看详情' }))[0]);

    expect(onOpenTenant).toHaveBeenCalledWith('tenant-careray');
  });

  it('opens the selected company detail drawer from the registry entry', async () => {
    mockGet
      .mockResolvedValueOnce(tenants)
      .mockResolvedValueOnce({ ...tenants[0], domains: [{ id: 'domain-primary', domain: 'interview.careray.com', is_primary: true, created_at: '2026-07-01T00:00:00Z' }] });
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await user.click((await screen.findAllByRole('button', { name: '查看详情' }))[0]);

    expect(await screen.findByRole('dialog', { name: '公司详情' })).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/platform/tenants/tenant-careray');
  });

  it('does not disable a company until the confirmation is accepted', async () => {
    mockGet.mockResolvedValue(tenants);
    mockPatch.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await screen.findByText('凯锐招聘');

    await user.click(screen.getByRole('button', { name: '停用' }));
    await user.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(mockPatch).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: '停用' }));
    await user.click(screen.getByRole('button', { name: /确\s*定/ }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/platform/tenants/tenant-careray/status', { status: 'inactive' }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it('enables an inactive company directly and refreshes the registry', async () => {
    mockGet.mockResolvedValue(tenants);
    mockPatch.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await screen.findByText('Photonthix');
    await user.click(screen.getByRole('button', { name: '启用' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/platform/tenants/tenant-photonthix/status', { status: 'active' }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it('keeps the original status and reports a Chinese error when a status update fails', async () => {
    mockGet.mockResolvedValue(tenants);
    mockPatch.mockRejectedValueOnce(new Error('network unavailable'));
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await screen.findByText('凯锐招聘');
    await user.click(screen.getByRole('button', { name: '停用' }));
    await user.click(screen.getByRole('button', { name: /确\s*定/ }));

    expect(await screen.findByText('公司状态更新失败，请稍后重试')).toBeInTheDocument();
    expect(screen.getByText('启用中')).toBeInTheDocument();
  });

  it('offers a reload action after the registry request fails', async () => {
    mockGet.mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValueOnce(tenants);
    const user = userEvent.setup();

    render(<PlatformTenants />);

    await user.click(await screen.findByRole('button', { name: /重新加载/ }));

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();
  });

  it('shows the company management heading', () => {
    mockGet.mockResolvedValueOnce([]);

    render(<PlatformTenants />);

    expect(screen.getByRole('heading', { name: '公司管理' })).toBeInTheDocument();
  });

  it('renders the registry through the protected platform route', async () => {
    mockGet.mockResolvedValueOnce([]);
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

  it('uses a Chinese empty state for an empty registry', async () => {
    mockGet.mockResolvedValueOnce([]);

    render(<PlatformTenants />);

    expect(await screen.findByText('暂无已注册公司')).toBeInTheDocument();
  });

  it('onboards a company with normalized registration values', async () => {
    mockGet.mockResolvedValue([]);
    mockPost.mockResolvedValueOnce({});
    const user = userEvent.setup();
    const boundaryPassword = `${'a'.repeat(70)}A1`;

    render(<PlatformTenants />);

    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('主域名'), { target: { value: ' Interview.Photonthix.COM ' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: ' Admin@Photonthix.COM ' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: boundaryPassword } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/tenants', {
      code: 'photonthix',
      name: 'Photonthix',
      primary_domain: 'interview.photonthix.com',
      admin_email: 'admin@photonthix.com',
      admin_password: boundaryPassword,
    }));
  });

  it('accepts a password with fewer than twelve characters when it reaches twelve UTF-8 bytes', async () => {
    mockGet.mockResolvedValue([]);
    mockPost.mockResolvedValueOnce({});
    const user = userEvent.setup();
    const multibytePassword = '密A1abcdefg';

    expect(new TextEncoder().encode(multibytePassword).length).toBe(12);

    render(<PlatformTenants />);

    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'photonthix' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('主域名'), { target: { value: 'interview.photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: multibytePassword } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/tenants', expect.objectContaining({
      admin_password: multibytePassword,
    })));
  });

  it('rejects a password below twelve UTF-8 bytes even when it contains letters and digits', async () => {
    mockGet.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<PlatformTenants />);

    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'photonthix' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('主域名'), { target: { value: 'interview.photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: '测A1' } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));

    expect(mockPost).not.toHaveBeenCalled();
  });

  it('does not submit an administrator password without the required character classes or within 72 UTF-8 bytes', async () => {
    mockGet.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<PlatformTenants />);

    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'photonthix' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('主域名'), { target: { value: 'interview.photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@photonthix.com' } });

    for (const password of ['Password123', 'abcdefghijkl', '123456789012', 'a'.repeat(73), `${'测'.repeat(24)}A1`]) {
      const passwordInput = screen.getByLabelText('管理员初始密码');
      fireEvent.change(passwordInput, { target: { value: password } });
      await user.click(screen.getByRole('button', { name: '创建公司' }));
    }

    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows the prescribed onboarding errors for conflicts and other failures', async () => {
    mockGet.mockResolvedValue([]);
    mockPost
      .mockRejectedValueOnce({ response: { status: 409 } })
      .mockRejectedValueOnce(new Error('network unavailable'));
    const user = userEvent.setup();

    render(<PlatformTenants />);

    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'photonthix' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('主域名'), { target: { value: 'interview.photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: 'Password1234' } });

    await user.click(screen.getByRole('button', { name: '创建公司' }));
    expect(await screen.findByText('公司代码或域名已存在')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '创建公司' }));
    expect(await screen.findByText('公司创建失败，请稍后重试')).toBeInTheDocument();
  });

});
