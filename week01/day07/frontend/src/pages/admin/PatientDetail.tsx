import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Form, Input, InputNumber, Select, Button, Card, Typography, App, Spin,
  Table, Modal, Tag, Space, Tabs,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { PatientFormData, SpecialCondition, PatientVersion } from '../../types/patient';
import {
  getPatient, createPatient, updatePatient,
  getSpecialConditions, addSpecialCondition, getVersions,
} from '../../services/patient';
import { getWorkers } from '../../services/worker';

const { Title } = Typography;
const { TextArea } = Input;

const condTypeLabels: Record<string, string> = { '死亡': '死亡', '就医': '就医', '外出': '外出', '其他': '其他' };

export default function PatientDetail() {
  const { id } = useParams<{ id: string }>();
  const isEdit = id && id !== 'new';
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<PatientFormData>();
  const navigate = useNavigate();
  const { message } = App.useApp();

  const [conditions, setConditions] = useState<SpecialCondition[]>([]);
  const [versions, setVersions] = useState<PatientVersion[]>([]);
  const [workerOptions, setWorkerOptions] = useState<{ value: number; label: string }[]>([]);
  const [condModalOpen, setCondModalOpen] = useState(false);
  const [condType, setCondType] = useState('其他');
  const [condDesc, setCondDesc] = useState('');
  const [condSaving, setCondSaving] = useState(false);

  // 加载护工选项
  useEffect(() => {
    getWorkers({ pageSize: 1000 }).then(res => {
      setWorkerOptions(res.data.map(w => ({ value: w.id, label: w.name })));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (isEdit) {
      setLoading(true);
      const patientId = Number(id);
      Promise.all([
        getPatient(patientId),
        getSpecialConditions(patientId),
        getVersions(patientId),
      ]).then(([res, condsRes, versRes]) => {
        const p = res.data;
        form.setFieldsValue({
          name: p.name, age: p.age, gender: p.gender,
          insurance_type: p.insurance_type, phone: p.phone,
          address: p.address, emergency_contact: p.emergency_contact,
          assigned_worker_id: p.assigned_worker_id,
        });
        setConditions(condsRes.data);
        setVersions(versRes.data);
      }).catch((e) => {
        message.error(e instanceof Error ? e.message : '加载失败');
        navigate('/admin/patients');
      }).finally(() => setLoading(false));
    }
  }, [id, isEdit, form, navigate, message]);

  const onFinish = async (values: PatientFormData) => {
    setSubmitting(true);
    try {
      if (isEdit) {
        await updatePatient(Number(id), values);
        message.success('更新成功');
      } else {
        await createPatient(values);
        message.success('病人创建成功');
      }
      navigate('/admin/patients');
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddCondition = async () => {
    if (!condDesc.trim()) { message.warning('请填写描述'); return; }
    setCondSaving(true);
    try {
      await addSpecialCondition(Number(id), { type: condType, description: condDesc });
      message.success('添加成功');
      setCondModalOpen(false);
      setCondDesc('');
      const res = await getSpecialConditions(Number(id));
      setConditions(res.data);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '添加失败');
    } finally {
      setCondSaving(false);
    }
  };

  if (loading) {
    return <Spin style={{ display: 'block', marginTop: 100 }} size="large" />;
  }

  const patientForm = (
    <Form form={form} layout="vertical" onFinish={onFinish} style={{ maxWidth: 600 }}>
      <Form.Item name="name" label="姓名" rules={[{ required: true }]}>
        <Input placeholder="请输入姓名" />
      </Form.Item>
      <Space size={16}>
        <Form.Item name="age" label="年龄" rules={[{ required: true }]}>
          <InputNumber min={0} max={150} />
        </Form.Item>
        <Form.Item name="gender" label="性别" rules={[{ required: true }]}>
          <Select style={{ width: 100 }} options={[{ value: '男', label: '男' }, { value: '女', label: '女' }]} />
        </Form.Item>
      </Space>
      <Form.Item name="insurance_type" label="医保类型" rules={[{ required: true }]}>
        <Select options={[
          { value: '城镇职工', label: '城镇职工' }, { value: '城乡居民', label: '城乡居民' },
          { value: '自费', label: '自费' }, { value: '其他', label: '其他' },
        ]} />
      </Form.Item>
      <Form.Item name="phone" label="联系电话" rules={[{ required: true }]}>
        <Input placeholder="联系电话" />
      </Form.Item>
      <Form.Item name="address" label="居住地址" rules={[{ required: true }]}>
        <Input placeholder="居住地址" />
      </Form.Item>
      <Form.Item name="emergency_contact" label="紧急联系人">
        <Input placeholder="姓名+关系+电话" />
      </Form.Item>
      <Form.Item name="assigned_worker_id" label="分配护工">
        <Select
          placeholder="选择护工"
          allowClear
          showSearch
          filterOption={(input, option) => (option?.label as string || '').includes(input)}
          options={workerOptions}
        />
      </Form.Item>
      <Form.Item>
        <Button type="primary" htmlType="submit" loading={submitting} style={{ marginRight: 12 }}>
          {isEdit ? '保存修改' : '确认创建'}
        </Button>
        <Button onClick={() => navigate('/admin/patients')}>取消</Button>
      </Form.Item>
    </Form>
  );

  const conditionTab = (
    <div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCondModalOpen(true)} style={{ marginBottom: 16 }}>
        新增特殊情况
      </Button>
      <Table
        rowKey="id"
        dataSource={conditions}
        columns={[
          { title: '类型', dataIndex: 'type', render: (v: string) => <Tag>{condTypeLabels[v] || v}</Tag> },
          { title: '描述', dataIndex: 'description' },
          { title: '记录时间', dataIndex: 'recorded_at', render: (v: string) => new Date(v).toLocaleString('zh-CN') },
        ]}
        pagination={false}
      />
      <Modal
        title="新增特殊情况"
        open={condModalOpen}
        onCancel={() => setCondModalOpen(false)}
        onOk={handleAddCondition}
        confirmLoading={condSaving}
      >
        <Select
          value={condType}
          onChange={setCondType}
          style={{ width: '100%', marginBottom: 16 }}
          options={['死亡', '就医', '外出', '其他'].map(v => ({ value: v, label: v }))}
        />
        <TextArea rows={4} value={condDesc} onChange={(e) => setCondDesc(e.target.value)} placeholder="请描述具体情况" />
      </Modal>
    </div>
  );

  const versionTab = (
    <Table
      rowKey="id"
      dataSource={versions}
      columns={[
        { title: '更新方式', dataIndex: 'update_method', render: (v: string) => v === 'admin_manual' ? '管理员手动' : 'AI补充' },
        { title: '变更内容', dataIndex: 'changed_fields', ellipsis: true },
        { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString('zh-CN') },
      ]}
      pagination={false}
    />
  );

  return (
    <Card>
      <Title level={4}>{isEdit ? '病人详情' : '新增病人'}</Title>
      {isEdit ? (
        <Tabs
          items={[
            { key: 'info', label: '基本信息', children: patientForm },
            { key: 'conditions', label: '特殊情况', children: conditionTab },
            { key: 'versions', label: '变更历史', children: versionTab },
          ]}
        />
      ) : patientForm}
    </Card>
  );
}
