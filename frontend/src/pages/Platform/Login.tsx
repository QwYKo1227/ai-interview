import { Alert, Button, Form, Input } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePlatformAuth } from '../../contexts/PlatformAuthContext';
import platformRequest from '../../utils/platformRequest';
import './platform.css';

interface PlatformLoginPayload {
  email: string;
  password: string;
}

const PlatformLogin = () => {
  const { isAuthenticated, login } = usePlatformAuth();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    if (isAuthenticated) navigate('/platform/tenants', { replace: true });
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (values: PlatformLoginPayload) => {
    setSubmitting(true);
    setHasError(false);

    try {
      const response = await platformRequest.post('/platform/auth/login', values) as { access_token: string };
      login(response.access_token);
      navigate('/platform/tenants', { replace: true });
    } catch {
      setHasError(true);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="platform-login" aria-labelledby="platform-login-title">
      <section className="platform-login__panel">
        <div className="platform-login__signal" aria-hidden="true" />
        <div className="platform-login__heading">
          <p className="platform-eyebrow">平台管理员 / 安全入口</p>
          <h1 id="platform-login-title">AI Interview 平台管理中心</h1>
          <p className="platform-login__description">验证管理员身份后，进入公司注册表。</p>
        </div>

        <Form<PlatformLoginPayload>
          className="platform-login__form"
          layout="vertical"
          onFinish={handleSubmit}
          requiredMark={false}
          size="large"
        >
          {hasError && (
            <Alert
              className="platform-login__alert"
              message="登录失败，请检查邮箱和密码"
              showIcon
              type="error"
            />
          )}
          <Form.Item label="邮箱" name="email" rules={[{ required: true, message: '请输入邮箱' }]}>
            <Input autoComplete="email" prefix={<UserOutlined />} placeholder="platform@example.com" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password autoComplete="current-password" prefix={<LockOutlined />} placeholder="请输入密码" />
          </Form.Item>
          <Form.Item className="platform-login__submit">
            <Button block htmlType="submit" loading={submitting} type="primary">登录</Button>
          </Form.Item>
        </Form>
      </section>
    </main>
  );
};

export default PlatformLogin;
