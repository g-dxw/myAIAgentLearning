import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Typography } from 'antd';
import {
  CalendarOutlined,
  UserOutlined,
  FileTextOutlined,
  BellOutlined,
} from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';

const { Header, Content } = Layout;
const { Text } = Typography;

const tabs = [
  { key: '/worker/schedules', icon: <CalendarOutlined />, label: '排班' },
  { key: '/worker/patients', icon: <UserOutlined />, label: '病人' },
  { key: '/worker/records', icon: <FileTextOutlined />, label: '记录' },
  { key: '/worker/reminders', icon: <BellOutlined />, label: '提醒' },
];

export default function WorkerLayout() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const activeKey =
    tabs.find((t) => location.pathname.startsWith(t.key))?.key || tabs[0].key;

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <Layout style={{ minHeight: '100vh', maxWidth: 768, margin: '0 auto' }}>
      <Header
        style={{
          background: '#fff',
          padding: '0 16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #f0f0f0',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <Text strong style={{ fontSize: 18 }}>
          护工工作台
        </Text>
        <a onClick={handleLogout} style={{ fontSize: 14, cursor: 'pointer' }}>
          退出
        </a>
      </Header>
      <Content style={{ padding: 16, paddingBottom: 64 }}>
        <Outlet />
      </Content>
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          width: '100%',
          maxWidth: 768,
          display: 'flex',
          background: '#fff',
          borderTop: '1px solid #f0f0f0',
          zIndex: 10,
        }}
      >
        {tabs.map((tab) => {
          const isActive = activeKey === tab.key;
          return (
            <div
              key={tab.key}
              onClick={() => navigate(tab.key)}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '8px 0',
                color: isActive ? '#1677ff' : '#999',
                cursor: 'pointer',
              }}
            >
              <span style={{ fontSize: 20 }}>{tab.icon}</span>
              <span style={{ fontSize: 12, marginTop: 2 }}>{tab.label}</span>
            </div>
          );
        })}
      </div>
    </Layout>
  );
}
