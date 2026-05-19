import { useState, useEffect } from 'react';
import { Row, Col, Card, Statistic, Typography } from 'antd';
import { TeamOutlined, UserOutlined, ScheduleOutlined, WarningOutlined } from '@ant-design/icons';
import { getWorkers } from '../../services/worker';
import { getPatients } from '../../services/patient';
import { getScheduleView } from '../../services/schedule';

const { Title } = Typography;

export default function AdminDashboard() {
  const [workerCount, setWorkerCount] = useState(0);
  const [patientCount, setPatientCount] = useState(0);
  const [todaySchedules, setTodaySchedules] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    const today = new Date().toISOString().slice(0, 10);
    Promise.all([
      getWorkers({ pageSize: 1, status: 'active' }),
      getPatients({ pageSize: 1, status: 'active' }),
      getPatients({ pageSize: 1, status: 'pending' }),
      getScheduleView({ date: today, view: 'worker' }),
    ]).then(([wRes, pRes, pendRes, sRes]) => {
      setWorkerCount(wRes.total);
      setPatientCount(pRes.total);
      setPendingCount(pendRes.total);
      const totalSlots = sRes.data.rows.reduce(
        (sum: number, row: { slots: Array<{ schedule_id: number | null }> }) =>
          sum + row.slots.filter((s) => s.schedule_id).length, 0
      );
      setTodaySchedules(totalSlots);
    }).catch(() => {});
  }, []);

  return (
    <div>
      <Title level={4}>工作台</Title>
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="在岗护工" value={workerCount} prefix={<TeamOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="在管病人" value={patientCount} prefix={<UserOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="今日排班(时段)" value={todaySchedules} prefix={<ScheduleOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="待审核病人" value={pendingCount} prefix={<WarningOutlined />}
              valueStyle={pendingCount > 0 ? { color: '#cf1322' } : undefined} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
