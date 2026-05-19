import { useState, useEffect } from 'react';
import { Row, Col, Card, Statistic, List, Tag, Typography } from 'antd';
import { CalendarOutlined, FileTextOutlined, BellOutlined } from '@ant-design/icons';
import { getMySchedules } from '../../services/schedule';
import { listMyRecords } from '../../services/record';
import { listReminders } from '../../services/reminder';
import type { MyScheduleItem } from '../../types/schedule';
import type { CareRecord } from '../../types/record';

const { Title } = Typography;

export default function WorkerDashboard() {
  const [todaySchedules, setTodaySchedules] = useState<MyScheduleItem[]>([]);
  const [recentRecords, setRecentRecords] = useState<CareRecord[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [recordTotal, setRecordTotal] = useState(0);

  useEffect(() => {
    const today = new Date().toISOString().slice(0, 10);
    Promise.all([
      getMySchedules(today),
      listMyRecords(1, 5),
      listReminders(1, 100),
    ]).then(([sRes, rRes, remRes]) => {
      if (sRes.code === 200) setTodaySchedules(sRes.data);
      if (rRes.code === 200) {
        setRecentRecords(rRes.data);
        setRecordTotal(rRes.total);
      }
      if (remRes.code === 200) {
        const unread = remRes.data.filter((r) => !r.is_read).length;
        setUnreadCount(unread);
      }
    }).catch(() => {});
  }, []);

  const activeSchedules = todaySchedules.filter(s => s.status === 'assigned' || s.status === 'in_progress');

  return (
    <div>
      <Title level={5}>今日概况</Title>
      <Row gutter={12}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="待服务" value={activeSchedules.length} prefix={<CalendarOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="护理记录" value={recordTotal} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="未读提醒" value={unreadCount} prefix={<BellOutlined />}
              valueStyle={unreadCount > 0 ? { color: '#cf1322' } : undefined} />
          </Card>
        </Col>
      </Row>

      <Title level={5} style={{ marginTop: 16 }}>今日排班</Title>
      <List
        dataSource={todaySchedules}
        locale={{ emptyText: '今日暂无排班' }}
        renderItem={(item) => (
          <Card size="small" style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>{item.patient_name}</strong>
                <div style={{ color: '#888', fontSize: 13 }}>
                  {item.start_time?.slice(11, 16)} - {item.end_time?.slice(11, 16)}
                </div>
              </div>
              <Tag color={item.status === 'completed' ? 'green' : item.status === 'in_progress' ? 'blue' : 'default'}>
                {item.status === 'assigned' ? '待服务' : item.status === 'in_progress' ? '服务中' : '已完成'}
              </Tag>
            </div>
          </Card>
        )}
      />
    </div>
  );
}
