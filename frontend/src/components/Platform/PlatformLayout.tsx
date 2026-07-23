import { Button } from 'antd';
import { LogoutOutlined } from '@ant-design/icons';
import { Outlet, useNavigate } from 'react-router-dom';
import { usePlatformAuth } from '../../contexts/PlatformAuthContext';
import '../../pages/Platform/platform.css';

const PlatformLayout = () => {
  const { logout } = usePlatformAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/platform/login');
  };

  return (
    <div className="platform-shell">
      <header className="platform-shell__header">
        <div className="platform-shell__brand" aria-label="AI Interview 平台管理中心">
          <span>AI</span> INTERVIEW
        </div>
        <div className="platform-shell__module">
          <span className="platform-shell__module-dot" aria-hidden="true" />
          公司注册表
        </div>
        <Button aria-label="退出登录" className="platform-shell__logout" icon={<LogoutOutlined />} onClick={handleLogout} type="text">
          退出登录
        </Button>
      </header>
      <main className="platform-shell__content">
        <Outlet />
      </main>
    </div>
  );
};

export default PlatformLayout;
