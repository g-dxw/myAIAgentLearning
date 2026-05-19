import { useState, useEffect, useCallback } from 'react';
import { Typography, List, Card, Tag, Spin, Empty, Button, Space, App } from 'antd';
import { BellOutlined, CheckOutlined } from '@ant-design/icons';
import { listReminders, markRead } from '../../services/reminder';
import type { Reminder } from '../../types/reminder';

const { Title, Text } = Typography;

export default function ReminderList() {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [, setTotal] = useState(0);
  const { message: msg } = App.useApp();

  const fetchReminders = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listReminders(page);
      setReminders(res.data);
      setTotal(res.total);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, msg]);

  useEffect(() => {
    fetchReminders();
  }, [fetchReminders]);

  const handleMarkRead = async (id: number) => {
    try {
      await markRead(id);
      setReminders((prev) =>
        prev.map((r) => (r.id === id ? { ...r, is_read: true } : r))
      );
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '操作失败');
    }
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;

  return (
    <div>
      <Title level={4}>
        <BellOutlined /> 提醒列表
      </Title>
      {reminders.length === 0 ? (
        <Empty description="暂无提醒" />
      ) : (
        <List
          dataSource={reminders}
          renderItem={(reminder) => (
            <Card
              size="small"
              style={{
                marginBottom: 12,
                background: reminder.is_read ? '#fff' : '#f6ffed',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <Space style={{ marginBottom: 4 }}>
                    <Tag color={reminder.is_read ? 'default' : 'green'}>
                      {reminder.is_read ? '已读' : '未读'}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {reminder.created_at ? new Date(reminder.created_at).toLocaleString('zh-CN') : ''}
                    </Text>
                  </Space>
                  <br />
                  <Text>{reminder.message}</Text>
                </div>
                {!reminder.is_read && (
                  <Button
                    type="link"
                    icon={<CheckOutlined />}
                    onClick={() => handleMarkRead(reminder.id)}
                  >
                    标记已读
                  </Button>
                )}
              </div>
            </Card>
          )}
        />
      )}
    </div>
  );
}
