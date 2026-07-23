import { Alert, Button, Descriptions, Drawer, Form, Input, List, Modal, Popconfirm, Tag } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { PlatformDomain, PlatformTenantDetail } from '../../types/platform';
import platformRequest from '../../utils/platformRequest';
import './platform.css';

interface TenantDetailDrawerProps {
  tenantId: string | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

const TenantDetailDrawer = ({ tenantId, open, onClose, onChanged }: TenantDetailDrawerProps) => {
  const [domainForm] = Form.useForm<{ domain: string }>();
  const requestVersion = useRef(0);
  const [tenant, setTenant] = useState<PlatformTenantDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [domainModalOpen, setDomainModalOpen] = useState(false);
  const [savingDomain, setSavingDomain] = useState(false);
  const [editingDomain, setEditingDomain] = useState<PlatformDomain | null>(null);

  const loadTenant = useCallback(async () => {
    if (!tenantId || !open) return;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setLoading(true);
    setHasError(false);

    try {
      const response = await platformRequest.get(`/platform/tenants/${tenantId}`) as PlatformTenantDetail;
      if (requestVersion.current === version) setTenant(response);
    } catch {
      if (requestVersion.current === version) setHasError(true);
    } finally {
      if (requestVersion.current === version) setLoading(false);
    }
  }, [open, tenantId]);

  useEffect(() => {
    void loadTenant();
    return () => { requestVersion.current += 1; };
  }, [loadTenant]);

  const closeDomainModal = () => {
    setDomainModalOpen(false);
    setEditingDomain(null);
    domainForm.resetFields();
  };

  const openCreateDomain = () => {
    setEditingDomain(null);
    domainForm.resetFields();
    setDomainModalOpen(true);
  };

  const openEditDomain = (domain: PlatformDomain) => {
    setEditingDomain(domain);
    domainForm.setFieldsValue({ domain: domain.domain });
    setDomainModalOpen(true);
  };

  const handleSaveDomain = async ({ domain }: { domain: string }) => {
    if (!tenantId) return;
    setSavingDomain(true);
    try {
      if (editingDomain) {
        await platformRequest.patch(`/platform/tenants/${tenantId}/domains/${editingDomain.id}`, { domain });
      } else {
        await platformRequest.post(`/platform/tenants/${tenantId}/domains`, { domain, is_primary: false });
      }
      closeDomainModal();
      await loadTenant();
      onChanged();
    } finally {
      setSavingDomain(false);
    }
  };

  const setPrimaryDomain = async (domain: PlatformDomain) => {
    if (!tenantId) return;
    await platformRequest.patch(`/platform/tenants/${tenantId}/domains/${domain.id}`, { is_primary: true });
    await loadTenant();
    onChanged();
  };

  const deleteDomain = async (domain: PlatformDomain) => {
    if (!tenantId) return;
    await platformRequest.delete(`/platform/tenants/${tenantId}/domains/${domain.id}`);
    await loadTenant();
    onChanged();
  };

  return (
    <Drawer className="platform-tenant-detail" destroyOnHidden onClose={onClose} open={open} size="large" title="公司详情">
      {hasError ? (
        <Alert
          action={<Button icon={<ReloadOutlined />} onClick={() => void loadTenant()} type="primary">重新加载</Button>}
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
          <div className="platform-tenant-detail__domains-heading">
            <div>
              <p className="platform-eyebrow">域名登记</p>
              <h2>域名</h2>
            </div>
            <Button onClick={openCreateDomain} type="primary">新增域名</Button>
          </div>
          <List
            className="platform-tenant-detail__domains"
            dataSource={tenant.domains}
            loading={loading}
            locale={{ emptyText: '暂无已登记域名' }}
            renderItem={(domain) => (
              <List.Item actions={domain.is_primary ? undefined : [
                <Button key="edit" onClick={() => openEditDomain(domain)} type="link">编辑</Button>,
                <Button key="primary" onClick={() => void setPrimaryDomain(domain)} type="link">设为主域名</Button>,
                <Popconfirm cancelText="取消" description="删除后无法恢复。" key="delete" okText="确定" onConfirm={() => void deleteDomain(domain)} title="确认删除此备用域名吗？">
                  <Button danger type="link">删除</Button>
                </Popconfirm>,
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
        <Form<{ domain: string }> form={domainForm} layout="vertical" onFinish={handleSaveDomain} requiredMark={false}>
          <Form.Item label="域名" name="domain" normalize={(value) => value.trim().toLowerCase()} rules={[{ required: true, message: '请输入域名' }]}>
            <Input autoComplete="url" placeholder="例如：careers.example.com" />
          </Form.Item>
          <div className="platform-tenant-detail__form-actions">
            <Button onClick={closeDomainModal}>取消</Button>
            <Button htmlType="submit" loading={savingDomain} type="primary">保存</Button>
          </div>
        </Form>
      </Modal>
    </Drawer>
  );
};

export default TenantDetailDrawer;
