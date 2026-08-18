import React, { useEffect, useState } from 'react';
import { Card, Descriptions, Tag, Button, Row, Col, Typography, message, Divider, Spin, Progress, Modal, Form, Input, Space, Select, Rate, List, Avatar, Statistic, Empty } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import request from '../../utils/request';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import dayjs from 'dayjs';
import { DownloadOutlined, FilePdfOutlined, FileWordOutlined, ArrowLeftOutlined, CloseCircleOutlined, EditOutlined, SaveOutlined, ReloadOutlined, UserOutlined, CheckCircleOutlined, TeamOutlined, SolutionOutlined, ClockCircleOutlined, LinkOutlined } from '@ant-design/icons';
import RejectReasonSelector, { REJECT_REASONS } from '../../components/RejectReasonSelector';
import { useAuth } from '../../contexts/AuthContext';
import { getMaximizedPdfPreviewUrl } from '../../utils/pdfPreview';
import { useAuthenticatedFileUrl } from '../../hooks/useAuthenticatedFileUrl';
import ScheduleInterviewModal from '../../components/ScheduleInterviewModal';

const { Title, Paragraph, Text } = Typography;
const { TextArea } = Input;

// 状态映射
const STATUS_MAP: Record<string, { text: string; color: string }> = {
  pending_screening: { text: '待初筛', color: 'warning' },
  pending_review: { text: '待评审', color: 'warning' },
  pending_dept_review: { text: '待部门评审', color: 'cyan' },
  pending_hr_decision: { text: '待HR决策', color: 'purple' },
  auto_rejected_pending_review: { text: 'AI建议淘汰', color: 'orange' },
  pending_interview: { text: '待安排面试', color: 'geekblue' },
  interview_scheduled: { text: '面试已安排', color: 'blue' },
  interview_in_progress: { text: '面试中', color: 'orange' },
  pending_interview_result: { text: '待确认面试结果', color: 'purple' },
  pending_next_interview: { text: '待安排下一轮面试', color: 'cyan' },
  interview_passed: { text: '面试通过，进入录用决策', color: 'lime' },
  interview_failed: { text: '面试淘汰', color: 'magenta' },
  offer_pending: { text: 'Offer待确认', color: 'blue' },
  offer_accepted: { text: '已接受Offer', color: 'success' },
  offer_rejected: { text: '已拒绝Offer', color: 'error' },
  completed: { text: '已入职', color: 'success' },
  rejected: { text: '已淘汰', color: 'error' },
  waitlist: { text: '备选', color: 'gold' },
};

