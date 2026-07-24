// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

const nativeGetComputedStyle = window.getComputedStyle;
vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element));

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserver);

vi.mock('../../utils/platformRequest', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const mockGet = vi.mocked(platformRequest.get);
const mockPost = vi.mocked(platformRequest.post);
const mockPatch = vi.mocked(platformRequest.patch);
const mockDelete = vi.mocked(platformRequest.delete);

const tenant = {
  id: 'tenant-careray',
  code: 'careray',
  name: '凯锐招聘',
  primary_domain: 'interview.careray.com',
  status: 'active' as const,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
  domains: [
    { id: 'domain-primary', domain: 'interview.careray.com', is_primary: true, created_at: '2026-07-01T00:00:00Z' },
    { id: 'domain-secondary', domain: 'careers.careray.com', is_primary: false, created_at: '2026-07-02T00:00:00Z' },
  ],
};

const domainActions = (domain: string) => {
  const item = screen.getByText(domain).closest('.ant-list-item');
  if (!item) throw new Error(`找不到域名列表项：${domain}`);
  return within(item as HTMLElement);
};

describe('TenantDetailDrawer', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
    mockDelete.mockReset();
  });

  it('shows every domain while protecting the primary domain from deletion', async () => {
    mockGet.mockResolvedValueOnce(tenant);

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);

    expect(await screen.findByText('interview.careray.com')).toBeInTheDocument();
    expect(screen.getByText('careers.careray.com')).toBeInTheDocument();
    expect(screen.getByText('主域名')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '删除' })).toHaveLength(1);
    expect(screen.getByText('DNS、Hosts 和 Caddy 配置需要另行维护。')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/platform/tenants/tenant-careray');
  });

  it('adds a normalized domain then refreshes the detail and parent list', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPost.mockResolvedValueOnce({});
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('interview.careray.com');

    await user.click(screen.getByRole('button', { name: '新增域名' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: ' Careers.Careray.COM ' } });
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/tenants/tenant-careray/domains', {
      domain: 'careers.careray.com',
      is_primary: false,
    }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('adds a new domain as primary when selected', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPost.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('interview.careray.com');

    await user.click(screen.getByRole('button', { name: '新增域名' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: ' Primary.Careray.COM ' } });
    await user.click(screen.getByRole('checkbox', { name: '设为主域名' }));
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/platform/tenants/tenant-careray/domains', {
      domain: 'primary.careray.com',
      is_primary: true,
    }));
  });

  it('edits the primary domain without offering delete or set-primary actions', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPatch.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('interview.careray.com');
    const primaryActions = domainActions('interview.careray.com');

    expect(primaryActions.queryByRole('button', { name: '删除' })).not.toBeInTheDocument();
    expect(primaryActions.queryByRole('button', { name: '设为主域名' })).not.toBeInTheDocument();
    await user.click(primaryActions.getByRole('button', { name: '编辑' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: ' Primary.Careray.COM ' } });
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/platform/tenants/tenant-careray/domains/domain-primary',
      { domain: 'primary.careray.com' },
    ));
  });

  it('edits a secondary domain with the requested endpoint and payload', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPatch.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');

    await user.click(domainActions('careers.careray.com').getByRole('button', { name: '编辑' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: ' Jobs.Careray.COM ' } });
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/platform/tenants/tenant-careray/domains/domain-secondary', {
      domain: 'jobs.careray.com',
    }));
  });

  it('sets a secondary domain as primary then refreshes detail and parent list', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPatch.mockResolvedValueOnce({});
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');

    await user.click(screen.getByRole('button', { name: '设为主域名' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/platform/tenants/tenant-careray/domains/domain-secondary', {
      is_primary: true,
    }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('does not delete a domain until deletion is confirmed', async () => {
    mockGet.mockResolvedValue(tenant);
    mockDelete.mockResolvedValueOnce({});
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');

    await user.click(screen.getByRole('button', { name: '删除' }));
    await user.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(mockDelete).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: '删除' }));
    await user.click(screen.getByRole('button', { name: /确\s*定/ }));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/platform/tenants/tenant-careray/domains/domain-secondary'));
  });

  it('ignores an old detail response after switching tenants', async () => {
    let resolveFirst: ((value: typeof tenant) => void) | undefined;
    const firstRequest = new Promise<typeof tenant>((resolve) => { resolveFirst = resolve; });
    const nextTenant = { ...tenant, id: 'tenant-photonthix', name: '光子科技', code: 'photonthix', domains: [] };
    mockGet.mockReturnValueOnce(firstRequest).mockResolvedValueOnce(nextTenant);

    const view = render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    view.rerender(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-photonthix" />);

    expect(await screen.findByText('光子科技')).toBeInTheDocument();
    resolveFirst?.(tenant);
    await Promise.resolve();
    expect(screen.queryByText('凯锐招聘')).not.toBeInTheDocument();
  });

  it('clears the previous company immediately while the next company detail is loading', async () => {
    let resolveNext: ((value: typeof tenant) => void) | undefined;
    const nextRequest = new Promise<typeof tenant>((resolve) => { resolveNext = resolve; });
    const nextTenant = { ...tenant, id: 'tenant-photonthix', name: '光子科技', code: 'photonthix', domains: [] };
    mockGet.mockResolvedValueOnce(tenant).mockReturnValueOnce(nextRequest);

    const view = render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    expect(await screen.findByText('凯锐招聘')).toBeInTheDocument();

    view.rerender(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-photonthix" />);
    expect(screen.queryByText('凯锐招聘')).not.toBeInTheDocument();

    resolveNext?.(nextTenant);
    expect(await screen.findByText('光子科技')).toBeInTheDocument();
  });

  it('does not reload a switched-away tenant after its delayed domain update succeeds', async () => {
    let resolveUpdate: (() => void) | undefined;
    const updateRequest = new Promise<void>((resolve) => { resolveUpdate = resolve; });
    const nextTenant = { ...tenant, id: 'tenant-photonthix', name: '光子科技', code: 'photonthix', domains: [] };
    mockGet.mockResolvedValueOnce(tenant).mockResolvedValueOnce(nextTenant);
    mockPatch.mockReturnValueOnce(updateRequest);
    const onChanged = vi.fn();
    const user = userEvent.setup();

    const view = render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(screen.getByRole('button', { name: '设为主域名' }));
    const callsBeforeSwitch = mockGet.mock.calls.length;

    view.rerender(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-photonthix" />);
    expect(await screen.findByText('光子科技')).toBeInTheDocument();
    resolveUpdate?.();

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(mockGet.mock.calls.slice(callsBeforeSwitch)).not.toContainEqual(['/platform/tenants/tenant-careray']);
    expect(screen.queryByText('凯锐招聘')).not.toBeInTheDocument();
  });

  it('does not reload a closed tenant after its delayed domain update succeeds', async () => {
    let resolveUpdate: (() => void) | undefined;
    const updateRequest = new Promise<void>((resolve) => { resolveUpdate = resolve; });
    mockGet.mockResolvedValueOnce(tenant);
    mockPatch.mockReturnValueOnce(updateRequest);
    const onChanged = vi.fn();
    const user = userEvent.setup();

    const view = render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(screen.getByRole('button', { name: '设为主域名' }));
    const callsBeforeClose = mockGet.mock.calls.length;

    view.rerender(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open={false} tenantId="tenant-careray" />);
    resolveUpdate?.();

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(mockGet.mock.calls.slice(callsBeforeClose)).not.toContainEqual(['/platform/tenants/tenant-careray']);
  });

  it('shows a Chinese error and keeps domain controls usable when a write fails', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPost.mockRejectedValueOnce(new Error('network unavailable'));
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('interview.careray.com');
    await user.click(screen.getByRole('button', { name: '新增域名' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: 'jobs.careray.com' } });
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    expect(await screen.findByText('域名操作失败，请稍后重试')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /取\s*消/ })).toBeEnabled();
  });

  it('refreshes detail and parent list after editing a domain', async () => {
    mockGet.mockResolvedValue(tenant);
    mockPatch.mockResolvedValueOnce({});
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(domainActions('careers.careray.com').getByRole('button', { name: '编辑' }));
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('refreshes detail and parent list after deleting a domain', async () => {
    mockGet.mockResolvedValue(tenant);
    mockDelete.mockResolvedValueOnce({});
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(screen.getByRole('button', { name: '删除' }));
    await user.click(screen.getByRole('button', { name: /确\s*定/ }));

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('closes and resets an edited domain modal immediately when the tenant scope changes', async () => {
    const nextTenant = { ...tenant, id: 'tenant-photonthix', name: '光子科技', code: 'photonthix', domains: [] };
    mockGet.mockResolvedValueOnce(tenant).mockResolvedValueOnce(nextTenant);
    const user = userEvent.setup();

    const view = render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(domainActions('careers.careray.com').getByRole('button', { name: '编辑' }));
    expect(screen.getByLabelText('域名')).toHaveValue('careers.careray.com');

    view.rerender(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-photonthix" />);

    expect(await screen.findByText('光子科技')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '新增域名' }));
    expect(screen.getByLabelText('域名')).toHaveValue('');
  });

  it('does not let a delayed A-domain save close a newly opened B-domain modal', async () => {
    let resolveUpdate: (() => void) | undefined;
    const updateRequest = new Promise<void>((resolve) => { resolveUpdate = resolve; });
    const nextTenant = { ...tenant, id: 'tenant-photonthix', name: '光子科技', code: 'photonthix', domains: [] };
    mockGet.mockResolvedValueOnce(tenant).mockResolvedValueOnce(nextTenant);
    mockPatch.mockReturnValueOnce(updateRequest);
    const onChanged = vi.fn();
    const user = userEvent.setup();

    const view = render(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(domainActions('careers.careray.com').getByRole('button', { name: '编辑' }));
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    view.rerender(<TenantDetailDrawer onChanged={onChanged} onClose={vi.fn()} open tenantId="tenant-photonthix" />);
    await screen.findByText('光子科技');
    await user.click(screen.getByRole('button', { name: '新增域名' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: 'b.example.com' } });

    resolveUpdate?.();

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('域名')).toHaveValue('b.example.com');
  });

  it('does not let a delayed A-domain failure show an error in B-domain modal', async () => {
    let rejectUpdate: ((reason?: unknown) => void) | undefined;
    const updateRequest = new Promise<void>((_, reject) => { rejectUpdate = reject; });
    const nextTenant = { ...tenant, id: 'tenant-photonthix', name: '光子科技', code: 'photonthix', domains: [] };
    mockGet.mockResolvedValueOnce(tenant).mockResolvedValueOnce(nextTenant);
    mockPatch.mockReturnValueOnce(updateRequest);
    const user = userEvent.setup();

    const view = render(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-careray" />);
    await screen.findByText('careers.careray.com');
    await user.click(domainActions('careers.careray.com').getByRole('button', { name: '编辑' }));
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    view.rerender(<TenantDetailDrawer onChanged={vi.fn()} onClose={vi.fn()} open tenantId="tenant-photonthix" />);
    await screen.findByText('光子科技');
    await user.click(screen.getByRole('button', { name: '新增域名' }));
    fireEvent.change(screen.getByLabelText('域名'), { target: { value: 'b.example.com' } });

    rejectUpdate?.(new Error('network unavailable'));

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByLabelText('域名')).toHaveValue('b.example.com');
    expect(screen.queryByText('域名操作失败，请稍后重试')).not.toBeInTheDocument();
  });
});
