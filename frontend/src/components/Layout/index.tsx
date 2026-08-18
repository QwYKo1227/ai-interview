import React, { useEffect, useState } from 'react';
import { Layout, Menu, Button, Avatar, Space, Dropdown, Grid, Badge } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  FileTextOutlined,
  TeamOutlined,
  BankOutlined,
  CodeOutlined,
  LogoutOutlined,
  BellOutlined,
  SettingOutlined,
  FileAddOutlined,
  ApartmentOutlined,
  AuditOutlined,
  FundProjectionScreenOutlined
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import request from '../../utils/request';

const { Header, Sider, Content } = Layout;

const AppLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, user, companyName } = useAuth();
  const screens = Grid.useBreakpoint();
  const isLaptop = !screens.xxl;
  const siderWidth = isLaptop ? 80 : 240;
  const role = (user as any)?.role?.value ?? (user as any)?.role;
  const [pendingOfferCount, setPendingOfferCount] = useState(0);

  useEffect(() => {
    if (!user || !['admin', 'hr'].includes(role)) {
      setPendingOfferCount(0);
      return;
    }
    const loadPendingCount = () => {
      request.get('/offers/my-pending-count')
        .then((response) => setPendingOfferCount(response?.count || 0))
        .catch(() => setPendingOfferCount(0));
    };
    loadPendingCount();
    window.addEventListener('offer-pending-updated', loadPendingCount);
    return () => window.removeEventListener('offer-pending-updated', loadPendingCount);
  }, [user, role, location.pathname]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const rawMenuItems = [
    {
      key: '/dashboard',
      icon: <DashboardOutlined aria-hidden="true" />,
      label: '仪表盘',
    },
    {
      key: '/recruitment-performance',
      icon: <FundProjectionScreenOutlined aria-hidden="true" />,
      label: '招聘绩效',
      roles: ['admin', 'hr'],
    },
    {
      key: '/positions',
      icon: <UserOutlined aria-hidden="true" />,
      label: '岗位管理',
      roles: ['admin', 'hr'],
    },
    {
      key: '/question-banks',
      icon: <BankOutlined aria-hidden="true" />,
      label: '题库管理',
      roles: ['admin', 'hr'],
    },
    {
      key: '/resumes',
      icon: <FileTextOutlined aria-hidden="true" />,
      label: '简历管理',
      roles: ['admin', 'hr'],
    },
    {
      key: '/resumes/my-reviews',
      icon: <AuditOutlined aria-hidden="true" />,
      label: '我的评审',
      roles: ['interviewer'],
    },
    {
      key: '/interviews',
      icon: <TeamOutlined aria-hidden="true" />,
      label: '面试管理',
    },
    {
      key: '/coding-tests',
      icon: <CodeOutlined aria-hidden="true" />,
      label: '笔试管理',
      roles: ['admin', 'hr'],
    },
    {
      key: '/offers',
      icon: <FileAddOutlined aria-hidden="true" />,
      label: <Badge count={pendingOfferCount} size="small" offset={[10, 0]}>Offer管理</Badge>,
      roles: ['admin', 'hr'],
    },
    {
      key: '/offers/templates',
      icon: <FileTextOutlined aria-hidden="true" />,
      label: 'Offer模板',
      roles: ['admin', 'hr'],
    },
    {
      key: '/workflows',
      icon: <ApartmentOutlined aria-hidden="true" />,
      label: '工作流',
    },
    {
      key: '/settings/users',
      icon: <SettingOutlined aria-hidden="true" />,
      label: '用户管理',
      roles: ['admin'],
    },
  ];

  const menuItems = rawMenuItems;

  const filteredMenuItems = menuItems.filter(item => {
    if (!item.roles) return true;
    return item.roles.includes(role);
  });

  const pageTitle =
    location.pathname.startsWith('/settings/profile')
      ? '个人设置'
      : location.pathname.startsWith('/settings/system')
        ? '系统设置'
        : location.pathname.startsWith('/workflows/')
          ? '工作流编辑'
          : menuItems.find(item => item.key === location.pathname)?.label || 'AI 面试助手';

  const userMenuItems: any[] = [
    {
      key: 'profile',
      label: '个人中心',
      icon: <UserOutlined />,
      onClick: () => navigate('/settings/profile'),
    },
  ];

  if (role === 'admin') {
    userMenuItems.push({
      key: 'settings',
      label: '系统设置',
      icon: <SettingOutlined />,
      onClick: () => navigate('/settings/system'),
    });
  }

  userMenuItems.push(
    { type: 'divider' },
    {
      key: 'logout',
      label: '退出登录',
      icon: <LogoutOutlined />,
      onClick: handleLogout,
    }
  );

  const userMenu = { items: userMenuItems };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider 
        className="app-sider"
        collapsed={isLaptop}
        collapsedWidth={80}
        trigger={null}
        width={240}
        theme="light"
        style={{
          borderRight: '1px solid #f0f0f0',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100
        }}
      >
        <div className="app-brand" style={{
          height: 64, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          color: '#0F172A',
          fontSize: '20px',
          fontWeight: 700,
          letterSpacing: '-0.025em',
          borderBottom: '1px solid #f0f0f0'
        }}>
          <span style={{ color: '#3B82F6' }}>AI</span>{!isLaptop && 'Recruiting'}
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={filteredMenuItems}
          tooltip={{ placement: 'right', trigger: ['hover', 'focus'] }}
          onClick={({ key }) => navigate(key)}
          style={{ padding: '16px 8px', borderRight: 0 }}
        />
      </Sider>
      <Layout className="app-main-layout" style={{ marginLeft: siderWidth }}>
        <Header className={isLaptop ? 'app-header app-header-compact' : 'app-header'} style={{
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          background: 'rgba(255, 255, 255, 0.8)',
          backdropFilter: 'blur(12px)'
        }}>
          <Space size="middle" style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 600, color: '#0F172A' }}>
              {pageTitle}
            </h2>
            {companyName && (
              <span className="app-company-name" aria-label="当前公司">
                {companyName}
              </span>
            )}
          </Space>
          <Space size="large">
            <Button type="text" icon={<BellOutlined style={{ fontSize: '18px', color: '#64748B' }} />} />
            <Dropdown menu={userMenu}>
              <Space style={{ cursor: 'pointer' }}>
                <Avatar style={{ backgroundColor: '#3B82F6' }} icon={<UserOutlined />} />
                <span className="app-user-name" style={{ fontWeight: 500, color: '#0F172A' }}>{user?.full_name || user?.email}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content className="app-content" style={{ margin: '32px', minHeight: 280 }}>
          <div className="page-container">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
};

export default AppLayout;
