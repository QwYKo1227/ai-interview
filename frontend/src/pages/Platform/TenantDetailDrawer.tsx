import { Alert, Button, Checkbox, Descriptions, Drawer, Form, Input, List, Modal, Popconfirm, Tag } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { PlatformDomain, PlatformTenantAdmin, PlatformTenantDetail } from '../../types/platform';
import platformRequest from '../../utils/platformRequest';
import './platform.css';

interface TenantDetailDrawerProps {
  tenantId: string | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

const TenantDetailDrawer = ({ tenantId, open, onClose, onChanged }: TenantDetailDrawerProps) => {
  const [domainForm] = Form.useForm<{ domain: string; is_primary: boolean }>();
  const [passwordForm] = Form.useForm<{ new_password: string; confirm_password: string }>();
  const requestVersion = useRef(0);
  const scopeVersion = useRef(0);
  const passwordRequestVersion = useRef(0);
  const currentScope = useRef({ open, tenantId });
  const [tenant, setTenant] = useState<PlatformTenantDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [domainModalOpen, setDomainModalOpen] = useState(false);
  const [savingDomain, setSavingDomain] = useState(false);
  const [editingDomain, setEditingDomain] = useState<PlatformDomain | null>(null);
  const [domainActionError, setDomainActionError] = useState<string | null>(null);
  const [resetAdmin, setResetAdmin] = useState<PlatformTenantAdmin | null>(null);
  const [resettingPassword, setResettingPassword] = useState(false);
  const [passwordResetError, setPasswordResetError] = useState<string | null>(null);
  const [passwordResetSuccess, setPasswordResetSuccess] = useState<string | null>(null);

  useLayoutEffect(() => {
    scopeVersion.current += 1;
    passwordRequestVersion.current += 1;
    currentScope.current = { open, tenantId };
    requestVersion.current += 1;
    setTenant(null);
    setHasError(false);
    setLoading(Boolean(open && tenantId));
    setDomainModalOpen(false);
    setEditingDomain(null);
    setDomainActionError(null);
    setSavingDomain(false);
    setResetAdmin(null);
    setResettingPassword(false);
    setPasswordResetError(null);
    setPasswordResetSuccess(null);
    if (domainModalOpen) domainForm.resetFields();
  }, [domainForm, open, passwordForm, tenantId]);

  const loadTenant = useCallback(async (requestedTenantId: string) => {
    if (!currentScope.current.open || currentScope.current.tenantId !== requestedTenantId) return;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setLoading(true);
    setHasError(false);

    try {
      const response = await platformRequest.get(`/platform/tenants/${requestedTenantId}`) as PlatformTenantDetail;
      if (requestVersion.current === version && currentScope.current.open && currentScope.current.tenantId === requestedTenantId) {
        setTenant(response);
      }
    } catch {
      if (requestVersion.current === version && currentScope.current.open && currentScope.current.tenantId === requestedTenantId) {
        setHasError(true);
      }
    } finally {
      if (requestVersion.current === version && currentScope.current.open && currentScope.current.tenantId === requestedTenantId) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (open && tenantId) void loadTenant(tenantId);
  }, [loadTenant, open, tenantId]);

  useEffect(() => () => {
    scopeVersion.current += 1;
    requestVersion.current += 1;
    passwordRequestVersion.current += 1;
    currentScope.current = { open: false, tenantId: null };
  }, []);

  const closeDomainModal = () => {
    setDomainModalOpen(false);
    setEditingDomain(null);
    setDomainActionError(null);
    domainForm.resetFields();
  };

  const openCreateDomain = () => {
    setEditingDomain(null);
    setDomainActionError(null);
    domainForm.resetFields();
    domainForm.setFieldsValue({ is_primary: false });
    setDomainModalOpen(true);
  };

  const openEditDomain = (domain: PlatformDomain) => {
    setEditingDomain(domain);
    setDomainActionError(null);
    domainForm.setFieldsValue({ domain: domain.domain });
    setDomainModalOpen(true);
  };

  const handleDomainAction = async (
    operationTenantId: string,
    operationScopeVersion: number,
    operation: () => Promise<unknown>,
  ) => {
    setDomainActionError(null);
    const isOperationCurrent = () => (
      scopeVersion.current === operationScopeVersion
      && currentScope.current.open
      && currentScope.current.tenantId === operationTenantId
    );
    try {
      await operation();
      if (isOperationCurrent()) {
        await loadTenant(operationTenantId);
      }
      onChanged();
      return { succeeded: true, isCurrent: isOperationCurrent() };
    } catch {
      if (isOperationCurrent()) setDomainActionError('域名操作失败，请稍后重试');
      return { succeeded: false, isCurrent: isOperationCurrent() };
    }
  };

  const handleSaveDomain = async ({ domain, is_primary = false }: { domain: string; is_primary?: boolean }) => {
    const operationTenantId = tenantId;
    if (!operationTenantId) return;
    const operationScopeVersion = scopeVersion.current;
    setSavingDomain(true);
    try {
      const result = await handleDomainAction(operationTenantId, operationScopeVersion, () => {
        if (editingDomain) {
          return platformRequest.patch(`/platform/tenants/${operationTenantId}/domains/${editingDomain.id}`, { domain });
        }
        return platformRequest.post(`/platform/tenants/${operationTenantId}/domains`, { domain, is_primary });
      });
      if (result.succeeded && result.isCurrent) closeDomainModal();
    } finally {
      if (scopeVersion.current === operationScopeVersion) setSavingDomain(false);
    }
  };

  const setPrimaryDomain = async (domain: PlatformDomain) => {
    const operationTenantId = tenantId;
    if (!operationTenantId) return;
    await handleDomainAction(operationTenantId, scopeVersion.current, () => (
      platformRequest.patch(`/platform/tenants/${operationTenantId}/domains/${domain.id}`, { is_primary: true })
    ));
  };

  const deleteDomain = async (domain: PlatformDomain) => {
    const operationTenantId = tenantId;
    if (!operationTenantId) return;
    await handleDomainAction(operationTenantId, scopeVersion.current, () => (
      platformRequest.delete(`/platform/tenants/${operationTenantId}/domains/${domain.id}`)
    ));
  };

  const closePasswordModal = () => {
    passwordRequestVersion.current += 1;
    setResetAdmin(null);
    setResettingPassword(false);
    setPasswordResetError(null);
    passwordForm.resetFields();
  };

  const openPasswordModal = (admin: PlatformTenantAdmin) => {
    passwordRequestVersion.current += 1;
    passwordForm.resetFields();
    setResettingPassword(false);
    setPasswordResetError(null);
    setPasswordResetSuccess(null);
    setResetAdmin(admin);
  };

  const handleResetPassword = async ({ new_password }: { new_password: string; confirm_password: string }) => {
    const operationTenantId = tenantId;
    const operationAdmin = resetAdmin;
    if (!operationTenantId || !operationAdmin) return;
    const operationScopeVersion = scopeVersion.current;
    const operationRequestVersion = passwordRequestVersion.current;
    const isOperationCurrent = () => (
      passwordRequestVersion.current === operationRequestVersion
      && scopeVersion.current === operationScopeVersion
      && currentScope.current.open
      && currentScope.current.tenantId === operationTenantId
    );
    setResettingPassword(true);
    setPasswordResetError(null);
    try {
      await platformRequest.patch(
        `/platform/tenants/${operationTenantId}/admins/${operationAdmin.id}/password`,
        { new_password },
      );
      if (isOperationCurrent()) {
        setPasswordResetSuccess(`已重置 ${operationAdmin.email} 的密码`);
        closePasswordModal();
      }
    } catch {
      if (isOperationCurrent()) {
        setPasswordResetError('密码重置失败，请稍后重试');
      }
    } finally {
      if (isOperationCurrent()) setResettingPassword(false);
    }
  };

  const passwordRules = [
    { required: true, message: '请输入新密码' },
    {
      validator: (_: unknown, value?: string) => {
        if (!value) return Promise.resolve();
        const bytes = new TextEncoder().encode(value).length;
        if (bytes < 12 || bytes > 72 || !/\p{L}/u.test(value) || !/\p{N}/u.test(value)) {
          return Promise.reject(new Error('密码须为 12–72 个 UTF-8 字节，并包含字母和数字'));
        }
        return Promise.resolve();
      },
    },
  ];

  return (
    <Drawer className="platform-tenant-detail" destroyOnHidden onClose={onClose} open={open} size="large" title="公司详情">
      {hasError ? (
        <Alert
          action={tenantId && <Button icon={<ReloadOutlined />} onClick={() => void loadTenant(tenantId)} type="primary">重新加载</Button>}
          showIcon
          title="公司详情暂时无法加载"
          type="error"
        />
      ) : tenant && (
        <>
          <Descriptions bordered className="platform-tenant-detail__summary" column={1} size="small">
            <Descriptions.Item label="公司名称">{tenant.name}</Descriptions.Item>
            <Descriptions.Item label="公司代码">{tenant.code}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color={tenant.status === 'active' ? 'cyan' : 'default'}>{tenant.status === 'active' ? '启用中' : '已停用'}</Tag></Descriptions.Item>
          </Descriptions>
          <div className="platform-tenant-detail__admins-heading">
            <p className="platform-eyebrow">账号管理</p>
            <h2>企业管理员</h2>
          </div>
          {passwordResetSuccess && <Alert className="platform-tenant-detail__admin-alert" showIcon title={passwordResetSuccess} type="success" />}
          <List
            className="platform-tenant-detail__admins"
            dataSource={tenant.admins ?? []}
            locale={{ emptyText: '暂无企业管理员' }}
            renderItem={(admin) => (
              <List.Item actions={[
                <Button key="reset-password" onClick={() => openPasswordModal(admin)} type="link">重置密码</Button>,
              ]}>
                <List.Item.Meta
                  description={<>{admin.full_name || '未填写姓名'} · <Tag color={admin.is_active ? 'green' : 'default'}>{admin.is_active ? '已启用' : '已停用'}</Tag></>}
                  title={admin.email}
                />
              </List.Item>
            )}
          />
          <div className="platform-tenant-detail__domains-heading">
            <div>
              <p className="platform-eyebrow">域名登记</p>
              <h2>域名</h2>
            </div>
            <Button onClick={openCreateDomain} type="primary">新增域名</Button>
          </div>
          {domainActionError && <Alert className="platform-tenant-detail__domain-alert" showIcon title={domainActionError} type="error" />}
          <List
            className="platform-tenant-detail__domains"
            dataSource={tenant.domains}
            loading={loading}
            locale={{ emptyText: '暂无已登记域名' }}
            renderItem={(domain) => (
              <List.Item actions={[
                <Button key="edit" onClick={() => openEditDomain(domain)} type="link">编辑</Button>,
                ...(!domain.is_primary ? [
                  <Button key="primary" onClick={() => void setPrimaryDomain(domain)} type="link">设为主域名</Button>,
                  <Popconfirm cancelText="取消" description="删除后无法恢复。" key="delete" okText="确定" onConfirm={() => void deleteDomain(domain)} title="确认删除此备用域名吗？">
                    <Button danger type="link">删除</Button>
                  </Popconfirm>,
                ] : []),
              ]}>
                <List.Item.Meta
                  description={domain.is_primary ? <Tag color="blue">主域名</Tag> : '备用域名'}
                  title={domain.domain}
                />
              </List.Item>
            )}
          />
          <Alert className="platform-tenant-detail__dns-note" showIcon title="DNS、Hosts 和 Caddy 配置需要另行维护。" type="info" />
        </>
      )}
      <Modal className="platform-tenant-detail__modal" footer={null} onCancel={closeDomainModal} open={domainModalOpen} title={editingDomain ? '编辑域名' : '新增域名'}>
        <Form<{ domain: string; is_primary: boolean }> form={domainForm} layout="vertical" onFinish={handleSaveDomain} requiredMark={false}>
          <Form.Item label="域名" name="domain" normalize={(value) => value.trim().toLowerCase()} rules={[{ required: true, message: '请输入域名' }]}>
            <Input autoComplete="url" placeholder="例如：careers.example.com" />
          </Form.Item>
          {!editingDomain && (
            <Form.Item name="is_primary" valuePropName="checked">
              <Checkbox>设为主域名</Checkbox>
            </Form.Item>
          )}
          <div className="platform-tenant-detail__form-actions">
            <Button onClick={closeDomainModal}>取消</Button>
            <Button htmlType="submit" loading={savingDomain} type="primary">保存</Button>
          </div>
        </Form>
      </Modal>
      <Modal className="platform-tenant-detail__modal" footer={null} onCancel={closePasswordModal} open={Boolean(resetAdmin)} title="重置企业管理员密码">
        <p className="platform-tenant-detail__modal-description">目标账号：{resetAdmin?.email}</p>
        {passwordResetError && <Alert className="platform-tenant-detail__admin-alert" showIcon title={passwordResetError} type="error" />}
        <Form<{ new_password: string; confirm_password: string }> form={passwordForm} layout="vertical" onFinish={handleResetPassword} requiredMark={false}>
          <Form.Item label="新密码" name="new_password" rules={passwordRules}>
            <Input.Password autoComplete="new-password" placeholder="12–72 个字节，包含字母和数字" />
          </Form.Item>
          <Form.Item
            dependencies={['new_password']}
            label="确认新密码"
            name="confirm_password"
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_: unknown, value?: string) => (
                  !value || getFieldValue('new_password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致'))
                ),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="再次输入新密码" />
          </Form.Item>
          <div className="platform-tenant-detail__form-actions">
            <Button onClick={closePasswordModal}>取消</Button>
            <Button htmlType="submit" loading={resettingPassword} type="primary">确认重置</Button>
          </div>
        </Form>
      </Modal>
    </Drawer>
  );
};

export default TenantDetailDrawer;
