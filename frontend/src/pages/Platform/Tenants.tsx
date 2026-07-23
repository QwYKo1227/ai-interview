import { Alert, Button, Form, Input, Modal, Table, Tag } from 'antd';
import type { TableColumnsType } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { PlatformTenant, TenantOnboardingPayload } from '../../types/platform';
import platformRequest from '../../utils/platformRequest';
import './platform.css';

interface PlatformTenantsProps {
  onOpenTenant?: (tenantId: string) => void;
}

const tenantColumns = (onOpenTenant: (tenantId: string) => void): TableColumnsType<PlatformTenant> => [
  {
    dataIndex: 'name',
    key: 'name',
    title: '公司名称',
    render: (name: string, tenant: PlatformTenant) => (
      <div className="platform-tenants__company">
        <strong>{name}</strong>
        <code>{tenant.code}</code>
      </div>
    ),
  },
  {
    dataIndex: 'primary_domain',
    key: 'primary_domain',
    title: '主域名',
    render: (domain: string | null | undefined) => domain || '未设置',
  },
  {
    dataIndex: 'status',
    key: 'status',
    title: '状态',
    width: 112,
    render: (status: PlatformTenant['status']) => (
      <Tag color={status === 'active' ? 'cyan' : 'default'}>
        {status === 'active' ? '启用中' : '已停用'}
      </Tag>
    ),
  },
  {
    dataIndex: 'created_at',
    key: 'created_at',
    title: '创建时间',
    width: 192,
    render: (createdAt: string) => <time dateTime={createdAt}>{createdAt}</time>,
  },
  {
    key: 'actions',
    title: '操作',
    width: 104,
    render: (_, tenant: PlatformTenant) => (
      <Button onClick={() => onOpenTenant(tenant.id)} type="link">查看详情</Button>
    ),
  },
];

const PlatformTenants = ({ onOpenTenant = () => undefined }: PlatformTenantsProps) => {
  const [form] = Form.useForm<TenantOnboardingPayload>();
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [isOnboardingOpen, setIsOnboardingOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [onboardingError, setOnboardingError] = useState<string | null>(null);

  const loadTenants = useCallback(async () => {
    setLoading(true);
    setHasError(false);

    try {
      const response = await platformRequest.get('/platform/tenants') as PlatformTenant[];
      setTenants(response);
    } catch {
      setHasError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTenants();
  }, [loadTenants]);

  const stats = useMemo(() => ({
    total: tenants.length,
    active: tenants.filter((tenant) => tenant.status === 'active').length,
    inactive: tenants.filter((tenant) => tenant.status === 'inactive').length,
  }), [tenants]);

  const closeOnboarding = () => {
    setIsOnboardingOpen(false);
    setOnboardingError(null);
  };

  const handleOnboard = async (values: TenantOnboardingPayload) => {
    setSubmitting(true);
    setOnboardingError(null);

    try {
      await platformRequest.post('/platform/tenants', values);
      form.resetFields();
      closeOnboarding();
      await loadTenants();
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status;
      setOnboardingError(status === 409 ? '公司代码或域名已存在' : '公司创建失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="platform-tenants" aria-labelledby="platform-tenants-title">
      <div className="platform-tenants__heading">
        <div>
          <p className="platform-eyebrow">公司注册表</p>
          <h1 id="platform-tenants-title">公司管理</h1>
          <p className="platform-tenants__description">查看平台内公司的注册状态和主域名。</p>
        </div>
        <Button className="platform-tenants__onboard" onClick={() => setIsOnboardingOpen(true)} type="primary">
          新建公司
        </Button>
      </div>

      <div aria-label="公司统计" className="platform-tenants__stats">
        <span>公司总数 {stats.total}</span>
        <span>已启用 {stats.active}</span>
        <span>已停用 {stats.inactive}</span>
      </div>

      {hasError ? (
        <Alert
          action={<Button icon={<ReloadOutlined />} onClick={() => void loadTenants()} type="primary">重新加载</Button>}
          className="platform-tenants__alert"
          title="公司注册表暂时无法加载"
          showIcon
          type="error"
        />
      ) : (
        <Table<PlatformTenant>
          className="platform-tenants__table"
          columns={tenantColumns(onOpenTenant)}
          dataSource={tenants}
          locale={{ emptyText: '暂无已注册公司' }}
          loading={loading}
          pagination={false}
          rowKey="id"
          scroll={{ x: 640 }}
        />
      )}

      <Modal
        className="platform-tenants__modal"
        footer={null}
        onCancel={closeOnboarding}
        open={isOnboardingOpen}
        title="新建公司"
      >
        <p className="platform-tenants__modal-description">填写注册信息后，将为该公司创建首位管理员账号。</p>
        {onboardingError && <Alert className="platform-tenants__modal-alert" showIcon title={onboardingError} type="error" />}
        <Form<TenantOnboardingPayload>
          className="platform-tenants__form"
          form={form}
          layout="vertical"
          onFinish={handleOnboard}
          requiredMark={false}
        >
          <Form.Item
            label="公司代码"
            name="code"
            normalize={(value) => value.trim().toLowerCase()}
            rules={[
              { required: true, message: '请输入公司代码' },
              { pattern: /^[a-z0-9-]+$/, message: '仅支持小写字母、数字和连字符' },
            ]}
          >
            <Input autoComplete="off" placeholder="例如：photonthix" />
          </Form.Item>
          <Form.Item label="公司名称" name="name" rules={[{ required: true, message: '请输入公司名称' }]}>
            <Input autoComplete="organization" placeholder="例如：Photonthix" />
          </Form.Item>
          <Form.Item
            label="主域名"
            name="primary_domain"
            normalize={(value) => value.trim().toLowerCase()}
            rules={[{ required: true, message: '请输入主域名' }]}
          >
            <Input autoComplete="url" placeholder="例如：interview.example.com" />
          </Form.Item>
          <Form.Item
            label="管理员邮箱"
            name="admin_email"
            normalize={(value) => value.trim().toLowerCase()}
            rules={[{ required: true, type: 'email', message: '请输入有效的管理员邮箱' }]}
          >
            <Input autoComplete="email" placeholder="admin@example.com" />
          </Form.Item>
          <Form.Item
            label="管理员初始密码"
            name="admin_password"
            rules={[
              { required: true, message: '请输入管理员初始密码' },
              { pattern: /[a-zA-Z]/, message: '密码需要包含字母' },
              { pattern: /\d/, message: '密码需要包含数字' },
              {
                validator: (_, value) => {
                  const byteLength = new TextEncoder().encode(value || '').length;
                  if (byteLength < 12) return Promise.reject(new Error('密码至少需要 12 个 UTF-8 字节'));
                  if (byteLength > 72) return Promise.reject(new Error('密码最多支持 72 个 UTF-8 字节'));
                  return Promise.resolve();
                },
              },
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="12 至 72 个字节，包含字母和数字" />
          </Form.Item>
          <div className="platform-tenants__form-actions">
            <Button onClick={closeOnboarding}>取消</Button>
            <Button htmlType="submit" loading={submitting} type="primary">创建公司</Button>
          </div>
        </Form>
      </Modal>
    </section>
  );
};

export default PlatformTenants;
