import { useState, useEffect } from 'react';
import { Card, Typography, Select, Button, App, Space, Divider } from 'antd';
import { getWorkers } from '../../services/worker';
import { resetPassword } from '../../services/worker';
import type { Worker } from '../../types/worker';

const { Title, Text } = Typography;

export default function SettingsPage() {
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState<number | null>(null);
  const [resetting, setResetting] = useState(false);
  const { message } = App.useApp();

  useEffect(() => {
    getWorkers({ pageSize: 1000, status: 'active' })
      .then(res => setWorkers(res.data))
      .catch(() => {});
  }, []);

  const handleResetPassword = async () => {
    if (!selectedWorkerId) {
      message.warning('请选择护工');
      return;
    }
    setResetting(true);
    try {
      const res = await resetPassword(selectedWorkerId);
      message.success(`密码已重置为身份证后6位`);
      setSelectedWorkerId(null);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败');
    } finally {
      setResetting(false);
    }
  };

  return (
    <div style={{ maxWidth: 500 }}>
      <Title level={4}>系统设置</Title>
      <Card title="重置护工密码">
        <Text type="secondary">重置后密码将恢复为护工身份证号码的后6位</Text>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Select
              style={{ width: 250 }}
              placeholder="选择护工"
              showSearch
              value={selectedWorkerId}
              onChange={setSelectedWorkerId}
              filterOption={(input, option) => (option?.label as string || '').includes(input)}
              options={workers.map(w => ({ value: w.id, label: `${w.name} (${w.phone})` }))}
            />
            <Button type="primary" loading={resetting} onClick={handleResetPassword}>
              重置密码
            </Button>
          </Space>
        </div>
      </Card>
      <Divider />
      <Card title="管理员账号">
        <Text>管理员账号: <Text strong>admin</Text></Text>
      </Card>
    </div>
  );
}
