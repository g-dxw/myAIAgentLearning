import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { Typography, Card, Button, Input, Spin, Statistic, Space, App } from 'antd';
import { ClockCircleOutlined } from '@ant-design/icons';
import { getMyCheckins } from '../../services/checkin';
import { submitCheckin } from '../../services/checkin';
import type { CheckinRecord } from '../../types/checkin';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function CheckinForm() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [checkin, setCheckin] = useState<CheckinRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { message: msg } = App.useApp();

  const patientName = (location.state as { patientName?: string } | null)?.patientName;

  const fetchCheckin = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await getMyCheckins();
      const found = (res.data || []).find((c) => c.id === parseInt(id));
      if (found) {
        setCheckin(found);
        if (found.start_time) {
          const start = new Date(found.start_time).getTime();
          setElapsed(Math.floor((Date.now() - start) / 1000));
        }
      } else {
        msg.error('打卡记录不存在');
        navigate('/worker/schedules');
      }
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [id, navigate, msg]);

  useEffect(() => {
    fetchCheckin();
  }, [fetchCheckin]);

  // Timer
  useEffect(() => {
    if (checkin && checkin.status === 'started') {
      timerRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [checkin]);

  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const handleSubmit = async () => {
    if (!content.trim()) {
      msg.warning('请填写护理记录内容');
      return;
    }
    if (!id) return;
    setSubmitting(true);
    try {
      await submitCheckin(parseInt(id), { content });
      msg.success('护理记录已提交');
      navigate('/worker/schedules');
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;
  if (!checkin) return null;

  return (
    <div>
      <Title level={4}>服务中</Title>
      <Card>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Text strong style={{ fontSize: 18 }}>{patientName || '未知病人'}</Text>
          <div style={{ marginTop: 16 }}>
            <Statistic
              title="服务时长"
              value={formatTime(elapsed)}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ fontSize: 32, fontFamily: 'monospace' }}
            />
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Text strong>护理记录内容：</Text>
          <TextArea
            rows={6}
            placeholder="请详细描述本次护理服务的内容..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            style={{ marginTop: 8 }}
            maxLength={2000}
            showCount
          />
        </div>

        <Space style={{ width: '100%', justifyContent: 'center' }}>
          <Button
            type="primary"
            size="large"
            loading={submitting}
            onClick={handleSubmit}
            disabled={checkin.status !== 'started'}
          >
            提交护理记录
          </Button>
        </Space>
      </Card>
    </div>
  );
}
