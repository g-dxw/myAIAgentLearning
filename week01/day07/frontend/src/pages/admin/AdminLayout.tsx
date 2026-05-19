import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Button, Typography, App } from 'antd';
import {
  TeamOutlined,
  UserOutlined,
  CalendarOutlined,
  FileTextOutlined,
  BarChartOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const menuItems = [
  { key: '/admin/workers', icon: <TeamOutlined />, label: '护工管理' },
  { key: '/admin/patients', icon: <UserOutlined />, label: '病人管理' },
  { key: '/admin/schedules', icon: <CalendarOutlined />, label: '排班管理' },
  { key: '/admin/records', icon: <FileTextOutlined />, label: '护理记录' },
  { key: '/admin/absenteeism', icon: <BarChartOutlined />, label: '出勤统计' },
  { key: '/admin/settings', icon: <SettingOutlined />, label: '系统设置' },
];

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { modal } = App.useApp();

  const handleLogout = () => {
    modal.confirm({
      title: '确认退出',
      content: '确定要退出登录吗？',
      onOk: () => {
        logout();
        navigate('/login', { replace: true });
      },
    });
  };

  const selectedKey = menuItems.find(
    (item) => location.pathname.startsWith(item.key)
  )?.key || '';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider trigger={null} collapsible collapsed={collapsed} theme="dark">
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text strong style={{ color: '#fff', fontSize: collapsed ? 14 : 18 }}>
            {collapsed ? '养老' : '养老管理系统'}
          </Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            padding: '0 24px',
            background: '#fff',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Text>管理员</Text>
            <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout}>
              退出
            </Button>
          </div>
        </Header>
        <Content
          style={{
            margin: 24,
            padding: 24,
            background: '#fff',
            borderRadius: 8,
            minHeight: 280,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
