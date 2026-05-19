import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Typography, Card, Tag, Button, Spin, Empty, Descriptions, Space, App,
} from 'antd';
import dayjs from 'dayjs';
import { getMySchedules } from '../../services/schedule';
import { startCheckin } from '../../services/checkin';
import type { MyScheduleItem } from '../../types/schedule';

const { Title, Text } = Typography;

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  assigned: { color: 'blue', label: '待服务' },
  in_progress: { color: 'green', label: '服务中' },
  completed: { color: 'default', label: '已完成' },
  cancelled: { color: 'red', label: '已取消' },
};

export default function ScheduleDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [schedule, setSchedule] = useState<MyScheduleItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const { message: msg } = App.useApp();

  const fetchDetail = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await getMySchedules(dayjs().format('YYYY-MM-DD'));
      const found = (res.data || []).find((s) => s.id === parseInt(id));
      if (!found) {
        msg.error('排班不存在');
        navigate('/worker/schedules');
        return;
      }
      setSchedule(found);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [id, navigate, msg]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const handleStartService = async () => {
    if (!schedule) return;
    setStarting(true);
    try {
      const res = await startCheckin({ schedule_id: schedule.id });
      msg.success('开始服务');
      navigate(`/worker/checkin/${res.data.id}`, {
        state: { scheduleId: schedule.id, patientName: schedule.patient_name },
      });
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setStarting(false);
    }
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;
  if (!schedule) return <Empty description="排班不存在" />;

  const statusInfo = STATUS_MAP[schedule.status] || { color: 'default', label: schedule.status };

  return (
    <div>
      <Title level={4}>排班详情</Title>
      <Card>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="病人">
            <Text strong>{schedule.patient_name}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="服务时间">
            {dayjs(schedule.start_time).format('HH:mm')} - {dayjs(schedule.end_time).format('HH:mm')}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
          </Descriptions.Item>
        </Descriptions>

        <Space style={{ marginTop: 24, width: '100%', justifyContent: 'center' }}>
          {schedule.status === 'assigned' && (
            <Button
              type="primary"
              size="large"
              loading={starting}
              onClick={handleStartService}
            >
              开始服务
            </Button>
          )}
          {schedule.status === 'in_progress' && (
            <Text type="warning">服务进行中，请在服务结束后提交护理记录</Text>
          )}
          {schedule.status === 'completed' && (
            <Text type="secondary">服务已结束</Text>
          )}
        </Space>
      </Card>
    </div>
  );
}
