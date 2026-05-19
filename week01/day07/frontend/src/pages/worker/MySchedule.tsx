import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Typography, Card, List, Tag, Spin, Empty, Button, Space, App } from 'antd';
import { RightOutlined, CalendarOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { getMySchedules } from '../../services/schedule';
import type { MyScheduleItem } from '../../types/schedule';

const { Title, Text } = Typography;

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  assigned: { color: 'blue', label: '待服务' },
  in_progress: { color: 'green', label: '服务中' },
  completed: { color: 'default', label: '已完成' },
  cancelled: { color: 'red', label: '已取消' },
};

export default function MySchedule() {
  const [schedules, setSchedules] = useState<MyScheduleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { message: msg } = App.useApp();

  const fetchSchedules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getMySchedules(dayjs().format('YYYY-MM-DD'));
      setSchedules(res.data || []);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [msg]);

  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  const groupByTime = () => {
    const groups: Record<string, MyScheduleItem[]> = {};
    schedules.forEach((s) => {
      const hour = dayjs(s.start_time).format('HH:mm');
      if (!groups[hour]) groups[hour] = [];
      groups[hour].push(s);
    });
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;
  if (schedules.length === 0) return <Empty description="今天暂无排班" />;

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>
        <CalendarOutlined /> 今日排班
      </Title>
      {groupByTime().map(([time, items]) => (
        <div key={time} style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 16, display: 'block', marginBottom: 8 }}>
            {time}
          </Text>
          <List
            dataSource={items}
            renderItem={(item) => {
              const statusInfo = STATUS_MAP[item.status] || { color: 'default', label: item.status };
              return (
                <Card
                  size="small"
                  style={{ marginBottom: 8, cursor: 'pointer' }}
                  onClick={() => navigate(`/worker/schedules/${item.id}`)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <Text strong>{item.patient_name}</Text>
                      <br />
                      <Text type="secondary">
                        {dayjs(item.start_time).format('HH:mm')} - {dayjs(item.end_time).format('HH:mm')}
                      </Text>
                    </div>
                    <Space>
                      <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
                      <RightOutlined style={{ color: '#999' }} />
                    </Space>
                  </div>
                </Card>
              );
            }}
          />
        </div>
      ))}
    </div>
  );
}
