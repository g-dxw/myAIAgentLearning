import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Form, Input, Button, Card, Typography, App, Spin } from 'antd';
import type { WorkerFormData } from '../../types/worker';
import { getWorker, createWorker, updateWorker } from '../../services/worker';

const { Title } = Typography;

export default function WorkerDetail() {
  const { id } = useParams<{ id: string }>();
  const isEdit = id && id !== 'new';
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<WorkerFormData>();
  const navigate = useNavigate();
  const { message } = App.useApp();

  useEffect(() => {
    if (isEdit) {
      setLoading(true);
      getWorker(Number(id))
        .then((res) => {
          form.setFieldsValue({
            name: res.data.name,
            phone: res.data.phone,
            id_card: res.data.id_card,
          });
        })
        .catch((e) => {
          message.error(e instanceof Error ? e.message : '加载失败');
          navigate('/admin/workers');
        })
        .finally(() => setLoading(false));
    }
  }, [id, isEdit, form, navigate, message]);

  const onFinish = async (values: WorkerFormData) => {
    setSubmitting(true);
    try {
      if (isEdit) {
        await updateWorker(Number(id), values);
        message.success('更新成功');
      } else {
        await createWorker(values);
        message.success('护工创建成功，初始密码为身份证后6位');
      }
      navigate('/admin/workers');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <Spin style={{ display: 'block', marginTop: 100 }} size="large" />;
  }

  return (
    <Card style={{ maxWidth: 500 }}>
      <Title level={4}>{isEdit ? '编辑护工' : '新增护工'}</Title>
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
          <Input placeholder="请输入姓名" />
        </Form.Item>
        <Form.Item
          name="phone"
          label="手机号"
          rules={[
            { required: true, message: '请输入手机号' },
            { pattern: /^\d{11}$/, message: '请输入正确的11位手机号' },
          ]}
        >
          <Input placeholder="请输入手机号（将作为登录账号）" disabled={isEdit} />
        </Form.Item>
        <Form.Item
          name="id_card"
          label="身份证号"
          rules={[
            { required: true, message: '请输入身份证号' },
            { min: 18, max: 18, message: '身份证号为18位' },
          ]}
        >
          <Input placeholder="请输入18位身份证号（后6位为初始密码）" disabled={isEdit} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting} style={{ marginRight: 12 }}>
            {isEdit ? '保存修改' : '确认创建'}
          </Button>
          <Button onClick={() => navigate('/admin/workers')}>取消</Button>
        </Form.Item>
      </Form>
    </Card>
  );
}
