import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Typography, Card, Form, Select, DatePicker, TimePicker, Input, Button, App,
} from 'antd';
import dayjs from 'dayjs';
import { getWorkerPatients } from '../../services/session';
import { makeupCheckin } from '../../services/checkin';
import type { WorkerPatient } from '../../types/session';

const { Title } = Typography;
const { TextArea } = Input;

export default function MakeupCheckin() {
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [patients, setPatients] = useState<WorkerPatient[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { message: msg } = App.useApp();

  useEffect(() => {
    setLoading(true);
    getWorkerPatients()
      .then((res) => setPatients(res.data || []))
      .catch(() => msg.error('加载病人列表失败'))
      .finally(() => setLoading(false));
  }, [msg]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const dateStr = values.date.format('YYYY-MM-DD');
      const startTime = values.start_time.format('HH:mm:ss');
      const endTime = values.end_time.format('HH:mm:ss');

      await makeupCheckin({
        patient_id: values.patient_id,
        start_time: `${dateStr}T${startTime}`,
        end_time: `${dateStr}T${endTime}`,
        content: values.content,
      });
      msg.success('补卡成功');
      navigate('/worker/schedules');
    } catch (err: unknown) {
      if (err instanceof Error) {
        msg.error(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <Title level={4}>补卡</Title>
      <Card>
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="patient_id"
            label="病人"
            rules={[{ required: true, message: '请选择病人' }]}
          >
            <Select
              placeholder="选择病人"
              loading={loading}
              options={patients.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>

          <Form.Item
            name="date"
            label="服务日期"
            rules={[{ required: true, message: '请选择日期' }]}
          >
            <DatePicker style={{ width: '100%' }} disabledDate={(d) => d.isAfter(dayjs())} />
          </Form.Item>

          <Form.Item
            name="start_time"
            label="开始时间"
            rules={[{ required: true, message: '请选择开始时间' }]}
          >
            <TimePicker style={{ width: '100%' }} format="HH:mm" />
          </Form.Item>

          <Form.Item
            name="end_time"
            label="结束时间"
            rules={[
              { required: true, message: '请选择结束时间' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || !getFieldValue('start_time')) return Promise.resolve();
                  if (value.isAfter(getFieldValue('start_time'))) return Promise.resolve();
                  return Promise.reject(new Error('结束时间必须晚于开始时间'));
                },
              }),
            ]}
          >
            <TimePicker style={{ width: '100%' }} format="HH:mm" />
          </Form.Item>

          <Form.Item
            name="content"
            label="护理记录"
            rules={[{ required: true, message: '请填写护理记录' }]}
          >
            <TextArea rows={6} maxLength={2000} showCount placeholder="请描述护理服务内容..." />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting} block size="large">
              提交补卡
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
