import { useState, useEffect, useCallback } from 'react';
import {
  Typography, Table, Spin, Empty, Select, DatePicker, Space, Button,
  Modal, Input, Tag, App,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { listAbsenteeism, correctAbsenteeism } from '../../services/absenteeism';
import { getWorkers } from '../../services/worker';
import type { AbsenteeismRecord } from '../../types/absenteeism';
import type { Worker } from '../../types/worker';

const { Title } = Typography;
const { RangePicker } = DatePicker;

export default function AbsenteeismList() {
  const [records, setRecords] = useState<AbsenteeismRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [filterWorker, setFilterWorker] = useState<number | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [correctModalOpen, setCorrectModalOpen] = useState(false);
  const [correctTarget, setCorrectTarget] = useState<AbsenteeismRecord | null>(null);
  const [correctReason, setCorrectReason] = useState('');
  const [correcting, setCorrecting] = useState(false);
  const { message: msg } = App.useApp();

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAbsenteeism({
        page,
        pageSize: 20,
        worker_id: filterWorker,
        start_date: dateRange?.[0]?.format('YYYY-MM-DD') ?? undefined,
        end_date: dateRange?.[1]?.format('YYYY-MM-DD') ?? undefined,
      });
      setRecords(res.data);
      setTotal(res.total);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, filterWorker, dateRange, msg]);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  useEffect(() => {
    getWorkers({ pageSize: 100 }).then((res) => setWorkers(res.data)).catch(() => {});
  }, []);

  const handleCorrect = async () => {
    if (!correctTarget || !correctReason.trim()) return;
    setCorrecting(true);
    try {
      await correctAbsenteeism(correctTarget.id, correctReason);
      msg.success('旷工状态已纠正');
      setCorrectModalOpen(false);
      setCorrectReason('');
      fetchRecords();
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '纠正失败');
    } finally {
      setCorrecting(false);
    }
  };

  const columns: ColumnsType<AbsenteeismRecord> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '护工', dataIndex: 'worker_name', key: 'worker_name', width: 100 },
    { title: '病人', dataIndex: 'patient_name', key: 'patient_name', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => (
        <Tag color={status === 'absent' ? 'red' : 'green'}>
          {status === 'absent' ? '旷工' : '已纠正'}
        </Tag>
      ),
    },
    {
      title: '标记时间',
      dataIndex: 'auto_marked_at',
      key: 'auto_marked_at',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '',
    },
    {
      title: '纠正原因',
      dataIndex: 'correction_reason',
      key: 'correction_reason',
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: AbsenteeismRecord) => (
        record.status === 'absent' ? (
          <Button
            type="link"
            onClick={() => {
              setCorrectTarget(record);
              setCorrectReason('');
              setCorrectModalOpen(true);
            }}
          >
            纠正
          </Button>
        ) : null
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>出勤统计</Title>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="筛选护工"
          allowClear
          style={{ width: 180 }}
          value={filterWorker}
          onChange={(val) => { setFilterWorker(val); setPage(1); }}
          options={workers.map((w) => ({ value: w.id, label: w.name }))}
        />
        <RangePicker
          value={dateRange as [dayjs.Dayjs | null, dayjs.Dayjs | null]}
          onChange={(dates) => setDateRange(dates as [dayjs.Dayjs | null, dayjs.Dayjs | null] | null)}
        />
      </Space>

      {loading ? (
        <Spin style={{ display: 'block', marginTop: 48 }} />
      ) : records.length === 0 ? (
        <Empty description="暂无出勤记录" />
      ) : (
        <Table
          dataSource={records}
          columns={columns}
          rowKey="id"
          pagination={{
            current: page,
            pageSize: 20,
            total,
            onChange: setPage,
          }}
        />
      )}

      <Modal
        title="纠正旷工"
        open={correctModalOpen}
        onCancel={() => setCorrectModalOpen(false)}
        onOk={handleCorrect}
        confirmLoading={correcting}
        okText="确认纠正"
      >
        <p>护工: {correctTarget?.worker_name}</p>
        <p>病人: {correctTarget?.patient_name}</p>
        <p>标记时间: {correctTarget?.auto_marked_at ? new Date(correctTarget.auto_marked_at).toLocaleString('zh-CN') : ''}</p>
        <Input.TextArea
          placeholder="请输入纠正原因"
          value={correctReason}
          onChange={(e) => setCorrectReason(e.target.value)}
          rows={3}
        />
      </Modal>
    </div>
  );
}
