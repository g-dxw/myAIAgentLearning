import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Typography, Card, Input, Button, Spin, Empty, Modal, Form, Space, App,
} from 'antd';
import { SendOutlined, ArrowLeftOutlined, FileTextOutlined } from '@ant-design/icons';
import {
  createSession, getSession, addMessage, extractInfo, confirmSubmit,
} from '../../services/session';
import type { ChatMessage, ExtractResult } from '../../types/session';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function SessionChat() {
  const { id: patientId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractResult, setExtractResult] = useState<ExtractResult>({});
  const [editableResult, setEditableResult] = useState<ExtractResult>({});
  const [confirming, setConfirming] = useState(false);
  const [patientName, setPatientName] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { message: msg, modal } = App.useApp();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const initSession = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    try {
      const res = await createSession(parseInt(patientId));
      const sid = res.data.id;
      setSessionId(sid);
      setPatientName(res.data.patient_name || '');

      const detailRes = await getSession(sid);
      setMessages(detailRes.data.messages || []);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '创建对话失败');
      navigate('/worker/patients');
    } finally {
      setLoading(false);
    }
  }, [patientId, navigate, msg]);

  useEffect(() => {
    initSession();
  }, [initSession]);

  const handleSend = async () => {
    if (!input.trim() || !sessionId) return;
    setSending(true);
    try {
      const res = await addMessage(sessionId, input);
      setMessages((prev) => [...prev, res.data.user_message, res.data.ai_message]);
      setInput('');
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '发送失败');
    } finally {
      setSending(false);
    }
  };

  const handleExtract = async () => {
    if (!sessionId) return;
    setExtracting(true);
    try {
      const res = await extractInfo(sessionId);
      setExtractResult(res.data);
      setEditableResult({ ...res.data });
      setExtractModalOpen(true);
    } catch (err: unknown) {
      msg.error(err instanceof Error ? err.message : '提取失败');
    } finally {
      setExtracting(false);
    }
  };

  const handleConfirm = () => {
    modal.confirm({
      title: '确认提交',
      content: '确认将以上信息提交到病人档案？提交后可由管理员修改。',
      onOk: async () => {
        if (!sessionId) return;
        setConfirming(true);
        try {
          const res = await confirmSubmit(sessionId, editableResult);
          const data = res.data as { updated: boolean; message?: string; completeness?: { is_complete: boolean } };
          if (data.updated) {
            if (data.completeness?.is_complete) {
              msg.success('信息已提交，档案已更新');
            } else {
              msg.success('信息已提交，部分字段可能还不完整，可继续补充');
            }
          } else {
            msg.info(data.message || '没有新的信息需要更新');
          }
          setExtractModalOpen(false);
        } catch (err: unknown) {
          msg.error(err instanceof Error ? err.message : '提交失败');
        } finally {
          setConfirming(false);
        }
      },
    });
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 48 }} />;
  if (!sessionId) return <Empty description="对话初始化失败" />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 180px)' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '12px 0', borderBottom: '1px solid #f0f0f0',
      }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/worker/patients')} />
        <Title level={5} style={{ margin: 0, flex: 1 }}>{patientName}</Title>
        <Button
          icon={<FileTextOutlined />}
          loading={extracting}
          onClick={handleExtract}
        >
          查看提取结果
        </Button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0' }}>
        {messages.map((m) => (
          <div
            key={m.id}
            style={{
              display: 'flex',
              justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
              marginBottom: 12,
            }}
          >
            <div
              style={{
                maxWidth: '80%',
                padding: '10px 14px',
                borderRadius: 12,
                background: m.role === 'user' ? '#1677ff' : '#f0f0f0',
                color: m.role === 'user' ? '#fff' : '#000',
              }}
            >
              <Text style={{ whiteSpace: 'pre-wrap', color: 'inherit' }}>
                {m.content}
              </Text>
              <div style={{ fontSize: 11, marginTop: 4, opacity: 0.6 }}>
                {m.role === 'user' ? '我' : 'AI'} - {new Date(m.created_at).toLocaleTimeString('zh-CN')}
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 8, padding: '12px 0', borderTop: '1px solid #f0f0f0' }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入消息..."
          autoSize={{ minRows: 1, maxRows: 4 }}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          loading={sending}
          onClick={handleSend}
        >
          发送
        </Button>
      </div>

      {/* Extract Result Modal */}
      <Modal
        title="AI 提取结果"
        open={extractModalOpen}
        onCancel={() => setExtractModalOpen(false)}
        footer={null}
        width={600}
        destroyOnClose
      >
        <Form layout="vertical">
          <Form.Item label="监护人情况">
            <TextArea
              rows={3}
              value={editableResult.guardian_info || ''}
              onChange={(e) => setEditableResult((prev) => ({ ...prev, guardian_info: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="基础疾病信息">
            <TextArea
              rows={3}
              value={editableResult.disease_info || ''}
              onChange={(e) => setEditableResult((prev) => ({ ...prev, disease_info: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="照护要求">
            <TextArea
              rows={3}
              value={editableResult.care_requirements || ''}
              onChange={(e) => setEditableResult((prev) => ({ ...prev, care_requirements: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="性格特点">
            <TextArea
              rows={3}
              value={editableResult.personality || ''}
              onChange={(e) => setEditableResult((prev) => ({ ...prev, personality: e.target.value }))}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" loading={confirming} onClick={handleConfirm} block>
              确认提交
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
