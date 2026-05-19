import { useState, useEffect, useCallback } from 'react';
import { Typography, Table, Spin, Empty, Select, Space, App } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listRecords } from '../../services/record';
import { getWorkers } from '../../services/worker';
import { getPatients } from '../../services/patient';
import type { CareRecord } from '../../types/record';
import type { Worker } from '../../types/worker';
import type { Patient } from '../../types/patient';

const { Title } = Typography;

export default function RecordList() {
  const [records, setRecords] = useState<CareRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [filterWorker, setFilterWorker] = useState<number | undefined>();
  const [filterPatient, setFilterPatient] = useState<number | undefined>();
  const { message: msg } = App.useApp();

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listRecords({
        page,
        pageSize: 20,
        worker_id: filterWorker,
        patient_id: filterPatient,
      });
      setRecords(res.data);
      setTotal(res.total);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, filterWorker, filterPatient, msg]);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  useEffect(() => {
    getWorkers({ pageSize: 100 }).then((res) => setWorkers(res.data)).catch(() => {});
    getPatients({ pageSize: 100 }).then((res) => setPatients(res.data)).catch(() => {});
  }, []);

  const columns: ColumnsType<CareRecord> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '病人', dataIndex: 'patient_name', key: 'patient_name', width: 100 },
    { title: '护工', dataIndex: 'worker_name', key: 'worker_name', width: 100 },
    {
      title: '护理内容',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
    },
    {
      title: '记录时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '',
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>护理记录</Title>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="筛选护工"
          allowClear
          style={{ width: 180 }}
          value={filterWorker}
          onChange={(val) => { setFilterWorker(val); setPage(1); }}
          options={workers.map((w) => ({ value: w.id, label: w.name }))}
        />
        <Select
          placeholder="筛选病人"
          allowClear
          style={{ width: 180 }}
          value={filterPatient}
          onChange={(val) => { setFilterPatient(val); setPage(1); }}
          options={patients.map((p) => ({ value: p.id, label: p.name }))}
        />
      </Space>

      {loading ? (
        <Spin style={{ display: 'block', marginTop: 48 }} />
      ) : records.length === 0 ? (
        <Empty description="暂无护理记录" />
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
    </div>
  );
}
