// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
};

const tenants = [
  {
    id: 'tenant-careray',
    code: 'careray',
    name: '凯锐招聘',
    status: 'active',
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
  },
  {
    id: 'tenant-photonthix',
    code: 'photonthix',
    name: 'Photonthix',
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
    expect(screen.queryByRole('columnheader', { name: '主域名' })).not.toBeInTheDocument();
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
      .mockResolvedValueOnce({ ...tenants[0], admins: [] });
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

  it('keeps the newest registry data when an older load resolves last', async () => {
    const olderLoad = deferred<typeof tenants>();
    const newerLoad = deferred<typeof tenants>();
    const staleTenant = { ...tenants[0], id: 'tenant-stale', name: '旧公司' };
    const freshTenant = { ...tenants[1], id: 'tenant-fresh', name: '新公司' };
    mockGet
      .mockReturnValueOnce(olderLoad.promise)
      .mockReturnValueOnce(newerLoad.promise);
    mockPost.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'fresh' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: '新公司' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@fresh.example.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: 'Password1234' } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));

    await act(async () => newerLoad.resolve([freshTenant]));
    expect(await screen.findByText('新公司')).toBeInTheDocument();
    await act(async () => olderLoad.resolve([staleTenant]));

    await waitFor(() => {
      expect(screen.getByText('新公司')).toBeInTheDocument();
      expect(screen.queryByText('旧公司')).not.toBeInTheDocument();
    });
  });

  it('keeps the newest successful registry when an older load rejects last', async () => {
    const olderLoad = deferred<typeof tenants>();
    const newerLoad = deferred<typeof tenants>();
    const freshTenant = { ...tenants[1], id: 'tenant-fresh', name: '新公司' };
    mockGet
      .mockReturnValueOnce(olderLoad.promise)
      .mockReturnValueOnce(newerLoad.promise);
    mockPost.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'fresh' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: '新公司' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@fresh.example.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: 'Password1234' } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));

    await act(async () => newerLoad.resolve([freshTenant]));
    expect(await screen.findByText('新公司')).toBeInTheDocument();
    await act(async () => olderLoad.reject(new Error('旧请求失败')));

    await waitFor(() => {
      expect(screen.getByText('新公司')).toBeInTheDocument();
      expect(screen.queryByText('公司注册表暂时无法加载')).not.toBeInTheDocument();
    });
  });

  it('ignores a registry load that settles after unmount', async () => {
    const pendingLoad = deferred<typeof tenants>();
    mockGet.mockReturnValueOnce(pendingLoad.promise);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const view = render(<PlatformTenants />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    view.unmount();
    await act(async () => pendingLoad.resolve(tenants));

    expect(consoleError).not.toHaveBeenCalled();
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
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: ' Admin@Photonthix.COM ' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: boundaryPassword } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/tenants', {
      code: 'photonthix',
      name: 'Photonthix',
      admin_email: 'admin@photonthix.com',
      admin_password: boundaryPassword,
    }));
  });

  it('shows success feedback then closes, resets, and refreshes after onboarding', async () => {
    mockGet.mockResolvedValue([]);
    mockPost.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<PlatformTenants />);
    await user.click(screen.getByRole('button', { name: '新建公司' }));
    fireEvent.change(screen.getByLabelText('公司代码'), { target: { value: 'photonthix' } });
    fireEvent.change(screen.getByLabelText('公司名称'), { target: { value: 'Photonthix' } });
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: 'Password1234' } });
    await user.click(screen.getByRole('button', { name: '创建公司' }));

    expect(await screen.findByText('公司创建成功')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('dialog', { name: '新建公司' })).toHaveClass('ant-zoom-leave'));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole('button', { name: '新建公司' }));
    expect(screen.getByLabelText('公司代码')).toHaveValue('');
    expect(screen.getByLabelText('公司名称')).toHaveValue('');
    expect(screen.getByLabelText('管理员邮箱')).toHaveValue('');
    expect(screen.getByLabelText('管理员初始密码')).toHaveValue('');
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
    fireEvent.change(screen.getByLabelText('管理员邮箱'), { target: { value: 'admin@photonthix.com' } });
    fireEvent.change(screen.getByLabelText('管理员初始密码'), { target: { value: 'Password1234' } });

    await user.click(screen.getByRole('button', { name: '创建公司' }));
    expect(await screen.findByText('公司代码已存在')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '创建公司' }));
    expect(await screen.findByText('公司创建失败，请稍后重试')).toBeInTheDocument();
  });

});
