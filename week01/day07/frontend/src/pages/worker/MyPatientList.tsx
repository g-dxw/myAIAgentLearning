import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Typography, Card, List, Tag, Spin, Empty, Progress, Space, App } from 'antd';
import { UserOutlined, MessageOutlined } from '@ant-design/icons';
import { getWorkerPatients } from '../../services/session';
import type { WorkerPatient } from '../../types/session';

const { Title, Text } = Typography;

export default function MyPatientList() {
  const [patients, setPatients] = useState<WorkerPatient[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { message: msg } = App.useApp();

  useEffect(() => {
    setLoading(true);
    getWorkerPatients()
      .then((res) => {
        setPatients(res.data || []);
      })
      .catch((err: Error) => msg.error(err.message || '加载失败'))
      .finally(() => setLoading(false));
  }, [msg]);

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;
  if (patients.length === 0) return <Empty description="暂无分配的病人" />;

  return (
    <div>
      <Title level={4}>
        <UserOutlined /> 我的病人
      </Title>
      <List
        dataSource={patients}
        renderItem={(patient) => (
          <Card
            hoverable
            style={{ marginBottom: 12 }}
            onClick={() => {
              if (patient.has_ongoing_session) {
                // Navigate to existing session
                navigate(`/worker/patients/${patient.id}/chat`);
              } else {
                // Create new session first, then navigate
                navigate(`/worker/patients/${patient.id}/chat`);
              }
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <Text strong style={{ fontSize: 16 }}>{patient.name}</Text>
                <Space style={{ marginLeft: 8 }}>
                  <Tag>{patient.gender}</Tag>
                  <Tag>{patient.age}岁</Tag>
                </Space>
                <br />
                <Text type="secondary">{patient.insurance_type}</Text>
              </div>
              <MessageOutlined style={{ fontSize: 20, color: '#1677ff' }} />
            </div>

            <div style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>信息完整度</Text>
                <Text style={{ fontSize: 12 }}>{patient.info_completeness}%</Text>
              </div>
              <Progress percent={patient.info_completeness} size="small" />
            </div>
          </Card>
        )}
      />
    </div>
  );
}
