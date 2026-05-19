import { useState, useEffect, useCallback } from 'react';
import { Typography, List, Card, Spin, Empty, Tag, App } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import { listMyRecords } from '../../services/record';
import type { CareRecord } from '../../types/record';

const { Title, Text } = Typography;

export default function MyRecordList() {
  const [records, setRecords] = useState<CareRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const { message: msg } = App.useApp();

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listMyRecords(page);
      setRecords(res.data);
      setTotal(res.total);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, msg]);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;

  return (
    <div>
      <Title level={4}>
        <FileTextOutlined /> 我的护理记录
      </Title>
      {records.length === 0 ? (
        <Empty description="暂无护理记录" />
      ) : (
        <>
          <List
            dataSource={records}
            renderItem={(record) => (
              <Card size="small" style={{ marginBottom: 12 }}>
                <div style={{ marginBottom: 8 }}>
                  <Tag color="blue">{record.patient_name}</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.created_at ? new Date(record.created_at).toLocaleString('zh-CN') : ''}
                  </Text>
                </div>
                <Text>{record.content}</Text>
              </Card>
            )}
          />
          {total > 20 && (
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Text type="secondary">
                共 {total} 条记录
              </Text>
            </div>
          )}
        </>
      )}
    </div>
  );
}
