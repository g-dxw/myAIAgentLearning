import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, Input, Select, Space, Tag, App } from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { Patient } from '../../types/patient';
import { getPatients } from '../../services/patient';

const statusMap: Record<string, { color: string; text: string }> = {
  active: { color: 'green', text: '已激活' },
  pending: { color: 'orange', text: '待审核' },
};

export default function PatientList() {
  const [loading, setLoading] = useState(false);
  const [patients, setPatients] = useState<Patient[]>([]);
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
      const res = await getPatients({
        page, pageSize,
        name: searchName || undefined,
        status: filterStatus || undefined,
      });
      setPatients(res.data);
      setTotal(res.total);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, searchName, filterStatus, message]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns: ColumnsType<Patient> = [
    { title: '姓名', dataIndex: 'name', key: 'name' },
    { title: '年龄', dataIndex: 'age', key: 'age', width: 60 },
    { title: '性别', dataIndex: 'gender', key: 'gender', width: 60 },
    { title: '联系电话', dataIndex: 'phone', key: 'phone' },
    { title: '地址', dataIndex: 'address', key: 'address', ellipsis: true },
    {
      title: '负责护工',
      dataIndex: 'assigned_worker_name',
      key: 'worker',
      render: (v) => v || <Tag>未分配</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (s: string) => {
        const st = statusMap[s] || { color: 'default', text: s };
        return <Tag color={st.color}>{st.text}</Tag>;
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
        <Button type="link" size="small" onClick={() => navigate(`/admin/patients/${record.id}`)}>
          查看/编辑
        </Button>
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
              { value: 'active', label: '已激活' },
              { value: 'pending', label: '待审核' },
            ]}
          />
        </Space>
        <Space>
          <Button onClick={() => navigate('/admin/patients/approvals')}>审核列表</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/admin/patients/new')}>
            新增病人
          </Button>
        </Space>
      </div>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={patients}
        loading={loading}
        pagination={{ current: page, total, pageSize, onChange: setPage, showTotal: (t) => `共 ${t} 人` }}
      />
    </div>
  );
}
