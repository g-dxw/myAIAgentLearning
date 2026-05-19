import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Tag, App, Modal, Input } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { Patient } from '../../types/patient';
import { getApprovals, approvePatient, rejectPatient } from '../../services/patient';

const { TextArea } = Input;

export default function PatientApproval() {
  const [loading, setLoading] = useState(false);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const { message } = App.useApp();
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectId, setRejectId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [rejecting, setRejecting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getApprovals({ page, pageSize });
      setPatients(res.data);
      setTotal(res.total);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, message]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleApprove = async (id: number) => {
    try {
      await approvePatient(id);
      message.success('已通过');
      fetchData();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败');
    }
  };

  const handleReject = async () => {
    if (!rejectReason.trim() || rejectId === null) return;
    setRejecting(true);
    try {
      await rejectPatient(rejectId, rejectReason);
      message.success('已驳回');
      setRejectModalOpen(false);
      setRejectReason('');
      fetchData();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败');
    } finally {
      setRejecting(false);
    }
  };

  const columns: ColumnsType<Patient> = [
    { title: '姓名', dataIndex: 'name' },
    { title: '年龄', dataIndex: 'age' },
    { title: '性别', dataIndex: 'gender' },
    { title: '联系电话', dataIndex: 'phone' },
    { title: '地址', dataIndex: 'address', ellipsis: true },
    { title: '分配护工', dataIndex: 'assigned_worker_name', render: (v) => v || <Tag>未分配</Tag> },
    { title: '创建时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleDateString('zh-CN') },
    {
      title: '操作',
      render: (_, record) => (
        <div style={{ display: 'flex', gap: 8 }}>
          <Button type="primary" size="small" onClick={() => handleApprove(record.id)}>通过</Button>
          <Button danger size="small" onClick={() => { setRejectId(record.id); setRejectModalOpen(true); }}>驳回</Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <h2>病人审核</h2>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={patients}
        loading={loading}
        pagination={{ current: page, total, pageSize, onChange: setPage }}
      />
      <Modal
        title="驳回原因"
        open={rejectModalOpen}
        onOk={handleReject}
        onCancel={() => setRejectModalOpen(false)}
        confirmLoading={rejecting}
      >
        <TextArea rows={4} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="请填写驳回原因" />
      </Modal>
    </div>
  );
}
