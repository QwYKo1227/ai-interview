import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Card, Button, Result, Spin, Descriptions, Input, Modal, DatePicker, message, Typography, Divider, Tag } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined, MailOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import request from '../../utils/request';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface OfferData {
  id: string;
  candidate_name: string;
  candidate_email: string;
  position_title: string;
  department: string;
  report_to: string;
  work_location: string;
  work_hours: string;
  salary_monthly: number;
  salary_annual: number;
  salary_structure: string;
  onboard_date: string;
  probation_months: number;
  benefits: string;
  bonus: string;
  special_terms: string;
  valid_until: string;
  status: string;
  sent_at: string;
  position_info: {
    id: string;
    title: string;
    department: string;
    location: string;
    salary_range: string;
  };
}

const OfferConfirm: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [offer, setOffer] = useState<OfferData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<'accept' | 'reject' | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [acceptedSalary, setAcceptedSalary] = useState<number | null>(null);
  const [acceptedOnboardDate, setAcceptedOnboardDate] = useState<dayjs.Dayjs | null>(null);
  const [completed, setCompleted] = useState<{ success: boolean; action: string; message: string } | null>(null);

  useEffect(() => {
    fetchOffer();
  }, [token]);

  const fetchOffer = async () => {
    try {
      setLoading(true);
      const response = await request.get(`/public/offers/confirm/${token}`);
      setOffer(response);
      if (response.onboard_date) {
        setAcceptedOnboardDate(dayjs(response.onboard_date));
      }
      if (response.salary_monthly) {
        setAcceptedSalary(response.salary_monthly);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || '获取Offer信息失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!action) return;
    
    if (action === 'reject' && !rejectReason.trim()) {
      message.warning('请填写拒绝原因');
      return;
    }

    try {
      setSubmitting(true);
      const response = await request.post(`/public/offers/confirm/${token}`, {
        action,
        reason: action === 'reject' ? rejectReason : null,
        accepted_salary: action === 'accept' ? acceptedSalary : null,
        accepted_onboard_date: action === 'accept' ? acceptedOnboardDate?.toISOString() : null
      });
      
      setCompleted({
        success: response.success,
        action: response.action,
        message: response.message
      });
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const getStatusTag = (status: string) => {
    const statusMap: Record<string, { color: string; text: string }> = {
      DRAFT: { color: 'default', text: '草稿' },
      PENDING: { color: 'processing', text: '待发送' },
      SENT: { color: 'blue', text: '已发送' },
      ACCEPTED: { color: 'success', text: '已接受' },
      REJECTED: { color: 'error', text: '已拒绝' },
      EXPIRED: { color: 'warning', text: '已过期' },
      WITHDRAWN: { color: 'default', text: '已撤回' }
    };
    const config = statusMap[status] || { color: 'default', text: status };
    return <Tag color={config.color}>{config.text}</Tag>;
  };

  if (loading) {
    return (
      <div style={{ 
        minHeight: '100vh', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
      }}>
        <Spin size="large" />
      </div>
    );
  }

  if (completed) {
    return (
      <div style={{ 
        minHeight: '100vh', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        padding: 20,
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
      }}>
        <Card style={{ maxWidth: 500, width: '100%', textAlign: 'center' }}>
          <Result
            status={completed.success ? 'success' : 'error'}
            title={completed.success ? (completed.action === 'accepted' ? '已接受Offer' : '已拒绝Offer') : '操作失败'}
            subTitle={completed.message}
            icon={completed.success ? 
              (completed.action === 'accepted' ? <CheckCircleOutlined /> : <CloseCircleOutlined />) : 
              <CloseCircleOutlined />
            }
          />
          {completed.success && completed.action === 'accepted' && (
            <Paragraph type="secondary">
              感谢您接受我们的Offer，我们将在近期与您联系后续入职事宜。
            </Paragraph>
          )}
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ 
        minHeight: '100vh', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        padding: 20,
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
      }}>
        <Card style={{ maxWidth: 500, width: '100%' }}>
          <Result
            status="error"
            title="获取Offer信息失败"
            subTitle={error}
          />
        </Card>
      </div>
    );
  }

  if (!offer) {
    return null;
  }

  if (offer.status !== 'sent' && offer.status !== 'SENT') {
    return (
      <div style={{ 
        minHeight: '100vh', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        padding: 20,
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
      }}>
        <Card style={{ maxWidth: 500, width: '100%' }}>
          <Result
            status="warning"
            title="Offer状态已变更"
            subTitle={<span>当前Offer状态为：{getStatusTag(offer.status.toUpperCase())}</span>}
          />
        </Card>
      </div>
    );
  }

  const isExpired = offer.valid_until && dayjs(offer.valid_until).isBefore(dayjs());

  if (isExpired) {
    return (
      <div style={{ 
        minHeight: '100vh', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        padding: 20,
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
      }}>
        <Card style={{ maxWidth: 500, width: '100%' }}>
          <Result
            status="error"
            title="Offer已过期"
            subTitle={`此Offer已于 ${dayjs(offer.valid_until).format('YYYY年MM月DD日')} 过期`}
          />
        </Card>
      </div>
    );
  }

  return (
    <div style={{ 
      minHeight: '100vh', 
      padding: '40px 20px',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
    }}>
      <Card style={{ maxWidth: 800, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 30 }}>
          <Title level={2} style={{ marginBottom: 8 }}>
            🎉 录用通知确认
          </Title>
          <Text type="secondary">
            <MailOutlined style={{ marginRight: 8 }} />
            尊敬的 {offer.candidate_name}，请确认您的Offer
          </Text>
        </div>

        <Descriptions bordered column={2} style={{ marginBottom: 24 }}>
          <Descriptions.Item label="岗位名称" span={2}>
            <Text strong>{offer.position_title}</Text>
          </Descriptions.Item>
          {offer.department && (
            <Descriptions.Item label="所属部门">{offer.department}</Descriptions.Item>
          )}
          {offer.report_to && (
            <Descriptions.Item label="汇报对象">{offer.report_to}</Descriptions.Item>
          )}
          {offer.work_location && (
            <Descriptions.Item label="工作地点">{offer.work_location}</Descriptions.Item>
          )}
          {offer.work_hours && (
            <Descriptions.Item label="工作时间">{offer.work_hours}</Descriptions.Item>
          )}
          {(offer.salary_monthly || offer.salary_annual) && (
            <Descriptions.Item label="薪资待遇" span={2}>
              <Text type="success" strong style={{ fontSize: 16 }}>
                {offer.salary_monthly && `月薪：${offer.salary_monthly.toLocaleString()}元`}
                {offer.salary_monthly && offer.salary_annual && ' / '}
                {offer.salary_annual && `年薪：${offer.salary_annual.toLocaleString()}元`}
              </Text>
            </Descriptions.Item>
          )}
          {offer.salary_structure && (
            <Descriptions.Item label="薪资结构" span={2}>{offer.salary_structure}</Descriptions.Item>
          )}
          <Descriptions.Item label="入职日期">
            {dayjs(offer.onboard_date).format('YYYY年MM月DD日')}
          </Descriptions.Item>
          <Descriptions.Item label="试用期">{offer.probation_months}个月</Descriptions.Item>
          {offer.benefits && (
            <Descriptions.Item label="福利待遇" span={2}>{offer.benefits}</Descriptions.Item>
          )}
          {offer.bonus && (
            <Descriptions.Item label="奖金" span={2}>{offer.bonus}</Descriptions.Item>
          )}
          {offer.special_terms && (
            <Descriptions.Item label="特别说明" span={2}>{offer.special_terms}</Descriptions.Item>
          )}
          <Descriptions.Item label="Offer有效期">
            <Text type="warning">
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              {dayjs(offer.valid_until).format('YYYY年MM月DD日')}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="发送时间">
            {dayjs(offer.sent_at).format('YYYY-MM-DD HH:mm')}
          </Descriptions.Item>
        </Descriptions>

        <Divider />

        <div style={{ textAlign: 'center' }}>
          <Title level={4} style={{ marginBottom: 24 }}>请确认您的决定</Title>
          
          <div style={{ marginBottom: 24 }}>
            <Button
              type={action === 'accept' ? 'primary' : 'default'}
              size="large"
              icon={<CheckCircleOutlined />}
              onClick={() => setAction('accept')}
              style={{ marginRight: 16, minWidth: 120 }}
            >
              接受 Offer
            </Button>
            <Button
              type={action === 'reject' ? 'primary' : 'default'}
              danger={action === 'reject'}
              size="large"
              icon={<CloseCircleOutlined />}
              onClick={() => setAction('reject')}
              style={{ minWidth: 120 }}
            >
              拒绝 Offer
            </Button>
          </div>

          {action === 'accept' && (
            <Card size="small" style={{ marginBottom: 24, textAlign: 'left' }}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="确认入职日期">
                  <DatePicker
                    value={acceptedOnboardDate}
                    onChange={(date) => setAcceptedOnboardDate(date)}
                    format="YYYY-MM-DD"
                    style={{ width: 200 }}
                  />
                </Descriptions.Item>
                <Descriptions.Item label="确认月薪（元）">
                  <Input
                    type="number"
                    value={acceptedSalary || ''}
                    onChange={(e) => setAcceptedSalary(e.target.value ? Number(e.target.value) : null)}
                    style={{ width: 200 }}
                    placeholder="如有调整请填写"
                  />
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}

          {action === 'reject' && (
            <div style={{ marginBottom: 24 }}>
              <TextArea
                rows={4}
                placeholder="请填写拒绝原因（必填）"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                style={{ marginBottom: 16 }}
              />
            </div>
          )}

          {action && (
            <Button
              type="primary"
              size="large"
              loading={submitting}
              onClick={handleSubmit}
              style={{ minWidth: 200 }}
            >
              确认提交
            </Button>
          )}
        </div>

        <Divider />

        <div style={{ textAlign: 'center', color: '#999', fontSize: 12 }}>
          <p>如有任何疑问，请随时与我们联系</p>
          <p>此页面由系统自动生成</p>
        </div>
      </Card>
    </div>
  );
};

export default OfferConfirm;