const ResumeDetail: React.FC = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [resume, setResume] = useState<any>(null);
  const protectedFile = useAuthenticatedFileUrl(resume?.file_path);
  const [loading, setLoading] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [form] = Form.useForm();
  const [rejectForm] = Form.useForm();
  const [hrDecisionForm] = Form.useForm();
  const [deptReviewForm] = Form.useForm();

  // 获取用户角色
  const userRole = (user as any)?.role?.value ?? (user as any)?.role;

  // 部门评审相关状态
  const [deptReviewSummary, setDeptReviewSummary] = useState<any>(null);
  const [reviewers, setReviewers] = useState<any[]>([]);
  const [isDeptReviewModalVisible, setIsDeptReviewModalVisible] = useState(false);
  const [isAssignReviewerModalVisible, setIsAssignReviewerModalVisible] = useState(false);
  const [isChangeReviewerModalVisible, setIsChangeReviewerModalVisible] = useState(false);
  const [selectedReview, setSelectedReview] = useState<any>(null);
  const [isRejectModalVisible, setIsRejectModalVisible] = useState(false);
  const [isHRDecisionModalVisible, setIsHRDecisionModalVisible] = useState(false);
  const [isSubmitReviewModalVisible, setIsSubmitReviewModalVisible] = useState(false);
  const [myReview, setMyReview] = useState<any>(null);
  const [submitReviewForm] = Form.useForm();
  const [changeReviewerForm] = Form.useForm();
  const [isScheduleInterviewModalVisible, setIsScheduleInterviewModalVisible] = useState(false);

  useEffect(() => {
    if (id) {
      fetchResume(id);
      fetchReviewers();
    }
  }, [id]);

  const fetchResume = async (resumeId: string) => {
    setLoading(true);
    try {
      const res = await request.get(`/resumes/${resumeId}`) as any;
      setResume(res);
      form.setFieldsValue({
          candidate_name: res.candidate_name,
          email: res.email,
          contact: res.contact,
          highest_degree: res.parsed_data?.highest_degree,
          school: res.parsed_data?.school,
          major: res.parsed_data?.major,
          years_of_experience: res.parsed_data?.years_of_experience,
          recent_company: res.parsed_data?.recent_company
      });

      // 获取部门评审汇总
      if (res.status === 'pending_dept_review' || res.status === 'pending_hr_decision' || res.department_reviews) {
        fetchDeptReviewSummary(resumeId);
      }

      // 检查当前用户是否是被指派的评审人
      if (res.department_reviews && user?.id) {
        const myReviewRecord = res.department_reviews.find((r: any) => r.reviewer_id === user.id);
        if (myReviewRecord) {
          setMyReview(myReviewRecord);
        }
      }
    } catch (error) {
      message.error('获取简历详情失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchDeptReviewSummary = async (resumeId: string) => {
    try {
      const res = await request.get(`/resumes/${resumeId}/department-reviews`);
      setDeptReviewSummary(res);
    } catch (error) {
      console.error('获取部门评审汇总失败');
    }
  };

  const fetchReviewers = async () => {
    try {
      const res = await request.get('/auth/interviewers');
      setReviewers(res);
    } catch (error) {
      console.error('获取评审人列表失败');
    }
  };

  const handleUpdate = async () => {
      try {
          const values = await form.validateFields();
          await request.put(`/resumes/${id}`, {
              candidate_name: values.candidate_name,
              email: values.email,
              contact: values.contact,
              highest_degree: values.highest_degree,
              school: values.school,
              major: values.major,
              years_of_experience: values.years_of_experience,
              recent_company: values.recent_company,
          });
          message.success('更新成功');
          setIsEditing(false);
          fetchResume(id!);
      } catch (error) {
          message.error('更新失败');
      }
  };

  const getStatusInfo = (status: string, parseStatus?: string) => {
      if (parseStatus === 'failed') return { text: '解析失败', color: 'error' };
      if (parseStatus === 'processing') return { text: '解析中', color: 'processing' };
      return STATUS_MAP[status] || { text: status, color: 'default' };
  };

  const getParseStatusInfo = (parseStatus?: string) => {
      if (parseStatus === 'failed') return { text: '解析失败', color: 'error' };
      if (parseStatus === 'processing') return { text: '解析中', color: 'processing' };
      if (parseStatus === 'success') return { text: '解析成功', color: 'success' };
      return { text: '未解析', color: 'default' };
  };

  if (loading || !resume) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  const parsedData = resume.parsed_data || {};
  const fileUrl = protectedFile.url;
  const isPdf = protectedFile.contentType === 'application/pdf';
  const pdfPreviewUrl = isPdf ? getMaximizedPdfPreviewUrl(fileUrl) : '';
  const workflowStatusInfo = getStatusInfo(resume.status);
  const parseStatusInfo = getParseStatusInfo(resume.parse_status);

  const handleReparse = () => {
    Modal.confirm({
      title: '重新解析简历',
      content: '将重新调用 AI 解析该简历，并覆盖现有解析结果。',
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await request.post(`/resumes/${id}/reparse`);
          message.success('已开始重新解析');
          fetchResume(id!);
        } catch (error) {
          message.error('重新解析失败');
        }
      },
    });
  };

  // 确认淘汰低分简历
  const handleConfirmRejection = async () => {
    try {
      const values = await rejectForm.validateFields();
      const formData = new FormData();
      formData.append('reason_category', values.reject_reason_category);
      if (values.reject_reason_detail) {
        formData.append('reason_detail', values.reject_reason_detail);
      }
      formData.append('hr_id', user?.id || '');

      await request.post(`/resumes/${id}/confirm-rejection`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      message.success('已确认淘汰');
      setIsRejectModalVisible(false);
      rejectForm.resetFields();
      fetchResume(id!);
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 覆盖AI淘汰建议
  const handleOverrideRejection = async () => {
    Modal.confirm({
      title: '恢复简历',
      content: '确定要将此简历恢复到评审流程吗？',
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const formData = new FormData();
          formData.append('hr_id', user?.id || '');
          await request.post(`/resumes/${id}/override-rejection`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          });
          message.success('已恢复到评审流程');
          fetchResume(id!);
        } catch (error) {
          message.error('操作失败');
        }
      }
    });
  };

  // 将备选简历恢复为待评审
  const handleRestoreWaitlist = async () => {
    Modal.confirm({
      title: '恢复简历',
      content: '确定要将此备选简历恢复到评审流程吗？',
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await request.put(`/resumes/${id}`, { status: 'pending_review' });
          message.success('已恢复到待评审状态');
          fetchResume(id!);
        } catch (error) {
          message.error('操作失败');
        }
      }
    });
  };

  // 指派评审人
  const copyReviewLink = async (rawToken: string) => {
    const url = `${window.location.origin}/public/review/${rawToken}`;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
      } else {
        const textArea = document.createElement('textarea');
        textArea.value = url;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      message.success('评审链接已复制');
    } catch (_error) {
      message.info(url);
    }
  };

  type ReviewLink = {
    reviewerId: string;
    reviewerName: string;
    token: string;
    link: string;
  };

  const showReviewLinks = (successfulLinks: ReviewLink[], failedReviewers: string[]) => {
    Modal.info({
      title: '部门评审链接',
      width: 720,
      content: (
        <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
          {successfulLinks.map(({ reviewerId, reviewerName, token, link }) => (
            <div key={reviewerId} style={{ width: '100%' }}>
              <Text strong>{reviewerName}</Text>
              <Space.Compact style={{ width: '100%' }}>
                <Input value={link} readOnly aria-label={`${reviewerName} 的评审链接`} />
                <Button type="primary" onClick={() => copyReviewLink(token)}>复制</Button>
              </Space.Compact>
            </div>
          ))}
          {failedReviewers.length > 0 && (
            <Text type="danger">创建失败：{failedReviewers.join('、')}</Text>
          )}
        </Space>
      ),
    });
  };

  const openChangeReviewer = (review: any) => {
    setSelectedReview(review);
    changeReviewerForm.setFieldsValue({ reviewer_id: review.reviewer_id });
    setIsChangeReviewerModalVisible(true);
  };

  const handleChangeReviewer = async () => {
    if (!selectedReview) return;
    try {
      const values = await changeReviewerForm.validateFields();
      const formData = new FormData();
      formData.append('reviewer_id', values.reviewer_id);
      await request.put(
        `/resumes/${id}/department-reviews/${selectedReview.id}/reviewer`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      message.success('部门评审人已修改');
      setIsChangeReviewerModalVisible(false);
      setSelectedReview(null);
      changeReviewerForm.resetFields();
      fetchResume(id!);
      fetchDeptReviewSummary(id!);
    } catch (error) {
      message.error('修改评审人失败');
    }
  };

  const handleShowReviewLink = async (review: any) => {
    try {
      const result = await request.post(
        `/resumes/${id}/department-reviews/${review.id}/review-link`,
      );
      if (!result?.public_token) {
        throw new Error('missing public token');
      }
      showReviewLinks([{
        reviewerId: review.reviewer_id,
        reviewerName: review.reviewer_name || '评审人',
        token: result.public_token,
        link: `${window.location.origin}/public/review/${result.public_token}`,
      }], []);
    } catch (error) {
      message.error('获取评审链接失败');
    }
  };

  const handleAssignReviewer = async () => {
    try {
      const values = await deptReviewForm.validateFields();
      const reviewerIds = values.reviewer_ids; // 多选
      const results = await Promise.allSettled(
        reviewerIds.map(async (reviewerId: string): Promise<ReviewLink> => {
          const reviewer = reviewers.find((item: any) => item.id === reviewerId);
          const reviewerName = reviewer?.full_name || reviewer?.email || reviewerId;
          const formData = new FormData();
          formData.append('reviewer_id', reviewerId);
          const created = await request.post(`/resumes/${id}/department-reviews`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          });
          if (!created?.public_token) {
            throw new Error(reviewerName);
          }
          return {
            reviewerId,
            reviewerName,
            token: created.public_token,
            link: `${window.location.origin}/public/review/${created.public_token}`,
          };
        })
      );
      const successfulLinks = results
        .filter((result): result is PromiseFulfilledResult<ReviewLink> => result.status === 'fulfilled')
        .map(result => result.value);
      const failedReviewers = results
        .map((result, index) => result.status === 'rejected'
          ? (reviewers.find((item: any) => item.id === reviewerIds[index])?.full_name
            || reviewers.find((item: any) => item.id === reviewerIds[index])?.email
            || reviewerIds[index])
          : null)
        .filter((name): name is string => Boolean(name));

      showReviewLinks(successfulLinks, failedReviewers);
      if (failedReviewers.length > 0) {
        message.warning(`成功 ${successfulLinks.length} 位，失败 ${failedReviewers.length} 位`);
      } else {
        message.success(`已指派 ${successfulLinks.length} 位评审人`);
      }
      setIsAssignReviewerModalVisible(false);
      deptReviewForm.resetFields();
      fetchResume(id!);
      fetchDeptReviewSummary(id!);
    } catch (error) {
      message.error('指派失败');
    }
  };

  // HR决策
  const handleHRDecision = async () => {
    try {
      const values = await hrDecisionForm.validateFields();

      if (values.decision === 'rejected' && !values.reject_reason_category) {
        message.error('淘汰时必须选择淘汰原因');
        return;
      }

      const payload: any = {
        hr_id: user?.id,
        decision: values.decision,
        hr_comment: values.hr_comment || null,
      };

      if (values.decision === 'rejected') {
        payload.reject_reason_category = values.reject_reason_category;
        payload.reject_reason_detail = values.reject_reason_detail || null;
      }

      await request.post(`/resumes/${id}/hr-decision`, payload);

      message.success('决策已提交');
      setIsHRDecisionModalVisible(false);
      hrDecisionForm.resetFields();
      fetchResume(id!);
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 提交部门评审
  const handleSubmitReview = async () => {
    try {
      const values = await submitReviewForm.validateFields();
      const formData = new FormData();
      formData.append('technical_score', values.technical_score || '');
      formData.append('experience_score', values.experience_score || '');
      formData.append('overall_score', values.overall_score || '');
      formData.append('recommendation', values.recommendation || '');
      formData.append('comment', values.comment || '');

      await request.put(
        `/resumes/${id}/department-reviews/${myReview.id}`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );

      message.success('评审已提交');
      setIsSubmitReviewModalVisible(false);
      submitReviewForm.resetFields();
      fetchResume(id!);
      fetchDeptReviewSummary(id!);
    } catch (error) {
      message.error('提交失败');
    }
  };

  // 转岗
  const handleTransfer = (newPositionId: string, positionTitle: string) => {
    Modal.confirm({
      title: '确认转岗',
      content: `确定将该候选人转岗到「${positionTitle}」吗？转岗后将重新进行简历分析。`,
      okText: '确认转岗',
      cancelText: '取消',
      onOk: async () => {
        try {
          const formData = new FormData();
          formData.append('new_position_id', newPositionId);
          await request.post(`/resumes/${id}/transfer`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          });
          message.success('转岗成功，正在重新解析简历');
          fetchResume(id!);
        } catch (error) {
          message.error('转岗失败');
        }
      }
    });
  };

  // 渲染操作按钮区域
  const renderActionButtons = () => {
    const buttons: React.ReactNode[] = [];

    // 检查当前用户是否是被指派的评审人且未完成评审
    const isAssignedReviewer = myReview && !myReview.is_completed;

    // 如果是被指派的评审人，显示提交评审按钮
    if (isAssignedReviewer) {
      buttons.push(
        <Button
          key="submit-review"
          type="primary"
          icon={<SolutionOutlined />}
          onClick={() => setIsSubmitReviewModalVisible(true)}
        >
          提交评审
        </Button>
      );
      return buttons; // 评审人只显示提交评审按钮
    }

    // 以下操作仅对 HR 和 Admin 显示
    if (userRole !== 'admin' && userRole !== 'hr') {
      return buttons;
    }

    // 基础操作
    if (!isEditing) {
      buttons.push(
        <Button key="reparse" icon={<ReloadOutlined />} onClick={handleReparse} disabled={resume?.parse_status === 'processing'}>重新解析</Button>,
        <Button key="edit" icon={<EditOutlined />} onClick={() => setIsEditing(true)}>编辑</Button>
      );
    } else {
      buttons.push(
        <Button key="save" icon={<SaveOutlined />} type="primary" onClick={handleUpdate}>保存</Button>,
        <Button key="cancel" onClick={() => setIsEditing(false)}>取消</Button>
      );
      return buttons;
    }

    // 根据状态显示不同操作
    if (resume.status === 'auto_rejected_pending_review') {
      buttons.push(
        <Button key="confirm-reject" danger icon={<CloseCircleOutlined />} onClick={() => setIsRejectModalVisible(true)}>确认淘汰</Button>,
        <Button key="override" type="primary" icon={<CheckCircleOutlined />} onClick={handleOverrideRejection}>恢复评审</Button>
      );
    } else if (resume.status === 'waitlist') {
      buttons.push(
        <Button key="restore-waitlist" type="primary" icon={<CheckCircleOutlined />} onClick={handleRestoreWaitlist}>恢复评审</Button>
      );
    } else if (resume.status === 'pending_review') {
      // 待评审状态：可指派部门评测人，也可由 HR 直接决策
      buttons.push(
        <Button key="assign-reviewer" icon={<TeamOutlined />} onClick={() => setIsAssignReviewerModalVisible(true)}>指派部门评审人</Button>,
        <Button key="hr-decision" icon={<SolutionOutlined />} onClick={() => setIsHRDecisionModalVisible(true)}>HR直接决策</Button>
      );
    } else if (resume.status === 'pending_hr_decision') {
      buttons.push(
        <Button key="hr-decision" type="primary" icon={<SolutionOutlined />} onClick={() => setIsHRDecisionModalVisible(true)}>HR决策</Button>
      );
    } else if (resume.status === 'pending_interview') {
      // 初审通过，可以安排面试
      buttons.push(
        <Button
          key="schedule-interview"
          type="primary"
          icon={<TeamOutlined />}
          onClick={() => setIsScheduleInterviewModalVisible(true)}
        >
          安排面试
        </Button>
      );
    } else if (resume.status !== 'rejected' && resume.status !== 'completed') {
      buttons.push(
        <Button key="reject" danger icon={<CloseCircleOutlined />} onClick={() => setIsRejectModalVisible(true)}>淘汰</Button>
      );
    }

    return buttons;
  };

  // 渲染部门评审区域
  const renderDepartmentReviewSection = () => {
    if (!['pending_review', 'pending_dept_review', 'pending_hr_decision', 'rejected', 'completed', 'waitlist', 'pending_interview'].includes(resume.status)) {
      return null;
    }

    return (
      <Card
        title={<span><TeamOutlined style={{ marginRight: 8 }} />部门评审</span>}
        style={{ marginTop: 24, borderRadius: '16px' }}
        extra={['pending_review', 'pending_dept_review'].includes(resume.status) && (userRole === 'admin' || userRole === 'hr') && (
          <Button type="primary" size="small" onClick={() => setIsAssignReviewerModalVisible(true)}>指派部门评审人</Button>
        )}
      >
        {deptReviewSummary && deptReviewSummary.total_reviewers > 0 ? (
          <>
            <Row gutter={24} style={{ marginBottom: 24 }}>
              <Col span={6}>
                <Statistic title="评审人数" value={`${deptReviewSummary.completed_reviewers}/${deptReviewSummary.total_reviewers}`} />
              </Col>
              <Col span={6}>
                <Statistic
                  title="技术评分"
                  value={deptReviewSummary.avg_technical_score?.toFixed(1) || '-'}
                  suffix={deptReviewSummary.avg_technical_score ? '/10' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="经验评分"
                  value={deptReviewSummary.avg_experience_score?.toFixed(1) || '-'}
                  suffix={deptReviewSummary.avg_experience_score ? '/10' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic title="推荐比例" value={(deptReviewSummary.recommend_ratio * 100).toFixed(0)} suffix="%" />
              </Col>
            </Row>

            {deptReviewSummary.reviews && deptReviewSummary.reviews.length > 0 && (
              <List
                header="评审详情"
                dataSource={deptReviewSummary.reviews}
                renderItem={(review: any) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={<Avatar icon={<UserOutlined />} />}
                      title={
                        <Space>
                          <span>{review.reviewer_name || '评审人'}</span>
                          <Tag color={review.is_completed ? 'green' : 'default'}>
                            {review.is_completed ? '已完成' : '待评审'}
                          </Tag>
                          {review.recommendation && review.is_completed && (
                            <Tag color={review.recommendation === 'recommend' ? 'green' : review.recommendation === 'not_recommend' ? 'red' : 'gold'}>
                              {review.recommendation === 'recommend' ? '推荐' : review.recommendation === 'not_recommend' ? '不推荐' : '待定'}
                            </Tag>
                          )}
                          {(userRole === 'admin' || userRole === 'hr') && !review.is_completed && (
                            <Button size="small" onClick={() => openChangeReviewer(review)}>
                              修改评审人
                            </Button>
                          )}
                          {(userRole === 'admin' || userRole === 'hr') && (
                            <Button
                              size="small"
                              icon={<LinkOutlined />}
                              onClick={() => handleShowReviewLink(review)}
                            >
                              评审链接
                            </Button>
                          )}
                        </Space>
                      }
                      description={
                        review.is_completed ? (
                          <Space direction="vertical" style={{ width: '100%' }}>
                            <Space>
                              <Text type="secondary">技术: {review.technical_score}/10</Text>
                              <Text type="secondary">经验: {review.experience_score}/10</Text>
                              <Text type="secondary">综合: {review.overall_score}/10</Text>
                            </Space>
                            {review.comment && <Text>{review.comment}</Text>}
                          </Space>
                        ) : (
                          <Text type="secondary">等待评审</Text>
                        )
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </>
        ) : (
          <Empty description="暂无部门评审记录" />
        )}
      </Card>
    );
  };

  return (
    <div style={{ height: 'calc(100vh - 100px)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/resumes')}>返回列表</Button>
      </div>
      <div className="resume-detail-split" style={{ flex: 1, display: 'flex', flexDirection: 'row', gap: 24, overflow: 'hidden' }}>
      {/* Left: File Preview */}
      <div className="resume-detail-pane resume-preview-pane" style={{ flex: '1 1 0px', background: '#fff', borderRadius: '16px', border: '1px solid #E2E8F0', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="resume-preview-header" style={{ padding: '16px 24px', borderBottom: '1px solid #E2E8F0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#F8FAFC' }}>
          <Title level={5} style={{ margin: 0 }}>简历原件预览</Title>
          <Button type="primary" icon={<DownloadOutlined />} href={fileUrl} target="_blank" download>
            下载原件
          </Button>
        </div>
        <div style={{ flex: 1, background: '#F1F5F9' }}>
          {fileUrl ? (
            isPdf ? (
              <iframe
                src={pdfPreviewUrl}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block', background: '#fff' }}
                title="Resume Preview"
              />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748B' }}>
                <FileWordOutlined style={{ fontSize: '64px', marginBottom: '16px', color: '#3B82F6' }} />
                <Text type="secondary" style={{ marginBottom: '16px' }}>该文件格式暂不支持在线预览，请下载后查看</Text>
                <Button type="primary" href={fileUrl} download>下载文件</Button>
              </div>
            )
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#94A3B8' }}>
              暂无文件
            </div>
          )}
        </div>
      </div>

      {/* Right: AI Analysis & Details */}
      <div className="resume-detail-pane resume-analysis-pane" style={{ flex: '1 1 0px', overflowY: 'auto', paddingRight: '4px' }}>
        <Card
          bordered={false}
          style={{ borderRadius: '16px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', border: '1px solid #E2E8F0' }}
        >
          <Form form={form} component={false}>
          <div className="resume-detail-heading">
            <div className="resume-detail-candidate">
              {isEditing ? (
                  <Form.Item name="candidate_name" style={{ marginBottom: 0 }}>
                    <Input placeholder="姓名" style={{ fontSize: 24, fontWeight: 600, width: 150 }} />
                  </Form.Item>
              ) : (
                  <Title level={2} style={{ margin: 0 }}>{resume.candidate_name}</Title>
              )}

              <div style={{ marginTop: 8 }}>
                {isEditing ? (
                    <Space size={8} style={{ marginTop: 8 }}>
                      <Form.Item name="email" style={{ marginBottom: 0 }}>
                        <Input placeholder="邮箱" style={{ width: 200 }} />
                      </Form.Item>
                      <Form.Item name="contact" style={{ marginBottom: 0 }}>
                        <Input placeholder="电话" style={{ width: 150 }} />
                      </Form.Item>
                    </Space>
                ) : (
                    <Space wrap size={12}>
                        <Text
                          type="secondary"
                          ellipsis={{ tooltip: resume.email }}
                          style={{ maxWidth: 260 }}
                        >
                          {resume.email}
                        </Text>
                        <Text type="secondary">{resume.contact}</Text>
                    </Space>
                )}
              </div>
            </div>

            <div className="resume-detail-summary" style={{ textAlign: 'right' }}>
              <div style={{ textAlign: 'center' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>匹配度</Text>
                <div style={{ marginTop: 4 }}>
                  <Progress
                    type="circle"
                    percent={resume.match_score}
                    width={50}
                    format={percent => <span style={{ fontSize: 14, fontWeight: 700, color: '#0F172A' }}>{percent}%</span>}
                    strokeColor={resume.match_score >= 80 ? '#10B981' : resume.match_score >= 60 ? '#F59E0B' : '#EF4444'}
                  />
                </div>
              </div>
              <div>
                <Tag color={workflowStatusInfo.color} style={{ fontSize: 14, padding: '4px 10px', margin: 0 }}>
                  {workflowStatusInfo.text}
                </Tag>
              </div>

            </div>
          </div>

          <Space className="resume-detail-actions" wrap>
            {renderActionButtons()}
          </Space>

          <Divider style={{ borderColor: '#E2E8F0' }}>简历信息提取</Divider>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="应聘岗位">{resume.position?.title}</Descriptions.Item>
            <Descriptions.Item label="学历">
              {isEditing ? <Form.Item name="highest_degree" noStyle><Input /></Form.Item> : (parsedData.highest_degree || '未识别')}
            </Descriptions.Item>
            <Descriptions.Item label="毕业院校">
              {isEditing ? <Form.Item name="school" noStyle><Input /></Form.Item> : (parsedData.school || '未识别')}
            </Descriptions.Item>
            <Descriptions.Item label="专业">
              {isEditing ? <Form.Item name="major" noStyle><Input /></Form.Item> : (parsedData.major || '未识别')}
            </Descriptions.Item>
            <Descriptions.Item label="工作年限">
              {isEditing ? <Form.Item name="years_of_experience" noStyle><Input /></Form.Item> : `${parsedData.years_of_experience || '0'}年`}
            </Descriptions.Item>
            <Descriptions.Item label="最近公司" span={2}>
              {isEditing ? <Form.Item name="recent_company" noStyle><Input /></Form.Item> : (parsedData.recent_company || '未识别')}
            </Descriptions.Item>
            {resume.reject_reason_category && (
              <>
                <Descriptions.Item label="淘汰原因">
                  {REJECT_REASONS.find(r => r.value === resume.reject_reason_category)?.label || resume.reject_reason_category}
                </Descriptions.Item>
                <Descriptions.Item label="详细说明">{resume.reject_reason_detail || '-'}</Descriptions.Item>
              </>
            )}
          </Descriptions>

          <Divider style={{ borderColor: '#E2E8F0' }}>解析状态</Divider>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="状态">{parseStatusInfo.text}</Descriptions.Item>
            <Descriptions.Item label="解析时间">{resume.parsed_at ? dayjs(resume.parsed_at).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
            {resume.parse_status === 'failed' && (
              <Descriptions.Item label="失败原因" span={2}>{resume.parse_error || '未知'}</Descriptions.Item>
            )}
          </Descriptions>

          <Divider style={{ borderColor: '#E2E8F0' }}>AI 初审评价</Divider>
          <div style={{
            background: '#F8FAFC',
            padding: '20px',
            borderRadius: '12px',
            border: '1px solid #E2E8F0',
            color: '#334155',
            fontSize: '15px',
            lineHeight: 1.8
          }}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h3: ({node, ...props}) => <h3 style={{ color: '#0F172A', marginTop: '16px', marginBottom: '8px', fontSize: '16px' }} {...props} />,
                p: ({node, ...props}) => <p style={{ marginBottom: '12px' }} {...props} />,
                ul: ({node, ...props}) => <ul style={{ paddingLeft: '20px', marginBottom: '12px' }} {...props} />,
                li: ({node, ...props}) => <li style={{ marginBottom: '4px' }} {...props} />
              }}
            >
              {resume.ai_review || '暂无评价'}
            </ReactMarkdown>
          </div>

          {/* 其他岗位匹配推荐 */}
          {resume.other_position_matches && resume.other_position_matches.length > 0 && (
            <>
              <Divider style={{ borderColor: '#E2E8F0' }}>其他岗位匹配推荐</Divider>
              <div style={{
                background: '#F0F9FF',
                padding: '20px',
                borderRadius: '12px',
                border: '1px solid #BAE6FD',
              }}>
                <Text type="secondary" style={{ marginBottom: 12, display: 'block' }}>
                  该候选人与以下岗位也有较好的匹配度，可考虑转岗推荐
                </Text>
                <List
                  dataSource={resume.other_position_matches}
                  renderItem={(match: any) => (
                    <List.Item style={{ border: 'none', padding: '12px 0' }}>
                      <Card
                        size="small"
                        style={{ width: '100%', background: '#fff', borderRadius: 8 }}
                        bodyStyle={{ padding: '12px 16px' }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div style={{ flex: 1 }}>
                            <Space>
                              <Text strong>{match.position_title}</Text>
                              {match.is_better_match && (
                                <Tag color="green">更适合</Tag>
                              )}
                            </Space>
                            {match.reason && (
                              <Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 13 }}>
                                {match.reason}
                              </Text>
                            )}
                          </div>
                          <Space>
                            <Progress
                              type="circle"
                              percent={match.match_score}
                              width={45}
                              format={percent => <span style={{ fontSize: 12, fontWeight: 600 }}>{percent}%</span>}
                              strokeColor={match.match_score >= 80 ? '#10B981' : match.match_score >= 60 ? '#F59E0B' : '#EF4444'}
                            />
                            {(userRole === 'admin' || userRole === 'hr') && match.position_id && (
                              <Button
                                type="primary"
                                size="small"
                                onClick={() => handleTransfer(match.position_id, match.position_title)}
                              >
                                转岗
                              </Button>
                            )}
                          </Space>
                        </div>
                      </Card>
                    </List.Item>
                  )}
                />
              </div>
            </>
          )}
          </Form>
        </Card>

        {/* 部门评审区域 */}
        {renderDepartmentReviewSection()}
      </div>
      </div>

      {/* 淘汰确认弹窗 */}
      <Modal
        title="确认淘汰"
        open={isRejectModalVisible}
        onOk={handleConfirmRejection}
        onCancel={() => { setIsRejectModalVisible(false); rejectForm.resetFields(); }}
        okText="确认淘汰"
        cancelText="取消"
        okType="danger"
      >
        <Form form={rejectForm} layout="vertical" style={{ marginTop: 24 }}>
          <RejectReasonSelector />
        </Form>
      </Modal>

      {/* 指派评审人弹窗 */}
      <Modal
        title="指派部门评审人"
        open={isAssignReviewerModalVisible}
        onOk={handleAssignReviewer}
        onCancel={() => { setIsAssignReviewerModalVisible(false); deptReviewForm.resetFields(); }}
        okText="确认指派"
        cancelText="取消"
      >
        <Form form={deptReviewForm} layout="vertical" style={{ marginTop: 24 }}>
          <Form.Item
            name="reviewer_ids"
            label="选择评审人（可多选）"
            rules={[{ required: true, message: '请选择至少一位评审人' }]}
          >
            <Select
              mode="multiple"
              placeholder="请选择评审人，可多选"
              size="large"
              showSearch
              optionFilterProp="children"
              style={{ width: '100%' }}
            >
              {reviewers.map((r: any) => (
                <Select.Option key={r.id} value={r.id}>{r.full_name || r.email}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* 修改评审人弹窗 */}
      <Modal
        title="修改部门评审人"
        open={isChangeReviewerModalVisible}
        onOk={handleChangeReviewer}
        onCancel={() => {
          setIsChangeReviewerModalVisible(false);
          setSelectedReview(null);
          changeReviewerForm.resetFields();
        }}
        okText="确认修改"
        cancelText="取消"
      >
        <Form form={changeReviewerForm} layout="vertical" style={{ marginTop: 24 }}>
          <Form.Item
            name="reviewer_id"
            label="部门评审人"
            rules={[{ required: true, message: '请选择部门评审人' }]}
          >
            <Select
              placeholder="请选择部门评审人"
              size="large"
              showSearch
              optionFilterProp="children"
            >
              {reviewers.map((reviewer: any) => (
                <Select.Option key={reviewer.id} value={reviewer.id}>
                  {reviewer.full_name || reviewer.email}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* HR决策弹窗 */}
      <Modal
        title="HR决策"
        open={isHRDecisionModalVisible}
        onOk={handleHRDecision}
        onCancel={() => { setIsHRDecisionModalVisible(false); hrDecisionForm.resetFields(); }}
        okText="提交决策"
        cancelText="取消"
        width={500}
      >
        <Form form={hrDecisionForm} layout="vertical" style={{ marginTop: 24 }}>
          <Form.Item
            name="decision"
            label="决策结果"
            rules={[{ required: true, message: '请选择决策结果' }]}
          >
            <Select placeholder="请选择决策结果" size="large">
              <Select.Option value="pending_interview">进入面试</Select.Option>
              <Select.Option value="waitlist">加入备选</Select.Option>
              <Select.Option value="rejected">淘汰</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) => prevValues.decision !== currentValues.decision}
          >
            {({ getFieldValue }) =>
              getFieldValue('decision') === 'rejected' && (
                <RejectReasonSelector />
              )
            }
          </Form.Item>

          <Form.Item
            name="hr_comment"
            label="HR备注"
          >
            <TextArea rows={3} placeholder="请输入备注信息（可选）" maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* 提交评审弹窗 */}
      <Modal
        title="提交部门评审"
        open={isSubmitReviewModalVisible}
        onOk={handleSubmitReview}
        onCancel={() => { setIsSubmitReviewModalVisible(false); submitReviewForm.resetFields(); }}
        okText="提交评审"
        cancelText="取消"
        width={500}
      >
        <Form form={submitReviewForm} layout="vertical" style={{ marginTop: 24 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="technical_score"
                label="技术评分"
                extra="1-10分"
              >
                <Select placeholder="技术评分" size="large">
                  {[1,2,3,4,5,6,7,8,9,10].map(n => (
                    <Select.Option key={n} value={n}>{n}分</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="experience_score"
                label="经验评分"
                extra="1-10分"
              >
                <Select placeholder="经验评分" size="large">
                  {[1,2,3,4,5,6,7,8,9,10].map(n => (
                    <Select.Option key={n} value={n}>{n}分</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="overall_score"
                label="综合评分"
                extra="1-10分"
              >
                <Select placeholder="综合评分" size="large">
                  {[1,2,3,4,5,6,7,8,9,10].map(n => (
                    <Select.Option key={n} value={n}>{n}分</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="recommendation"
            label="推荐意见"
            rules={[{ required: true, message: '请选择推荐意见' }]}
          >
            <Select placeholder="请选择推荐意见" size="large">
              <Select.Option value="recommend">推荐</Select.Option>
              <Select.Option value="not_recommend">不推荐</Select.Option>
              <Select.Option value="pending">待定</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="comment"
            label="评审意见"
          >
            <TextArea rows={4} placeholder="请输入详细评审意见（可选）" maxLength={1000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {isScheduleInterviewModalVisible && (
        <ScheduleInterviewModal
          open
          resume={{ id: resume.id, position_id: resume.position_id }}
          onClose={() => setIsScheduleInterviewModalVisible(false)}
        />
      )}
    </div>
  );
};

export default ResumeDetail;
