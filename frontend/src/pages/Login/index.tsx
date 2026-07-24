import React from 'react';
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import type { LoginPayload, TenantSummary } from '../../types/tenant';
import request from '../../utils/request';

const { Title, Text } = Typography;

const Login: React.FC = () => {
  const { login, isAuthenticated, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [form] = Form.useForm<LoginPayload>();
  const [loading, setLoading] = React.useState(false);
  const [tenants, setTenants] = React.useState<TenantSummary[]>([]);
  const [tenantsLoading, setTenantsLoading] = React.useState(true);
  const [tenantsError, setTenantsError] = React.useState(false);

  React.useEffect(() => {
    if (!authLoading && isAuthenticated) {
      navigate('/dashboard', { replace: true });
    }
  }, [authLoading, isAuthenticated, navigate]);

  const loadTenants = React.useCallback(async () => {
    setTenantsLoading(true);
    setTenantsError(false);
    try {
      const response = await request.get('/auth/tenants') as TenantSummary[];
      const nextTenants = Array.isArray(response) ? response : [];
      setTenants(nextTenants);
    } catch {
      setTenants([]);
      setTenantsError(true);
    } finally {
      setTenantsLoading(false);
    }
  }, [form]);

  React.useEffect(() => {
    void loadTenants();
  }, [loadTenants]);

  const onFinish = async (values: LoginPayload) => {
    setLoading(true);
    try {
      const response = await request.post('/auth/login', values) as { access_token: string };
      const authenticated = await login(response.access_token);
      if (!authenticated) throw new Error('Unable to verify session');
      message.success('登录成功');
      navigate('/dashboard', { replace: true });
    } catch {
      message.error('登录失败，请检查公司、邮箱和密码后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: 'var(--background-color)' }}>
      <Card style={{ width: 'min(400px, calc(100vw - 32px))', boxShadow: 'var(--shadow-md)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3}>AI 智能面试系统</Title>
          <Text type="secondary">选择公司后登录您的账号</Text>
        </div>

        <Form name="login" form={form} onFinish={onFinish} size="large">
          {tenantsError && (
            <Alert
              type="error"
              showIcon
              title="公司列表加载失败"
              description="请检查网络连接后重新加载。"
              action={<Button size="small" onClick={() => void loadTenants()}>重新加载公司列表</Button>}
              style={{ marginBottom: 16 }}
            />
          )}

          <Form.Item label="公司" name="tenant_code" rules={[{ required: true, message: '请选择公司' }]}>
            <select
              aria-label="公司"
              disabled={tenantsLoading}
              style={{ width: '100%', minHeight: 40, padding: '6px 12px', border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius-sm)', background: 'var(--surface-color)', color: 'var(--text-primary)' }}
            >
              <option value="">{tenantsLoading ? '正在加载公司…' : '请选择公司'}</option>
              {tenants.map((tenant) => <option key={tenant.id} value={tenant.code}>{tenant.name}</option>)}
            </select>
          </Form.Item>

          <Form.Item label="邮箱" name="email" rules={[{ required: true, message: '请输入邮箱' }]}>
            <Input prefix={<UserOutlined />} placeholder="admin@example.com" autoComplete="email" />
          </Form.Item>

          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" style={{ width: '100%' }} loading={loading} disabled={tenantsLoading || tenantsError}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default Login;
