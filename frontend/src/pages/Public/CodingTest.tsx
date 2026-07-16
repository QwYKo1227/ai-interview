import React, { useEffect, useMemo, useState, useRef } from 'react';
import { Button, Card, Form, Input, Space, Spin, Tag, Typography, message, Table, Radio, Checkbox, Modal, Progress, Badge, Tooltip, Divider } from 'antd';
import { useParams } from 'react-router-dom';
import { PlayCircleOutlined, SendOutlined, ClockCircleOutlined, CheckCircleOutlined, FlagOutlined, FlagFilled, UserOutlined, MailOutlined, LoginOutlined, TrophyOutlined, CloseCircleOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import CodeEditor from '../../components/CodeEditor';

const { Title, Paragraph, Text } = Typography;
const { TextArea } = Input;

const testTypeLabels: Record<string, { label: string; color: string }> = {
  algorithm: { label: '算法笔试', color: 'blue' },
  choice: { label: '选择题', color: 'green' },
  essay: { label: '简答题', color: 'orange' },
};

const difficultyLabels: Record<string, string> = {
  easy: '简单',
  intermediate: '中等',
  hard: '困难',
};

const PublicCodingTest: React.FC = () => {
  const { token } = useParams();
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [test, setTest] = useState<any>(null);
  const [code, setCode] = useState('');
  const [runResult, setRunResult] = useState<any>(null);
  const [submission, setSubmission] = useState<any>(null);
  const [form] = Form.useForm();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [markedQuestions, setMarkedQuestions] = useState<Set<string>>(new Set());
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [started, setStarted] = useState(false);
  const [candidateInfo, setCandidateInfo] = useState<{ name: string; email: string } | null>(null);
  const [showResult, setShowResult] = useState(false);
  const questionRefs = useRef<Record<string, HTMLElement | null>>({});

  const getCandidateKey = (name: string, email: string) => `${token}:${name}:${email}`;
  
  const getStorageKeys = (name: string, email: string) => {
    const key = getCandidateKey(name, email);
    return {
      code: `codingtest:${key}:code`,
      answers: `codingtest:${key}:answers`,
      marked: `codingtest:${key}:marked`,
      startTime: `codingtest:${key}:startTime`,
    };
  };

  const fetchTest = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await request.get(`/public/coding-tests/${token}`);
      setTest(res);
    } catch (e) {
      message.error('笔试链接无效或已关闭');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTest();
  }, [token]);

  useEffect(() => {
    if (!candidateInfo || !test) return;
    
    const keys = getStorageKeys(candidateInfo.name, candidateInfo.email);
    
    if (test.test_type === 'algorithm') {
      const saved = localStorage.getItem(keys.code);
      setCode(saved || test.starter_code || '');
    } else {
      const savedAnswers = localStorage.getItem(keys.answers);
      if (savedAnswers) {
        setAnswers(JSON.parse(savedAnswers));
      }
      const savedMarked = localStorage.getItem(keys.marked);
      if (savedMarked) {
        setMarkedQuestions(new Set(JSON.parse(savedMarked)));
      }
    }
    
    const savedStartTime = localStorage.getItem(keys.startTime);
    const duration = test.duration_minutes ? test.duration_minutes * 60 : null;
    
    if (savedStartTime && duration) {
      const elapsed = Math.floor((Date.now() - parseInt(savedStartTime)) / 1000);
      const remaining = Math.max(0, duration - elapsed);
      setTimeLeft(remaining);
      
      if (remaining === 0) {
        message.warning('考试时间已结束');
      }
    } else if (duration) {
      const now = Date.now();
      localStorage.setItem(keys.startTime, now.toString());
      setTimeLeft(duration);
    }
  }, [candidateInfo, test]);

  useEffect(() => {
    if (!candidateInfo || !started || test?.test_type !== 'algorithm') return;
    const keys = getStorageKeys(candidateInfo.name, candidateInfo.email);
    localStorage.setItem(keys.code, code || '');
  }, [candidateInfo, started, code, test?.test_type]);

  useEffect(() => {
    if (!candidateInfo || !started || test?.test_type === 'algorithm') return;
    const keys = getStorageKeys(candidateInfo.name, candidateInfo.email);
    localStorage.setItem(keys.answers, JSON.stringify(answers));
  }, [candidateInfo, started, answers, test?.test_type]);

  useEffect(() => {
    if (!candidateInfo || !started || test?.test_type === 'algorithm') return;
    const keys = getStorageKeys(candidateInfo.name, candidateInfo.email);
    localStorage.setItem(keys.marked, JSON.stringify([...markedQuestions]));
  }, [candidateInfo, started, markedQuestions, test?.test_type]);

  useEffect(() => {
    if (timeLeft === null || timeLeft <= 0) return;
    const timer = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(timer);
          if (prev === 1) {
            message.warning('时间到，正在自动提交...');
            handleSubmit(true);
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [timeLeft]);

  const handleStart = async () => {
    try {
      const values = await form.validateFields();
      setCandidateInfo({ name: values.candidate_name, email: values.candidate_email });
      setStarted(true);
    } catch (e) {
      // validation failed
    }
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const handleRun = async () => {
    if (!token) return;
    if (!code.trim()) {
      message.error('请先填写代码');
      return;
    }
    setRunning(true);
    try {
      const res = await request.post(`/public/coding-tests/${token}/run`, {
        code,
        language: test?.language || 'javascript',
      });
      setRunResult(res);
      message.success(res.passed ? '全部用例通过' : '部分用例未通过');
    } catch (e) {
      message.error('运行失败');
    } finally {
      setRunning(false);
    }
  };

  const handleSubmit = async (forceSubmit = false) => {
    if (!token || !candidateInfo) return;
    
    const testType = test?.test_type || 'algorithm';
    
    if (testType === 'algorithm' && !code.trim()) {
      message.error('请先填写代码');
      return;
    }
    
    if ((testType === 'choice' || testType === 'essay') && !forceSubmit) {
      const questions = test?.questions || [];
      const unanswered = questions.filter((q: any) => !answers[q.id] || answers[q.id].trim() === '');
      
      if (unanswered.length > 0) {
        message.error(`还有 ${unanswered.length} 道题目未作答，请完成所有题目后再提交`);
        return;
      }
    }
    
    try {
      setSubmitting(true);
      
      let endpoint = `/public/coding-tests/${token}/submit`;
      let payload: any = {
        candidate_name: candidateInfo.name,
        candidate_email: candidateInfo.email,
      };
      
      if (testType === 'algorithm') {
        payload.code = code;
        payload.language = test?.language || 'javascript';
      } else if (testType === 'choice') {
        endpoint = `/public/coding-tests/${token}/submit-choice`;
        payload.answers = Object.entries(answers).map(([questionId, answer]) => ({
          question_id: questionId,
          answer,
        }));
      } else if (testType === 'essay') {
        endpoint = `/public/coding-tests/${token}/submit-essay`;
        payload.answers = Object.entries(answers).map(([questionId, answer]) => ({
          question_id: questionId,
          answer,
        }));
      }
      
      const res = await request.post(endpoint, payload);
      setSubmission(res);
      setShowResult(true);
      
      if (candidateInfo) {
        const keys = getStorageKeys(candidateInfo.name, candidateInfo.email);
        localStorage.removeItem(keys.code);
        localStorage.removeItem(keys.answers);
        localStorage.removeItem(keys.marked);
        localStorage.removeItem(keys.startTime);
      }
      setTimeLeft(0);
    } catch (e) {
      if ((e as any)?.errorFields) return;
      message.error('提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmitClick = () => {
    const questions = test?.questions || [];
    const unanswered = questions.filter((q: any) => !answers[q.id] || answers[q.id].trim() === '');
    const answered = questions.length - unanswered.length;
    
    if (unanswered.length === 0) {
      handleSubmit(true);
      return;
    }
    
    Modal.confirm({
      title: '确认提交',
      icon: <SendOutlined />,
      content: (
        <div>
          <Paragraph>您已完成 <Text strong>{answered}</Text> / <Text strong>{questions.length}</Text> 道题目</Paragraph>
          <Paragraph type="warning">注意：还有 {unanswered.length} 道题目未作答</Paragraph>
          {markedQuestions.size > 0 && (
            <Paragraph type="warning">注意：有 {markedQuestions.size} 道题目已标记</Paragraph>
          )}
          <Paragraph>确定要提交吗？</Paragraph>
        </div>
      ),
      okText: '确认提交',
      cancelText: '继续作答',
      onOk: () => handleSubmit(true),
    });
  };

  const handleAnswerChange = (questionId: string, answer: string) => {
    setAnswers((prev) => ({ ...prev, [questionId]: answer }));
  };

  const toggleMark = (questionId: string) => {
    setMarkedQuestions((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(questionId)) {
        newSet.delete(questionId);
      } else {
        newSet.add(questionId);
      }
      return newSet;
    });
  };

  const scrollToQuestion = (questionId: string) => {
    const el = questionRefs.current[questionId];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  const resultRows = useMemo(() => {
    const results = runResult?.results || submission?.run_result?.results || [];
    return results.map((r: any) => ({ ...r, key: r.index }));
  }, [runResult, submission]);

  const answerStats = useMemo(() => {
    const questions = test?.questions || [];
    const answered = questions.filter((q: any) => answers[q.id] && answers[q.id].trim() !== '').length;
    const marked = markedQuestions.size;
    return { total: questions.length, answered, marked };
  }, [test?.questions, answers, markedQuestions]);

  if (loading && !test) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!test) return null;

  const testType = test.test_type || 'algorithm';
  const typeInfo = testTypeLabels[testType] || { label: '笔试', color: 'default' };

  if (showResult && submission) {
    return (
      <div style={{ maxWidth: 600, margin: '0 auto', padding: '24px 16px' }}>
        <Card style={{ borderRadius: 16, textAlign: 'center' }}>
          <div style={{ marginBottom: 32 }}>
            {submission.passed ? (
              <TrophyOutlined style={{ fontSize: 80, color: '#52c41a' }} />
            ) : (
              <CloseCircleOutlined style={{ fontSize: 80, color: '#ff4d4f' }} />
            )}
          </div>
          
          <Title level={2} style={{ marginBottom: 8 }}>
            {submission.passed ? '恭喜通过！' : '未通过'}
          </Title>
          
          <Space style={{ marginBottom: 24 }}>
            <Tag color={typeInfo.color} style={{ border: 'none' }}>{typeInfo.label}</Tag>
            <Tag style={{ border: 'none' }}>{test.title}</Tag>
          </Space>
          
          <Card style={{ background: '#f5f5f5', borderRadius: 12, marginBottom: 24 }}>
            <Space direction="vertical" size={8}>
              <div>
                <Text type="secondary">得分：</Text>
                <Text strong style={{ fontSize: 24, color: submission.passed ? '#52c41a' : '#ff4d4f' }}>
                  {submission.score}
                </Text>
              </div>
              {candidateInfo && (
                <div>
                  <Text type="secondary">考生：</Text>
                  <Text>{candidateInfo.name} ({candidateInfo.email})</Text>
                </div>
              )}
            </Space>
          </Card>
          
          {testType === 'algorithm' && submission.run_result?.results && (
            <Card size="small" style={{ borderRadius: 12, textAlign: 'left' }} title="测试用例结果">
              <Table
                dataSource={submission.run_result.results.map((r: any, i: number) => ({ ...r, key: i }))}
                pagination={false}
                size="small"
                columns={[
                  { title: '#', dataIndex: 'index', width: 50, render: (_: any, __: any, i: number) => i + 1 },
                  {
                    title: '状态',
                    dataIndex: 'ok',
                    width: 80,
                    render: (ok: boolean) => ok ? <Tag color="green" style={{ border: 'none' }}>通过</Tag> : <Tag color="red" style={{ border: 'none' }}>失败</Tag>,
                  },
                  { title: '输入', dataIndex: 'input', render: (v: any) => <Text code style={{ fontSize: 12 }}>{JSON.stringify(v)}</Text> },
                  { title: '期望', dataIndex: 'expected', render: (v: any) => <Text code style={{ fontSize: 12 }}>{JSON.stringify(v)}</Text> },
                  { title: '实际', dataIndex: 'actual', render: (v: any) => <Text code style={{ fontSize: 12 }}>{JSON.stringify(v)}</Text> },
                ]}
              />
            </Card>
          )}
          
          {submission.run_result?.error && (
            <Card size="small" style={{ borderRadius: 12, textAlign: 'left', marginTop: 16 }} title="运行错误">
              <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#ff4d4f' }}>{submission.run_result.error}</Paragraph>
            </Card>
          )}
        </Card>
      </div>
    );
  }

  if (!started) {
    return (
      <div style={{ maxWidth: 600, margin: '0 auto', padding: '24px 16px' }}>
        <Card style={{ borderRadius: 16 }}>
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <Title level={2} style={{ marginBottom: 8 }}>{test.title}</Title>
            <Space>
              <Tag color={typeInfo.color} style={{ border: 'none' }}>{typeInfo.label}</Tag>
              <Tag style={{ border: 'none' }}>{difficultyLabels[test.difficulty] || '中等'}</Tag>
              {testType === 'algorithm' && (
                <Tag style={{ border: 'none' }}>{(test.language || 'javascript').toUpperCase()}</Tag>
              )}
            </Space>
          </div>

          {test.description && (
            <Card size="small" style={{ background: '#F8FAFC', borderRadius: 12, marginBottom: 24 }}>
              <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{test.description}</Paragraph>
            </Card>
          )}

          {test.duration_minutes && (
            <div style={{ textAlign: 'center', marginBottom: 24 }}>
              <ClockCircleOutlined style={{ marginRight: 8, color: '#1890ff' }} />
              <Text>考试时长：<Text strong>{test.duration_minutes}</Text> 分钟</Text>
            </div>
          )}

          <Divider>开始答题</Divider>

          <Form form={form} layout="vertical">
            <Form.Item 
              name="candidate_name" 
              rules={[{ required: true, message: '请输入姓名' }]}
              label="姓名"
            >
              <Input prefix={<UserOutlined />} placeholder="请输入您的姓名" size="large" />
            </Form.Item>
            <Form.Item 
              name="candidate_email" 
              rules={[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '请输入有效的邮箱地址' }
              ]}
              label="邮箱"
            >
              <Input prefix={<MailOutlined />} placeholder="请输入您的邮箱" size="large" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button 
                type="primary" 
                size="large" 
                block 
                icon={<LoginOutlined />}
                onClick={handleStart}
              >
                开始答题
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </div>
    );
  }

  const renderQuestionCard = (q: any, index: number) => {
    const isAnswered = answers[q.id] && answers[q.id].trim() !== '';
    const isMarked = markedQuestions.has(q.id);
    
    return (
      <Card
        key={q.id}
        id={`question-${q.id}`}
        ref={(el) => { questionRefs.current[q.id] = el; }}
        style={{
          marginBottom: 24,
          borderRadius: 16,
          border: isMarked ? '2px solid #faad14' : undefined,
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
        }}
        styles={{
          header: {
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            borderRadius: '14px 14px 0 0',
            padding: '12px 20px',
          },
        }}
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#fff' }}>
            <Space>
              <span style={{ fontSize: 16, fontWeight: 600 }}>第 {index + 1} 题</span>
              {q.is_multiple && <Tag color="gold">多选</Tag>}
              {isAnswered && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
            </Space>
            <Tooltip title={isMarked ? '取消标记' : '标记此题'}>
              <Button
                type="text"
                icon={isMarked ? <FlagFilled style={{ color: '#faad14' }} /> : <FlagOutlined style={{ color: '#fff' }} />}
                onClick={() => toggleMark(q.id)}
              />
            </Tooltip>
          </div>
        }
      >
        <Paragraph style={{ fontSize: 15, marginBottom: 20, lineHeight: 1.8 }}>{q.question}</Paragraph>
        
        {testType === 'choice' && (
          <>
            {q.is_multiple ? (
              <Checkbox.Group
                value={answers[q.id]?.split(',') || []}
                onChange={(vals) => handleAnswerChange(q.id, (vals as string[]).join(','))}
                style={{ width: '100%' }}
              >
                <Space direction="vertical" style={{ width: '100%' }} size={12}>
                  {q.options?.map((opt: any) => (
                    <div
                      key={opt.label}
                      onClick={() => {
                        const current = answers[q.id]?.split(',').filter(Boolean) || [];
                        const newVals = current.includes(opt.label)
                          ? current.filter((v: string) => v !== opt.label)
                          : [...current, opt.label];
                        handleAnswerChange(q.id, newVals.join(','));
                      }}
                      style={{
                        padding: '12px 16px',
                        borderRadius: 8,
                        border: '1px solid #d9d9d9',
                        background: (answers[q.id]?.split(',') || []).includes(opt.label) ? '#e6f7ff' : '#fff',
                        borderColor: (answers[q.id]?.split(',') || []).includes(opt.label) ? '#1890ff' : '#d9d9d9',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                    >
                      <Checkbox value={opt.label} style={{ pointerEvents: 'none' }}>
                        <Text strong>{opt.label}.</Text> {opt.text}
                      </Checkbox>
                    </div>
                  ))}
                </Space>
              </Checkbox.Group>
            ) : (
              <Radio.Group
                value={answers[q.id]}
                onChange={(e) => handleAnswerChange(q.id, e.target.value)}
                style={{ width: '100%' }}
              >
                <Space direction="vertical" style={{ width: '100%' }} size={12}>
                  {q.options?.map((opt: any) => (
                    <div
                      key={opt.label}
                      onClick={() => handleAnswerChange(q.id, opt.label)}
                      style={{
                        padding: '12px 16px',
                        borderRadius: 8,
                        border: '1px solid #d9d9d9',
                        background: answers[q.id] === opt.label ? '#e6f7ff' : '#fff',
                        borderColor: answers[q.id] === opt.label ? '#1890ff' : '#d9d9d9',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                    >
                      <Radio value={opt.label} style={{ pointerEvents: 'none' }}>
                        <Text strong>{opt.label}.</Text> {opt.text}
                      </Radio>
                    </div>
                  ))}
                </Space>
              </Radio.Group>
            )}
          </>
        )}
        
        {testType === 'essay' && (
          <div>
            <TextArea
              rows={6}
              value={answers[q.id] || ''}
              onChange={(e) => handleAnswerChange(q.id, e.target.value)}
              placeholder="请输入您的答案..."
              style={{ borderRadius: 8, marginBottom: 8 }}
              showCount
              maxLength={2000}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              已输入 {(answers[q.id] || '').length} 字
            </Text>
          </div>
        )}

        
      </Card>
    );
  };

  const renderAnswerSheet = () => {
    const questions = test?.questions || [];
    
    return (
      <Card
        size="small"
        style={{ borderRadius: 12, position: 'sticky', top: 16 }}
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>答题卡</span>
            <Space size={4}>
              <Badge color="#52c41a" text="已答" />
              <Badge color="#faad14" text="标记" />
            </Space>
          </div>
        }
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
          {questions.map((q: any, index: number) => {
            const isAnswered = answers[q.id] && answers[q.id].trim() !== '';
            const isMarked = markedQuestions.has(q.id);
            
            return (
              <div
                key={q.id}
                onClick={() => scrollToQuestion(q.id)}
                style={{
                  width: 36,
                  height: 36,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontWeight: 500,
                  fontSize: 13,
                  border: isMarked ? '2px solid #faad14' : '1px solid #d9d9d9',
                  background: isAnswered ? '#52c41a' : '#fff',
                  color: isAnswered ? '#fff' : '#333',
                  transition: 'all 0.2s',
                }}
              >
                {index + 1}
              </div>
            );
          })}
        </div>
        
        <div style={{ marginTop: 16, padding: '12px', background: '#f5f5f5', borderRadius: 8 }}>
          <Progress
            percent={Math.round((answerStats.answered / answerStats.total) * 100)}
            size="small"
            status={answerStats.answered === answerStats.total ? 'success' : 'active'}
            format={() => `${answerStats.answered}/${answerStats.total}`}
          />
          <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
            <div>已答: {answerStats.answered} 题</div>
            <div>未答: {answerStats.total - answerStats.answered} 题</div>
            {answerStats.marked > 0 && <div style={{ color: '#faad14' }}>标记: {answerStats.marked} 题</div>}
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
      <Card style={{ borderRadius: 16 }}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <Title level={3} style={{ marginBottom: 4 }}>{test.title}</Title>
              <Space>
                <Tag color={typeInfo.color} style={{ border: 'none' }}>{typeInfo.label}</Tag>
                <Tag style={{ border: 'none' }}>{difficultyLabels[test.difficulty] || '中等'}</Tag>
                {testType === 'algorithm' && (
                  <Tag style={{ border: 'none' }}>{(test.language || 'javascript').toUpperCase()}</Tag>
                )}
              </Space>
            </div>
            <Space>
              {candidateInfo && (
                <Text type="secondary">{candidateInfo.name} ({candidateInfo.email})</Text>
              )}
              {timeLeft !== null && timeLeft > 0 && (
                <Tag icon={<ClockCircleOutlined />} color={timeLeft < 300 ? 'red' : 'blue'} style={{ fontSize: 16, padding: '4px 12px' }}>
                  剩余时间: {formatTime(timeLeft)}
                </Tag>
              )}
            </Space>
          </div>

          {test.description && (
            <Card size="small" style={{ background: '#F8FAFC', borderRadius: 12 }}>
              <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{test.description}</Paragraph>
            </Card>
          )}

          {testType === 'algorithm' && (
            <>
              <div>
                <Space style={{ marginBottom: 12 }}>
                  <Button icon={<PlayCircleOutlined />} onClick={handleRun} loading={running}>运行用例</Button>
                  <Button type="primary" icon={<SendOutlined />} onClick={onSubmitClick} loading={submitting}>提交作答</Button>
                  {(runResult || submission?.run_result) && (
                    <Space>
                      <Tag color={(runResult?.passed ?? submission?.run_result?.passed) ? 'green' : 'red'} style={{ border: 'none' }}>
                        {(runResult?.passed ?? submission?.run_result?.passed) ? '通过' : '未通过'}
                      </Tag>
                      <Text type="secondary">得分 {(runResult?.score ?? submission?.run_result?.score) ?? 0}</Text>
                    </Space>
                  )}
                </Space>

                <CodeEditor
                  value={code}
                  onChange={setCode}
                  language={test?.language || 'javascript'}
                  height={420}
                />
              </div>

              {(runResult?.error || submission?.run_result?.error) && (
                <Card size="small" style={{ borderRadius: 12 }} title="运行错误">
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{runResult?.error || submission?.run_result?.error}</Paragraph>
                </Card>
              )}

              {resultRows.length > 0 && (
                <Card size="small" style={{ borderRadius: 12 }} title="测试用例结果">
                  <Table
                    dataSource={resultRows}
                    pagination={false}
                    columns={[
                      { title: '#', dataIndex: 'index', width: 60 },
                      {
                        title: '状态',
                        dataIndex: 'ok',
                        width: 90,
                        render: (ok: boolean) => ok ? <Tag color="green" style={{ border: 'none' }}>通过</Tag> : <Tag color="red" style={{ border: 'none' }}>失败</Tag>,
                      },
                      { title: '输入', dataIndex: 'input', render: (v: any) => <Text code>{JSON.stringify(v)}</Text> },
                      { title: '期望', dataIndex: 'expected', render: (v: any) => <Text code>{JSON.stringify(v)}</Text> },
                      { title: '实际', dataIndex: 'actual', render: (v: any) => <Text code>{JSON.stringify(v)}</Text> },
                    ]}
                  />
                </Card>
              )}
            </>
          )}

          {(testType === 'choice' || testType === 'essay') && (
            <>
              <div style={{ display: 'flex', gap: 24 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {(test?.questions || []).map((q: any, index: number) => renderQuestionCard(q, index))}
                </div>
                <div style={{ width: 240, flexShrink: 0, position: 'sticky', top: 16, alignSelf: 'flex-start', maxHeight: 'calc(100vh - 32px)', overflow: 'auto' }}>
                  {renderAnswerSheet()}
                </div>
              </div>
              
              <div style={{ textAlign: 'center', marginTop: 24, paddingTop: 24, borderTop: '1px solid #f0f0f0' }}>
                <Space size="large">
                  <Button size="large" onClick={() => {
                    const questions = test?.questions || [];
                    if (questions.length > 0) {
                      scrollToQuestion(questions[0].id);
                    }
                  }}>
                    回到顶部
                  </Button>
                  <Button type="primary" size="large" icon={<SendOutlined />} onClick={onSubmitClick} loading={submitting}>
                    提交作答
                  </Button>
                </Space>
              </div>
            </>
          )}
        </Space>
      </Card>
    </div>
  );
};

export default PublicCodingTest;