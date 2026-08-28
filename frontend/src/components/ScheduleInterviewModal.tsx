import React, { useEffect, useState } from 'react';
import {
  Button,
  Checkbox,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Tag,
  Typography,
} from 'antd';
import { useNavigate } from 'react-router-dom';
import request from '../utils/request';
import {
  buildInterviewTimePayload,
  defaultInterviewEnd,
  INTERVIEW_MINUTE_STEP,
  getScheduleErrorMessage,
  validateInterviewTimeRange,
} from '../pages/Interviews/interviewSchedule';

const { Text } = Typography;

interface ScheduleInterviewResume {
  id: string;
  position_id: string;
}

interface InterviewSummary {
  id: string;
  resume_id: string;
  status: string;
  round?: number;
}

interface InterviewerOption {
  id: string;
  full_name?: string | null;
  email: string;
}

interface QuestionBankOption {
  id: string;
  name: string;
}

interface EmailPreview {
  subject: string;
  content: string;
  to_email: string;
  candidate_name: string;
}

interface ScheduleInterviewModalProps {
  open: boolean;
  resume: ScheduleInterviewResume;
  onClose: () => void;
}

const ScheduleInterviewModal: React.FC<ScheduleInterviewModalProps> = ({
  open,
  resume,
  onClose,
}) => {
  const navigate = useNavigate();
  const [interviewForm] = Form.useForm();
  const [emailForm] = Form.useForm();
  const [existingInterviews, setExistingInterviews] = useState<InterviewSummary[]>([]);
  const [interviewers, setInterviewers] = useState<InterviewerOption[]>([]);
  const [questionBanks, setQuestionBanks] = useState<QuestionBankOption[]>([]);
  const [emailPreviewVisible, setEmailPreviewVisible] = useState(false);
  const [emailContent, setEmailContent] = useState<EmailPreview | null>(null);
  const [pendingInterviewData, setPendingInterviewData] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);

  useEffect(() => {
    if (!open) return;

    interviewForm.resetFields();
    setEmailPreviewVisible(false);

    const prepareForm = async () => {
      const [interviewsResult, interviewersResult, questionBanksResult] = await Promise.allSettled([
        request.get('/interviews'),
        request.get('/auth/interviewers'),
        request.get('/question-banks'),
      ]);

      let nextRound = 1;
      if (interviewsResult.status === 'fulfilled') {
        const resumeInterviews = (interviewsResult.value as InterviewSummary[])
          .filter((interview) => interview.resume_id === resume.id);
        setExistingInterviews(resumeInterviews);
        nextRound = resumeInterviews.reduce(
          (max, interview) => Math.max(max, interview.round || 1),
          0,
        ) + 1;
      } else {
        setExistingInterviews([]);
      }

      if (interviewersResult.status === 'fulfilled') {
        setInterviewers(interviewersResult.value as InterviewerOption[]);
      }
      if (questionBanksResult.status === 'fulfilled') {
        setQuestionBanks(questionBanksResult.value as QuestionBankOption[]);
      }

      interviewForm.setFieldsValue({
        question_count: 5,
        interview_type: 'onsite',
        interview_category: 'technical',
        round: nextRound,
        skip_ai_questions: false,
      });
    };

    void prepareForm();
  }, [interviewForm, open, resume.id]);

  const handleInterviewOk = async () => {
    try {
      const values = await interviewForm.validateFields();
      setSubmitting(true);

      const interviewData = {
        resume_id: resume.id,
        position_id: resume.position_id,
        interviewer: '面试小组',
        panel_members: values.panel_members,
        ...buildInterviewTimePayload(values),
        question_bank_ids: values.question_bank_ids,
        question_count: values.question_count,
        round: values.round || 1,
        interview_type: values.interview_type || 'onsite',
        interview_category: values.interview_category || 'technical',
        interview_location: values.interview_location,
        meeting_link: values.meeting_link,
        skip_ai_questions: values.skip_ai_questions || false,
      };
      setPendingInterviewData(interviewData);

      try {
        const emailPreview = await request.post('/interviews/email-preview', {
          resume_id: resume.id,
          position_id: resume.position_id,
          panel_members: values.panel_members,
          ...buildInterviewTimePayload(values),
          round: values.round || 1,
          interview_type: values.interview_type || 'onsite',
          interview_category: values.interview_category || 'technical',
          interview_location: values.interview_location,
          meeting_link: values.meeting_link,
        }) as EmailPreview;

        setEmailContent(emailPreview);
        emailForm.setFieldsValue({
          subject: emailPreview.subject,
          content: emailPreview.content,
          send_email: true,
        });
        setEmailPreviewVisible(true);
      } catch (error) {
        console.error('获取邮件预览失败', error);
        const result = await request.post('/interviews', {
          ...interviewData,
          skip_email: true,
        }) as { id: string };
        message.success('面试安排成功');
        onClose();
        navigate(`/interviews/${result.id}/score`);
      }
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return;
      message.error(getScheduleErrorMessage(error, '安排面试失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmAndSend = async () => {
    try {
      const values = await emailForm.validateFields();
      setSendingEmail(true);
      const result = await request.post('/interviews', {
        ...pendingInterviewData,
        skip_email: true,
      }) as { id: string };

      if (values.send_email && result.id) {
        try {
          await request.post(`/interviews/${result.id}/send-email`, {
            subject: values.subject,
            content: values.content,
          });
          message.success('面试安排成功，邮件已发送');
        } catch {
          message.warning('面试安排成功，但邮件发送失败');
        }
      } else {
        message.success('面试安排成功');
      }

      setEmailPreviewVisible(false);
      onClose();
      navigate(`/interviews/${result.id}/score`);
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return;
      message.error(getScheduleErrorMessage(error, '安排面试失败'));
    } finally {
      setSendingEmail(false);
    }
  };

  const returnToInterviewForm = () => setEmailPreviewVisible(false);

  return (
    <>
      <Modal
        title="安排面试"
        open={open && !emailPreviewVisible}
        onOk={() => void handleInterviewOk()}
        onCancel={onClose}
        confirmLoading={submitting}
        width={700}
        centered
        destroyOnHidden
        okText="确认"
        cancelText="取消"
      >
        {existingInterviews.length > 0 && (
          <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
            <Text strong>该候选人已有 {existingInterviews.length} 轮面试：</Text>
            <div style={{ marginTop: 8 }}>
              {existingInterviews.map((interview) => (
                <Tag key={interview.id} color={interview.status === 'completed' ? 'green' : 'blue'}>
                  第{interview.round || 1}轮 - {interview.status === 'completed' ? '已完成' : '待面试'}
                </Tag>
              ))}
            </div>
          </div>
        )}

        <Form form={interviewForm} layout="vertical" style={{ marginTop: 24 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="round" label="面试轮次" rules={[{ required: true, message: '请选择面试轮次' }]}>
                <Select placeholder="选择轮次" size="large">
                  {[1, 2, 3, 4, 5].map((round) => (
                    <Select.Option key={round} value={round}>第{round}轮面试</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="interview_category"
                label="面试类型"
                rules={[{ required: true, message: '请选择面试类型' }]}
                extra="不同类型会生成不同侧重点的面试题"
              >
                <Select placeholder="选择面试类型" size="large">
                  <Select.Option value="hr">HR面</Select.Option>
                  <Select.Option value="technical">技术面</Select.Option>
                  <Select.Option value="manager">主管面</Select.Option>
                  <Select.Option value="ceo">CEO面</Select.Option>
                  <Select.Option value="comprehensive">综合面</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="interview_type" label="面试形式" rules={[{ required: true, message: '请选择面试形式' }]}>
                <Select placeholder="选择面试形式" size="large">
                  <Select.Option value="onsite">现场面试</Select.Option>
                  <Select.Option value="video">视频面试</Select.Option>
                  <Select.Option value="phone">电话面试</Select.Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="panel_members"
            label="面试官"
            rules={[{ required: true, message: '请选择面试官' }]}
            extra="选择参与此次面试的面试官（可多选）"
          >
            <Select mode="multiple" placeholder="选择面试官" size="large" style={{ width: '100%' }}>
              {interviewers.map((interviewer) => (
                <Select.Option key={interviewer.id} value={interviewer.id}>
                  {interviewer.full_name || interviewer.email}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="interview_time" label="开始时间" rules={[{ required: true, message: '请选择开始时间' }]}>
                <DatePicker
                  showTime={{ format: 'HH:mm', minuteStep: INTERVIEW_MINUTE_STEP, showNow: false }}
                  format="YYYY-MM-DD HH:mm"
                  style={{ width: '100%' }}
                  size="large"
                  onChange={(value) => {
                    const currentEnd = interviewForm.getFieldValue('interview_end_time');
                    if (value && (!currentEnd || !currentEnd.isAfter(value))) {
                      interviewForm.setFieldValue('interview_end_time', defaultInterviewEnd(value));
                    }
                  }}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="interview_end_time"
                label="结束时间"
                dependencies={['interview_time']}
                rules={[
                  { required: true, message: '请选择结束时间' },
                  ({ getFieldValue }) => ({
                    validator: (_, value) => {
                      const error = validateInterviewTimeRange(getFieldValue('interview_time'), value);
                      return error ? Promise.reject(new Error(error)) : Promise.resolve();
                    },
                  }),
                ]}
              >
                <DatePicker showTime={{ format: 'HH:mm', minuteStep: INTERVIEW_MINUTE_STEP, showNow: false }} format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} size="large" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item noStyle shouldUpdate={(previous, current) => previous.interview_type !== current.interview_type}>
            {({ getFieldValue }) => {
              const interviewType = getFieldValue('interview_type');
              return (
                <>
                  {interviewType === 'onsite' && (
                    <Form.Item name="interview_location" label="面试地点" rules={[{ required: true, whitespace: true, message: '请输入面试地点' }]}>
                      <Input placeholder="请输入面试地点，如：北京市朝阳区xxx大厦A座10层" size="large" />
                    </Form.Item>
                  )}
                  {interviewType === 'video' && (
                    <Form.Item name="meeting_link" label="会议链接" rules={[{ required: true, whitespace: true, message: '请输入会议链接' }]}>
                      <Input placeholder="请输入视频会议链接，如：https://meeting.xxx.com/xxx" size="large" />
                    </Form.Item>
                  )}
                </>
              );
            }}
          </Form.Item>

          <Form.Item name="skip_ai_questions" valuePropName="checked" extra="勾选后将跳过AI生成面试题，您可以稍后手动添加题目">
            <Checkbox>跳过AI生成面试题</Checkbox>
          </Form.Item>

          <Form.Item noStyle shouldUpdate={(previous, current) => previous.skip_ai_questions !== current.skip_ai_questions}>
            {({ getFieldValue }) => !getFieldValue('skip_ai_questions') ? (
              <>
                <Form.Item name="question_bank_ids" label="参考题库" extra="选择题库后，AI 将参考题库内容生成更精准的面试题">
                  <Select mode="multiple" placeholder="选择参考题库" size="large" style={{ width: '100%' }}>
                    {questionBanks.map((questionBank) => (
                      <Select.Option key={questionBank.id} value={questionBank.id}>{questionBank.name}</Select.Option>
                    ))}
                  </Select>
                </Form.Item>
                <Form.Item name="question_count" label="生成题目数量">
                  <InputNumber min={1} max={20} size="large" style={{ width: '100%' }} />
                </Form.Item>
              </>
            ) : null}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="邮件预览"
        open={open && emailPreviewVisible}
        onCancel={returnToInterviewForm}
        width={800}
        centered
        destroyOnHidden
        footer={[
          <Button key="cancel" onClick={returnToInterviewForm}>取消</Button>,
          <Button key="confirm" type="primary" loading={sendingEmail} onClick={() => void handleConfirmAndSend()}>
            确认
          </Button>,
        ]}
      >
        {emailContent && (
          <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
            <p><strong>收件人：</strong>{emailContent.to_email}</p>
            <p><strong>候选人：</strong>{emailContent.candidate_name}</p>
          </div>
        )}
        <Form form={emailForm} layout="vertical">
          <Form.Item name="subject" label="邮件主题" rules={[{ required: true, message: '请输入邮件主题' }]}>
            <Input placeholder="邮件主题" size="large" />
          </Form.Item>
          <Form.Item name="content" label="邮件内容" rules={[{ required: true, message: '请输入邮件内容' }]}>
            <Input.TextArea rows={10} placeholder="邮件内容（支持 HTML 格式）" style={{ fontFamily: 'monospace' }} />
          </Form.Item>
          <Form.Item label="邮件预览">
            <div
              style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 16, maxHeight: 300, overflow: 'auto', background: '#fff' }}
              dangerouslySetInnerHTML={{ __html: emailForm.getFieldValue('content') || '' }}
            />
          </Form.Item>
          <Form.Item name="send_email" valuePropName="checked">
            <Checkbox>发送邮件通知候选人</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

export default ScheduleInterviewModal;
