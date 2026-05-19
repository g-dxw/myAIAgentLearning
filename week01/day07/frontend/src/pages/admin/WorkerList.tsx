import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, Input, Select, Space, Tag, App, Popconfirm } from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { Worker } from '../../types/worker';
import { getWorkers, updateWorkerStatus, deleteWorker, resetPassword } from '../../services/worker';

const statusMap: Record<string, { color: string; text: string }> = {
  active: { color: 'green', text: '在岗' },
  inactive: { color: 'red', text: '停用' },
  deleted: { color: 'default', text: '已删除' },
};

export default function WorkerList() {
  const [loading, setLoading] = useState(false);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [searchName, setSearchName] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('');
  const { message } = App.useApp();
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getWorkers({
        page,
        pageSize,
        name: searchName || undefined,
        status: filterStatus || undefined,
      });
      setWorkers(res.data);
      setTotal(res.total);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, searchName, filterStatus, message]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggleStatus = async (worker: Worker) => {
    const newStatus = worker.status === 'active' ? 'inactive' : 'active';
    try {
      await updateWorkerStatus(worker.id, newStatus);
      message.success('状态更新成功');
      fetchData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败';
      message.error(msg);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteWorker(id);
      message.success('删除成功');
      fetchData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '删除失败';
      message.error(msg);
    }
  };

  const handleResetPassword = async (id: number) => {
    try {
      const res = await resetPassword(id);
      message.success(`密码已重置为身份证后6位`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败';
      message.error(msg);
    }
  };

  const columns: ColumnsType<Worker> = [
    { title: '姓名', dataIndex: 'name', key: 'name' },
    { title: '手机号', dataIndex: 'phone', key: 'phone' },
    { title: '身份证号', dataIndex: 'id_card', key: 'id_card', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const s = statusMap[status] || { color: 'default', text: status };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => new Date(v).toLocaleDateString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => navigate(`/admin/workers/${record.id}`)}>
            编辑
          </Button>
          <Popconfirm
            title={record.status === 'active' ? '确认停用该护工？停用后将自动取消其未执行的排班' : '确认启用该护工？'}
            onConfirm={() => handleToggleStatus(record)}
          >
            <Button type="link" size="small" danger={record.status === 'active'}>
              {record.status === 'active' ? '停用' : '启用'}
            </Button>
          </Popconfirm>
          <Popconfirm title="确认重置密码为身份证后6位？" onConfirm={() => handleResetPassword(record.id)}>
            <Button type="link" size="small">重置密码</Button>
          </Popconfirm>
          <Popconfirm title="确认删除该护工？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Input
            placeholder="搜索姓名"
            prefix={<SearchOutlined />}
            value={searchName}
            onChange={(e) => { setSearchName(e.target.value); setPage(1); }}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            placeholder="状态筛选"
            value={filterStatus || undefined}
            onChange={(v) => { setFilterStatus(v || ''); setPage(1); }}
            allowClear
            style={{ width: 120 }}
            options={[
              { value: 'active', label: '在岗' },
              { value: 'inactive', label: '停用' },
            ]}
          />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/admin/workers/new')}>
          新增护工
        </Button>
      </div>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={workers}
        loading={loading}
        pagination={{ current: page, total, pageSize, onChange: setPage, showTotal: (t) => `共 ${t} 人` }}
      />
    </div>
  );
}
