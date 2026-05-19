import { useState, useEffect, useCallback } from 'react';
import {
  Typography, Button, Space, DatePicker, Segmented, Table, Modal,
  Form, Select, message, Spin, Empty, Popconfirm, App,
} from 'antd';
import { PlusOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import type { ColumnsType } from 'antd/es/table';
import { getScheduleView, createSchedule, cancelSchedule } from '../../services/schedule';
import { getWorkers } from '../../services/worker';
import { getPatients } from '../../services/patient';
import type { ScheduleViewData, ScheduleRow, ScheduleSlot } from '../../types/schedule';
import type { Worker } from '../../types/worker';
import type { Patient } from '../../types/patient';

const { Title, Text } = Typography;

const HOURS = Array.from({ length: 24 }, (_, i) => i);

export default function ScheduleView() {
  const [view, setView] = useState<'worker' | 'patient'>('worker');
  const [date, setDate] = useState<Dayjs>(dayjs());
  const [data, setData] = useState<ScheduleViewData | null>(null);
  const [loading, setLoading] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm] = Form.useForm();
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<{
    rowIndex: number; hour: number; scheduleId: number | null;
  } | null>(null);
  const { message: msg, modal } = App.useApp();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getScheduleView(date.format('YYYY-MM-DD'), view);
      setData(res.data);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [date, view, msg]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchWorkers = async () => {
    try {
      const res = await getWorkers({ pageSize: 100 });
      setWorkers(res.data);
    } catch { /* ignore */ }
  };

  const fetchPatients = async () => {
    try {
      const res = await getPatients({ pageSize: 100 });
      setPatients(res.data);
    } catch { /* ignore */ }
  };

  const handleCellClick = (rowIndex: number, slot: ScheduleSlot, hour: number) => {
    setSelectedSlot({ rowIndex, hour, scheduleId: slot.schedule_id });
    if (slot.schedule_id) {
      // Show info about existing schedule
      const row = data?.rows[rowIndex];
      const name = view === 'worker'
        ? (slot as { patient_name?: string | null }).patient_name
        : (slot as { worker_name?: string | null }).worker_name;
      modal.confirm({
        title: '排班信息',
        content: `${view === 'worker' ? '病人' : '护工'}: ${name || '未知'}\n时间: ${hour}:00-${hour + 1}:00`,
        okText: '取消排班',
        cancelText: '返回',
        okType: 'danger',
        onOk: async () => {
          try {
            await cancelSchedule(slot.schedule_id!);
            msg.success('排班已取消');
            fetchData();
          } catch (err: unknown) {
            msg.error(err instanceof Error ? err.message : '取消失败');
          }
        },
      });
    } else {
      // Open add modal
      fetchWorkers();
      fetchPatients();
      addForm.resetFields();
      if (view === 'worker' && data?.rows[rowIndex]) {
        addForm.setFieldsValue({ worker_id: data.rows[rowIndex].worker_id });
      }
      if (view === 'patient' && data?.rows[rowIndex]) {
        addForm.setFieldsValue({ patient_id: data.rows[rowIndex].patient_id });
      }
      setAddModalOpen(true);
    }
  };

  const handleAdd = async () => {
    try {
      const values = await addForm.validateFields();
      setSubmitting(true);

      const selectedDate = date.format('YYYY-MM-DD');
      const start_time = `${selectedDate}T${String(values.start_hour).padStart(2, '0')}:00:00`;
      const end_time = `${selectedDate}T${String(values.end_hour).padStart(2, '0')}:00:00`;

      await createSchedule({
        worker_id: values.worker_id,
        patient_id: values.patient_id,
        start_time,
        end_time,
      });
      msg.success('排班创建成功');
      setAddModalOpen(false);
      fetchData();
    } catch (err: unknown) {
      if (err instanceof Error) {
        msg.error(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const goToday = () => setDate(dayjs());
  const goPrev = () => setDate(date.subtract(1, 'day'));
  const goNext = () => setDate(date.add(1, 'day'));

  // Build table columns
  const columns: ColumnsType<ScheduleRow> = [
    {
      title: view === 'worker' ? '护工姓名' : '病人姓名',
      dataIndex: view === 'worker' ? 'worker_name' : 'patient_name',
      key: 'name',
      fixed: 'left' as const,
      width: 100,
      render: (text: string) => <Text strong>{text}</Text>,
    },
    ...HOURS.map((hour) => ({
      title: `${hour}:00`,
      key: `hour_${hour}`,
      width: 80,
      render: (_: unknown, _record: ScheduleRow, rowIndex: number) => {
        const slot = _record.slots[hour];
        const isOccupied = slot.schedule_id !== null;
        return (
          <div
            onClick={() => handleCellClick(rowIndex, slot, hour)}
            style={{
              minHeight: 40,
              cursor: 'pointer',
              background: isOccupied ? '#e6f4ff' : undefined,
              border: '1px solid #f0f0f0',
              borderRadius: 4,
              padding: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 12,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            {isOccupied ? (
              <Text style={{ fontSize: 12 }}>
                {view === 'worker'
                  ? (slot as { patient_name?: string | null }).patient_name
                  : (slot as { worker_name?: string | null }).worker_name}
              </Text>
            ) : (
              <PlusOutlined style={{ color: '#d9d9d9', fontSize: 14 }} />
            )}
          </div>
        );
      },
    })),
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={4} style={{ margin: 0 }}>排班管理</Title>
        <Space>
          <Segmented
            value={view}
            onChange={(val) => setView(val as 'worker' | 'patient')}
            options={[
              { value: 'worker', label: '护工视角' },
              { value: 'patient', label: '病人视角' },
            ]}
          />
        </Space>
      </div>

      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 16 }}>
        <Space>
          <Button icon={<LeftOutlined />} onClick={goPrev} />
          <Button onClick={goToday}>今天</Button>
          <Button icon={<RightOutlined />} onClick={goNext} />
        </Space>
        <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
        <Text strong>{date.format('YYYY-MM-DD')}</Text>
      </div>

      {loading ? (
        <Spin tip="加载中..." style={{ display: 'block', marginTop: 48 }} />
      ) : !data || data.rows.length === 0 ? (
        <Empty description="暂无数据" />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <Table
            dataSource={data.rows}
            columns={columns}
            rowKey={(row) =>
              String((row as { worker_id?: number; patient_id?: number }).worker_id
                ?? (row as { worker_id?: number; patient_id?: number }).patient_id ?? 0)
            }
            pagination={false}
            scroll={{ x: 80 * 24 + 100 }}
            bordered
            size="small"
          />
        </div>
      )}

      <Modal
        title="新增排班"
        open={addModalOpen}
        onCancel={() => setAddModalOpen(false)}
        onOk={handleAdd}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={addForm} layout="vertical">
          <Form.Item
            name="worker_id"
            label="护工"
            rules={[{ required: true, message: '请选择护工' }]}
          >
            <Select
              showSearch
              placeholder="搜索护工"
              options={workers.map((w) => ({ value: w.id, label: w.name }))}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item
            name="patient_id"
            label="病人"
            rules={[{ required: true, message: '请选择病人' }]}
          >
            <Select
              showSearch
              placeholder="搜索病人"
              options={patients.map((p) => ({ value: p.id, label: p.name }))}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Space style={{ width: '100%' }}>
            <Form.Item
              name="start_hour"
              label="开始时间"
              rules={[{ required: true, message: '请选择开始时间' }]}
              style={{ flex: 1 }}
            >
              <Select placeholder="时">
                {HOURS.slice(0, 23).map((h) => (
                  <Select.Option key={h} value={h}>{`${h}:00`}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item
              name="end_hour"
              label="结束时间"
              rules={[{ required: true, message: '请选择结束时间' }]}
              style={{ flex: 1 }}
            >
              <Select placeholder="时">
                {HOURS.slice(1).map((h) => (
                  <Select.Option key={h} value={h}>{`${h}:00`}</Select.Option>
                ))}
              </Select>
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  );
}
