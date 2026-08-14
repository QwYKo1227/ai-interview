import { AuditOutlined, CalendarOutlined, CheckSquareOutlined, RightOutlined } from '@ant-design/icons';
import { Button, Card, Col, Empty, Row, Skeleton, Tag, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../../contexts/AuthContext';
import request from '../../utils/request';
import { getInterviewEnd, toBeijingTime } from '../Interviews/interviewSchedule';
import './InterviewerDashboard.css';

const { Text, Title } = Typography;

type InterviewerDashboardData = {
  metrics: {
    pending_reviews: number;
    today_interviews: number;
    pending_feedback: number;
  };
  upcoming_interviews: Array<{
    id: string;
    candidate_name?: string | null;
    position_title?: string | null;
    interview_time: string;
    interview_end_time?: string | null;
    interview_type?: string | null;
    interview_location?: string | null;
    meeting_link?: string | null;
  }>;
};

const INTERVIEW_TYPE_LABELS: Record<string, string> = {
  onsite: '现场面试',
  video: '视频面试',
  phone: '电话面试',
};

const InterviewerDashboard = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<InterviewerDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    request.get('/dashboard/interviewer')
      .then((response) => {
        if (active) setData(response);
      })
      .catch(() => {
        if (active) message.error('获取我的工作台失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const metrics = [
    {
      key: 'reviews',
      label: '待评审简历',
      value: data?.metrics.pending_reviews || 0,
      hint: '部门评审任务',
      icon: <AuditOutlined />,
      tone: 'blue',
      onClick: () => navigate('/resumes/my-reviews'),
    },
    {
      key: 'today',
      label: '今日面试',
      value: data?.metrics.today_interviews || 0,
      hint: '已分配给你的场次',
      icon: <CalendarOutlined />,
      tone: 'green',
      onClick: () => navigate('/interviews'),
    },
    {
      key: 'feedback',
      label: '待提交评价',
      value: data?.metrics.pending_feedback || 0,
      hint: '面试结束后待完成',
      icon: <CheckSquareOutlined />,
      tone: 'amber',
      onClick: () => navigate('/interviews'),
    },
  ];

  if (loading) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }

  return (
    <div className="interviewer-dashboard">
      <header className="interviewer-dashboard__header">
        <div>
          <Text className="interviewer-dashboard__eyebrow">我的工作台</Text>
          <Title level={2}>你好，{user?.full_name || '面试官'}</Title>
          <Text type="secondary">只显示分配给你的评审和面试任务</Text>
        </div>
      </header>

      <Row gutter={[16, 16]}>
        {metrics.map((metric) => (
          <Col xs={24} md={8} key={metric.key}>
            <button
              type="button"
              className={`interviewer-metric interviewer-metric--${metric.tone}`}
              onClick={metric.onClick}
            >
              <span className="interviewer-metric__icon">{metric.icon}</span>
              <span className="interviewer-metric__copy">
                <span className="interviewer-metric__label">{metric.label}</span>
                <strong>{metric.value}</strong>
                <span className="interviewer-metric__hint">{metric.hint}</span>
              </span>
              <RightOutlined className="interviewer-metric__arrow" />
            </button>
          </Col>
        ))}
      </Row>

      <Card
        className="interviewer-dashboard__schedule"
        title={(
          <div>
            <div className="interviewer-dashboard__section-title">接下来的面试</div>
            <Text type="secondary">按开始时间排列，最多显示 5 场</Text>
          </div>
        )}
        extra={<Button type="link" onClick={() => navigate('/interviews')}>查看全部</Button>}
      >
        {!data?.upcoming_interviews.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无即将开始的面试" />
        ) : (
          <div className="interviewer-schedule-list">
            {data.upcoming_interviews.map((interview) => {
              const start = toBeijingTime(interview.interview_time);
              const { value: end } = getInterviewEnd(interview);
              const location = interview.interview_type === 'video'
                ? '视频会议'
                : interview.interview_location || INTERVIEW_TYPE_LABELS[interview.interview_type || ''] || '面试';
              return (
                <div className="interviewer-schedule-item" key={interview.id}>
                  <div className="interviewer-schedule-item__time">
                    <strong>{start?.format('MM月DD日')}</strong>
                    <span>{start?.format('HH:mm')}–{end?.format('HH:mm')}</span>
                  </div>
                  <div className="interviewer-schedule-item__main">
                    <strong>{interview.candidate_name || '未知候选人'}</strong>
                    <span>{interview.position_title || '未知岗位'}</span>
                  </div>
                  <Tag>{location}</Tag>
                  <Button onClick={() => navigate(`/interviews/${interview.id}/score`)}>查看安排</Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
};

export default InterviewerDashboard;
