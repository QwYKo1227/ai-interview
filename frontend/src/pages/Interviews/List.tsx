import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Table, Button, Space, message, Tag, Modal, Tooltip, Select, Input, Form, DatePicker, InputNumber, Row, Col, Checkbox, Typography, Card, Segmented } from 'antd';
import { PlusOutlined, DeleteOutlined, PlayCircleOutlined, EyeOutlined, StopOutlined, TeamOutlined, SendOutlined, EditOutlined, UnorderedListOutlined, CalendarOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import dayjs from 'dayjs';
import InterviewCalendar from './InterviewCalendar';
import {
  buildInterviewTimePayload,
  defaultInterviewEnd,
  formatInterviewRange,
  getScheduleErrorMessage,
  INTERVIEW_MINUTE_STEP,
  toBeijingTime,
  validateInterviewTimeRange,
} from './interviewSchedule';

export const SCHEDULABLE_RESUME_STATUSES = ['pending_interview', 'pending_next_interview'] as const;

export const mergeSchedulableResumes = (groups: any[][]) => (
  Array.from(new Map(groups.flat().map((resume) => [resume.id, resume])).values())
);

const { Text } = Typography;

export const getInterviewProgress = (record: any) => {
  if (record.lifecycle_state === 'cancelled' || record.status === 'cancelled') return 'cancelled';
  if (record.final_decision_at) return 'decided';
  if (record.lifecycle_state === 'ended') return 'pending_decision';
  if (record.lifecycle_state === 'ending') return 'ending';
  return record.lifecycle_state || record.status;
};

export const normalizeInterviewResult = (result?: string) => {
  if (result === 'hired') return 'passed';
  if (result === 'waitlist') return 'pending';
  return result || 'pending';
};

export type InterviewListFilters = {
  candidateId?: string;
  positionId?: string;
  interviewerId?: string;
  status?: string;
  result?: string;
};

export const createEmptyInterviewListFilters = (): InterviewListFilters => ({});

export const getInterviewMemberIds = (record: any): string[] => {
  const panelMemberIds = Array.isArray(record?.panel_members) ? record.panel_members : [];
  const panelIds = Array.isArray(record?.panels)
    ? record.panels.map((panel: any) => panel?.interviewer_id)
    : [];

  return Array.from(new Set([...panelMemberIds, ...panelIds]
    .filter(Boolean)
    .map((id) => String(id))));
};

export const matchesInterviewFilters = (
  record: any,
  filters: InterviewListFilters,
) => {
  const resumeId = String(record?.resume_id || record?.resume?.id || '');
  const positionId = String(record?.position_id || record?.position?.id || '');

  return (!filters.candidateId || resumeId === filters.candidateId)
    && (!filters.positionId || positionId === filters.positionId)
    && (!filters.interviewerId || getInterviewMemberIds(record).includes(filters.interviewerId))
    && (!filters.status || getInterviewProgress(record) === filters.status)
    && (!filters.result || normalizeInterviewResult(record?.result) === filters.result);
};

export const buildInterviewSchedulePayload = (values: any) => ({
  panel_members: values.panel_members,
  ...buildInterviewTimePayload(values),
  interview_type: values.interview_type,
  interview_location: values.interview_type === 'onsite' ? values.interview_location : null,
  meeting_link: values.interview_type === 'video' ? values.meeting_link : null,
});

const InterviewsList: React.FC = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [calendarData, setCalendarData] = useState<any[]>([]);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarRange, setCalendarRange] = useState<{ start: Date; end: Date } | null>(null);
  const [calendarDraft, setCalendarDraft] = useState<{ date: dayjs.Dayjs; start: dayjs.Dayjs | null } | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'calendar'>(() => (
    localStorage.getItem('interview-management-view') === 'calendar' ? 'calendar' : 'list'
  ));
  const [filters, setFilters] = useState<InterviewListFilters>(createEmptyInterviewListFilters);
  const [interviewerNameMap, setInterviewerNameMap] = useState<Record<string, string>>({});
  const [cancelModalVisible, setCancelModalVisible] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [selectedInterviewId, setSelectedInterviewId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [sendCancelNotification, setSendCancelNotification] = useState(true);
  
  const [selectResumeModalVisible, setSelectResumeModalVisible] = useState(false);
  const [pendingInterviewResumes, setPendingInterviewResumes] = useState<any[]>([]);
  const [loadingResumes, setLoadingResumes] = useState(false);
  const [selectedResume, setSelectedResume] = useState<any>(null);
  const [interviewModalVisible, setInterviewModalVisible] = useState(false);
  const [existingInterviews, setExistingInterviews] = useState<any[]>([]);
  const [interviewers, setInterviewers] = useState([]);
  const [filterInterviewers, setFilterInterviewers] = useState<any[]>([]);
  const [questionBanks, setQuestionBanks] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [interviewForm] = Form.useForm();
  const [emailPreviewVisible, setEmailPreviewVisible] = useState(false);
  const [emailContent, setEmailContent] = useState<any>(null);
  const [pendingInterviewData, setPendingInterviewData] = useState<any>(null);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [emailForm] = Form.useForm();
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [scheduleModalVisible, setScheduleModalVisible] = useState(false);
  const [scheduleEmailVisible, setScheduleEmailVisible] = useState(false);
  const [editingInterview, setEditingInterview] = useState<any>(null);
  const [pendingSchedule, setPendingSchedule] = useState<any>(null);
  const [scheduleEmailPreview, setScheduleEmailPreview] = useState<any>(null);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleSaved, setScheduleSaved] = useState(false);
  const [notificationFailures, setNotificationFailures] = useState<Record<string, string[]>>({});
  const [scheduleForm] = Form.useForm();
  const [scheduleEmailForm] = Form.useForm();
  
  const navigate = useNavigate();
  const { user } = useAuth();

  // 判断是否可以取消面试（仅 HR/Admin 可见）
  const canCancelInterview = user?.role === 'admin' || user?.role === 'hr';
  // 判断是否可以删除面试（仅 HR/Admin 可见）
  const canDeleteInterview = user?.role === 'admin';

  const handleOpenScheduleEdit = (record: any) => {
    setEditingInterview(record);
    setScheduleSaved(false);
    setNotificationFailures({});
    scheduleForm.setFieldsValue({
      panel_members: record.panel_members || [],
      interview_time: record.interview_time ? dayjs(record.interview_time) : null,
      interview_end_time: record.interview_end_time
        ? dayjs(record.interview_end_time)
        : (record.interview_time ? dayjs(record.interview_time).add(60, 'minute') : null),
      interview_type: record.interview_type || 'onsite',
      interview_location: record.interview_location || undefined,
      meeting_link: record.meeting_link || undefined,
    });
    setScheduleModalVisible(true);
  };

  const handlePreviewScheduleEmails = async () => {
    if (!editingInterview) return;
    try {
      const values = await scheduleForm.validateFields();
      const payload = buildInterviewSchedulePayload(values);
      setScheduleSaving(true);
      const preview = await request.post(`/interviews/${editingInterview.id}/schedule-email-preview`, payload);
      setPendingSchedule(payload);
      setScheduleEmailPreview(preview);
      scheduleEmailForm.setFieldsValue({
        notify_current: preview.current.default_enabled,
        current_subject: preview.current.subject,
        current_content: preview.current.content,
        notify_removed: preview.removed.default_enabled,
        removed_subject: preview.removed.subject,
        removed_content: preview.removed.content,
      });
      setScheduleModalVisible(false);
      setScheduleEmailVisible(true);
    } catch (error) {
      message.error(getScheduleErrorMessage(error, '无法预览面试安排变更'));
    } finally {
      setScheduleSaving(false);
    }
  };

  const sendScheduleNotificationGroup = async (
    group: 'current' | 'removed',
    values: any,
    recipientIds?: string[],
  ) => {
    const preview = scheduleEmailPreview?.[group];
    const enabled = values[`notify_${group}`];
    const ids = recipientIds || preview?.recipients?.map((item: any) => item.id) || [];
    if (!enabled || ids.length === 0) return [];
    try {
      const result = await request.post(`/interviews/${editingInterview.id}/schedule-notifications`, {
        recipient_ids: ids,
        subject: values[`${group}_subject`],
        content: values[`${group}_content`],
        preview_token: scheduleEmailPreview?.notification_token,
      });
      return result.failed || [];
    } catch {
      return ids;
    }
  };

  const handleSaveSchedule = async () => {
    if (!editingInterview || !pendingSchedule) return;
    try {
      const values = await scheduleEmailForm.validateFields();
      setScheduleSaving(true);
      if (!scheduleSaved) {
        await request.put(`/interviews/${editingInterview.id}/schedule`, pendingSchedule);
        setScheduleSaved(true);
        await refreshInterviews();
      }
      const currentFailures = await sendScheduleNotificationGroup(
        'current', values, notificationFailures.current,
      );
      const removedFailures = await sendScheduleNotificationGroup(
        'removed', values, notificationFailures.removed,
      );
      const failures = { current: currentFailures, removed: removedFailures };
      setNotificationFailures(failures);
      if (currentFailures.length || removedFailures.length) {
        message.warning('面试安排已更新，但部分邮件发送失败，可重试失败邮件');
        return;
      }
      message.success('面试安排已更新，所选通知已发送');
      setScheduleEmailVisible(false);
      setEditingInterview(null);
      setPendingSchedule(null);
    } catch (error) {
      message.error(getScheduleErrorMessage(error, scheduleSaved ? '邮件重试失败' : '更新面试安排失败'));
    } finally {
      setScheduleSaving(false);
    }
  };

  const fetchInterviews = async () => {
    setLoading(true);
    try {
      const res = await request.get('/interviews');
      setData(res);
    } catch (error) {
      message.error('获取面试列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchCalendarInterviews = useCallback(async (start: Date, end: Date) => {
    setCalendarLoading(true);
    try {
      const res = await request.get('/interviews', {
        params: { start: start.toISOString(), end: end.toISOString(), limit: 10000 },
      });
      setCalendarData(res || []);
    } catch {
      message.error('获取面试日历失败');
    } finally {
      setCalendarLoading(false);
    }
  }, []);

  const fetchFilterInterviewers = useCallback(async () => {
    try {
      const res = await request.get('/interviews/filter-options/interviewers');
      setFilterInterviewers(res || []);
    } catch {
      setFilterInterviewers([]);
    }
  }, []);

  const handleCalendarRangeChange = useCallback((start: Date, end: Date) => {
    setCalendarRange((current) => {
      if (current?.start.getTime() === start.getTime() && current?.end.getTime() === end.getTime()) return current;
      void fetchCalendarInterviews(start, end);
      return { start, end };
    });
  }, [fetchCalendarInterviews]);

  const refreshInterviews = async () => {
    const tasks: Promise<unknown>[] = [fetchInterviews(), fetchFilterInterviewers()];
    if (calendarRange) tasks.push(fetchCalendarInterviews(calendarRange.start, calendarRange.end));
    await Promise.all(tasks);
  };

  useEffect(() => {
    fetchInterviews();
    void fetchFilterInterviewers();
  }, [fetchFilterInterviewers]);

  useEffect(() => {
    request.get('/auth/interviewers')
      .then((res: any) => {
        const map: Record<string, string> = {};
        (res || []).forEach((u: any) => {
          const name = u?.full_name || u?.email || u?.id;
          if (u?.id) map[String(u.id)] = name;
        });
        setInterviewerNameMap(map);
        setInterviewers(res || []);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    request.get('/question-banks')
      .then((res: any) => {
        setQuestionBanks(res || []);
      })
      .catch(() => {});
  }, []);

  const filterOptionSource = useMemo(() => (
    Array.from(new Map([...(data as any[]), ...calendarData].map((item) => [String(item.id), item])).values())
  ), [data, calendarData]);

  const candidateOptions = useMemo(() => Array.from(
    new Map(filterOptionSource
      .map((interview) => {
        const value = String(interview?.resume_id || interview?.resume?.id || '');
        return [value, { value, label: interview?.resume?.candidate_name || '未知候选人' }] as const;
      })
      .filter(([value]) => value)).values(),
  ), [filterOptionSource]);

  const positionOptions = useMemo(() => Array.from(
    new Map(filterOptionSource
      .map((interview) => {
        const value = String(interview?.position_id || interview?.position?.id || '');
        return [value, { value, label: interview?.position?.title || '未知岗位' }] as const;
      })
      .filter(([value]) => value)).values(),
  ), [filterOptionSource]);

  const interviewerOptions = useMemo(() => filterInterviewers.map((interviewer) => ({
    value: String(interviewer.id),
    label: interviewer.full_name || interviewer.email || String(interviewer.id),
  })), [filterInterviewers]);

  const filteredData = useMemo(
    () => (data as any[]).filter((interview) => matchesInterviewFilters(interview, filters)),
    [data, filters],
  );

  const filteredCalendarData = useMemo(
    () => calendarData.filter((interview) => matchesInterviewFilters(interview, filters)),
    [calendarData, filters],
  );

  const getInterviewerText = (record: any) => {
    const members = Array.isArray(record?.panel_members) ? record.panel_members : [];
    if (members.length > 0) {
      return members.map((id: any) => interviewerNameMap[String(id)] || String(id)).join('、');
    }
    return record?.interviewer || '-';
  };

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这条面试记录吗？此操作不可恢复。',
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await request.delete(`/interviews/${id}`);
          message.success('删除成功');
          refreshInterviews();
        } catch (error) {
          message.error('删除失败');
        }
      },
    });
  };

  const handleOpenCancelModal = (id: string) => {
    setSelectedInterviewId(id);
    setCancelReason('');
    setSendCancelNotification(true);
    setCancelModalVisible(true);
  };

  const handleCancelInterview = async () => {
    if (!selectedInterviewId) return;

    if (!cancelReason.trim()) {
      message.error('请输入取消原因');
      return;
    }

    setCancelling(true);
    try {
      const response = await request.post(`/interviews/${selectedInterviewId}/cancel`, undefined, {
        params: { reason: cancelReason.trim(), notify: sendCancelNotification },
      }) as any;
      if (sendCancelNotification && !response?.notification_sent) {
        message.warning('面试已取消，但通知发送失败，可在列表中重新发送');
      } else {
        message.success('面试已取消');
      }
      setCancelModalVisible(false);
      setCancelReason('');
      setSelectedInterviewId(null);
      refreshInterviews();
    } catch (error) {
      message.error('取消面试失败');
    } finally {
      setCancelling(false);
    }
  };

  const handleRetryCancelNotification = async (id: string) => {
    try {
      const response = await request.post(`/interviews/${id}/cancel-notification`) as any;
      if (response?.success) {
        message.success('取消通知已发送');
      } else {
        message.error('取消通知发送失败');
      }
    } catch (error) {
      message.error('取消通知发送失败');
    }
  };

  const openSelectResume = async () => {
    setLoadingResumes(true);
    setSelectResumeModalVisible(true);
    try {
      const groups = await Promise.all(
        SCHEDULABLE_RESUME_STATUSES.map((status) => (
          request.get('/resumes', { params: { status } }) as Promise<any[]>
        )),
      );
      setPendingInterviewResumes(mergeSchedulableResumes(groups.map((group) => group || [])));
    } catch (error) {
      message.error('获取简历列表失败');
    } finally {
      setLoadingResumes(false);
    }
  };

  const handleOpenSelectResume = () => {
    setCalendarDraft(null);
    void openSelectResume();
  };

  const handleCalendarEmptyDoubleClick = (date: Date, allDay: boolean) => {
    if (!canCancelInterview) return;
    const beijingDate = toBeijingTime(date);
    if (!beijingDate) return;
    setCalendarDraft({
      date: beijingDate.startOf('day'),
      start: allDay ? null : beijingDate,
    });
    void openSelectResume();
  };

  const handleSelectResume = (record: any) => {
    setSelectedResume(record);
    setSelectResumeModalVisible(false);
    handleCreateInterviewClick(record);
  };

  const handleCreateInterviewClick = async (record: any) => {
    interviewForm.resetFields();

    try {
      const allInterviews = await request.get('/interviews') as any[];
      const resumeInterviews = allInterviews.filter((i: any) => i.resume_id === record.id);
      setExistingInterviews(resumeInterviews);

      const maxRound = resumeInterviews.reduce((max: number, i: any) => Math.max(max, i.round || 1), 0);
      interviewForm.setFieldsValue({
        question_count: 5,
        interview_type: 'onsite',
        interview_category: 'technical',
        round: maxRound + 1,
        interview_time: calendarDraft?.start,
        interview_end_time: calendarDraft?.start ? defaultInterviewEnd(calendarDraft.start) : null,
      });
    } catch (error) {
      console.error('获取面试记录失败', error);
      interviewForm.setFieldsValue({
        question_count: 5,
        interview_type: 'onsite',
        round: 1,
        interview_time: calendarDraft?.start,
        interview_end_time: calendarDraft?.start ? defaultInterviewEnd(calendarDraft.start) : null,
      });
    }

    setInterviewModalVisible(true);
  };

  const handleInterviewOk = async () => {
    try {
      const values = await interviewForm.validateFields();
      setSubmitting(true);

      const interviewData = {
        resume_id: selectedResume.id,
        position_id: selectedResume.position_id,
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
        skip_ai_questions: values.skip_ai_questions || false
      };

      setPendingInterviewData(interviewData);

      try {
        const emailPreview = await request.post('/interviews/email-preview', {
          resume_id: selectedResume.id,
          position_id: selectedResume.position_id,
          panel_members: values.panel_members,
          ...buildInterviewTimePayload(values),
          round: values.round || 1,
          interview_type: values.interview_type || 'onsite',
          interview_category: values.interview_category || 'technical',
          interview_location: values.interview_location,
          meeting_link: values.meeting_link
        });

        setEmailContent(emailPreview);
        emailForm.setFieldsValue({
          subject: emailPreview.subject,
          content: emailPreview.content,
          send_email: true
        });
        setInterviewModalVisible(false);
        setEmailPreviewVisible(true);
      } catch (error) {
        console.error('获取邮件预览失败', error);
        const res = await request.post('/interviews', {
          ...interviewData,
          skip_email: true
        });
        message.success('面试安排成功');
        setInterviewModalVisible(false);
        refreshInterviews();
        navigate(`/interviews/${res.id}/score`);
      }
    } catch (error) {
      message.error(getScheduleErrorMessage(error, '安排面试失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmAndSend = async () => {
    try {
      const values = await emailForm.validateFields();
      setSendingEmail(true);

      const res = await request.post('/interviews', {
        ...pendingInterviewData,
        skip_email: true
      });

      if (values.send_email && res.id) {
        try {
          await request.post(`/interviews/${res.id}/send-email`, {
            subject: values.subject,
            content: values.content
          });
          message.success('面试安排成功，邮件已发送');
        } catch (error) {
          message.warning('面试安排成功，但邮件发送失败');
        }
      } else {
        message.success('面试安排成功');
      }

      setEmailPreviewVisible(false);
      refreshInterviews();
      navigate(`/interviews/${res.id}/score`);
    } catch (error) {
      message.error(getScheduleErrorMessage(error, '安排面试失败'));
    } finally {
      setSendingEmail(false);
    }
  };

  const handleCancelPreview = () => {
    setEmailPreviewVisible(false);
    setInterviewModalVisible(true);
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的面试');
      return;
    }
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 个面试吗？`,
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await Promise.all(selectedRowKeys.map(id => request.delete(`/interviews/${id}`)));
          message.success(`成功删除 ${selectedRowKeys.length} 个面试`);
          setSelectedRowKeys([]);
          refreshInterviews();
        } catch (error) {
          message.error('批量删除失败');
        }
      },
    });
  };

  const renderInterviewActions = (record: any) => {
    const isPendingConfirmation = record.status !== 'completed'
      && record.result === 'pending'
      && record.scores
      && Object.keys(record.scores).length > 0;
    return (
      <Space size="small">
        {(record.lifecycle_state || record.status) === 'scheduled' && (
          <Tooltip title="进入面试">
            <Button type="text" icon={<PlayCircleOutlined style={{ color: '#3B82F6' }} />} onClick={() => navigate(`/interviews/${record.id}/score`)} />
          </Tooltip>
        )}
        {canCancelInterview && (record.lifecycle_state || record.status) === 'scheduled' && (
          <Tooltip title="编辑面试安排">
            <Button type="text" icon={<EditOutlined />} onClick={() => handleOpenScheduleEdit(record)} />
          </Tooltip>
        )}
        {(record.lifecycle_state || record.status) === 'in_progress' && (
          <Tooltip title="继续面试">
            <Button type="text" icon={<PlayCircleOutlined style={{ color: '#F97316' }} />} onClick={() => navigate(`/interviews/${record.id}/score`)} />
          </Tooltip>
        )}
        {(record.lifecycle_state === 'ended' || record.status === 'completed' || isPendingConfirmation) && (
          <Tooltip title={isPendingConfirmation ? '确认结果' : '查看结果'}>
            <Button type="text" icon={<EyeOutlined style={{ color: isPendingConfirmation ? '#F59E0B' : '#10B981' }} />} onClick={() => navigate(`/interviews/${record.id}/result`)} />
          </Tooltip>
        )}
        {canCancelInterview && (record.lifecycle_state || record.status) === 'scheduled' && (
          <Tooltip title="取消面试">
            <Button type="text" danger icon={<StopOutlined />} onClick={() => handleOpenCancelModal(record.id)} />
          </Tooltip>
        )}
        {canCancelInterview && getInterviewProgress(record) === 'cancelled' && (
          <Tooltip title="重新发送取消通知">
            <Button type="text" icon={<SendOutlined />} onClick={() => handleRetryCancelNotification(record.id)} />
          </Tooltip>
        )}
        {canDeleteInterview && ['scheduled', 'cancelled'].includes(getInterviewProgress(record)) && (
          <Tooltip title="删除">
            <Button type="text" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
          </Tooltip>
        )}
      </Space>
    );
  };

  const columns = [
    {
      title: '候选人',
      dataIndex: ['resume', 'candidate_name'],
      key: 'candidate_name',
      render: (text: string) => <span style={{ fontWeight: 500, color: '#0F172A' }}>{text || '未知'}</span>
    },
    {
      title: '岗位',
      dataIndex: ['position', 'title'],
      key: 'position',
      render: (text: string) => <span style={{ color: '#64748B' }}>{text || '未知'}</span>
    },
    {
      title: '轮次',
      dataIndex: 'round',
      key: 'round',
      width: 80,
      render: (round: number) => (
        <Tag color="purple" style={{ border: 'none' }}>
          第{round || 1}轮
        </Tag>
      )
    },
    {
      title: '面试官',
      key: 'interviewer',
      render: (_: any, record: any) => {
        const full = getInterviewerText(record);
        return (
          <Tooltip title={full}>
            <span
              style={{
                display: 'inline-block',
                maxWidth: 220,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                verticalAlign: 'bottom',
              }}
            >
              {full}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '面试时间',
      dataIndex: 'interview_time',
      key: 'interview_time',
      sorter: (a: any, b: any) => {
        const at = a?.interview_time ? new Date(a.interview_time).getTime() : 0;
        const bt = b?.interview_time ? new Date(b.interview_time).getTime() : 0;
        return at - bt;
      },
      render: (_: string, record: any) => {
        const range = formatInterviewRange(record);
        return range.estimated
          ? <Tooltip title="历史记录未填写结束时间，按 60 分钟预计"><span>{range.text}（预计）</span></Tooltip>
          : range.text;
      }
    },
    {
      title: '总分',
      key: 'total_score',
      render: (_, record: any) => {
        if (!record.scores) return '-';
        const values = Object.values(record.scores) as number[];
        if (values.length === 0) return '-';
        const sum = values.reduce((a, b) => a + b, 0);
        const avg = (sum / values.length).toFixed(1);
        return <span style={{ fontWeight: 600, color: '#0F172A' }}>{avg}</span>;
      }
    },
    {
      title: '面试进度',
      key: 'progress',
      render: (_: unknown, record: any) => {
        const map: Record<string, {text: string, color: string}> = {
          scheduled: { text: '待面试', color: 'blue' },
          in_progress: { text: '面试中', color: 'orange' },
          ending: { text: '正在结束', color: 'gold' },
          pending_decision: { text: '待确认面试结果', color: 'purple' },
          decided: { text: '已确认', color: 'green' },
          cancelled: { text: '已取消', color: 'default' },
        };
        const progress = getInterviewProgress(record);
        const info = map[progress] || { text: progress, color: 'default' };
        const tag = <Tag color={info.color} style={{ border: 'none' }}>{info.text}</Tag>;
        const cancellationDetails = [
          record.cancel_reason ? `取消原因：${record.cancel_reason}` : '',
          record.cancelled_at ? `取消时间：${new Date(record.cancelled_at).toLocaleString()}` : '',
        ].filter(Boolean).join('；');
        return progress === 'cancelled' && cancellationDetails
          ? <Tooltip title={cancellationDetails}>{tag}</Tooltip>
          : tag;
      }
    },
    {
      title: '面试结果',
      key: 'result',
      render: (_: unknown, record: any) => {
        const map: Record<string, {text: string, color: string}> = {
          pending: { text: '未出结果', color: 'default' },
          next_round: { text: '进入下一轮', color: 'blue' },
          passed: { text: '通过', color: 'green' },
          rejected: { text: '淘汰', color: 'red' },
        };
        const result = normalizeInterviewResult(record.result);
        const info = map[result] || { text: result, color: 'default' };
        return <Tag color={info.color} style={{ border: 'none' }}>{info.text}</Tag>;
      }
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: any) => renderInterviewActions(record),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Segmented
          value={viewMode}
          options={[
            { value: 'list', label: '列表', icon: <UnorderedListOutlined /> },
            { value: 'calendar', label: '日历', icon: <CalendarOutlined /> },
          ]}
          onChange={(value) => {
            const nextMode = value as 'list' | 'calendar';
            localStorage.setItem('interview-management-view', nextMode);
            setViewMode(nextMode);
          }}
        />
        {(user?.role === 'admin' || user?.role === 'hr') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={handleOpenSelectResume}>安排面试</Button>
        )}
      </div>
      <Card
        className="interviews-filter-bar"
        style={{ marginBottom: 24, borderRadius: '8px' }}
        styles={{ body: { padding: '24px' } }}
      >
        <Form layout="inline">
          <Form.Item label="候选人">
            <Select
              placeholder="请选择候选人"
              allowClear
              showSearch
              optionFilterProp="label"
              value={filters.candidateId}
              options={candidateOptions}
              onChange={(candidateId) => setFilters((current) => ({ ...current, candidateId }))}
              style={{ width: 180 }}
            />
          </Form.Item>
          <Form.Item label="岗位">
            <Select
              placeholder="请选择岗位"
              allowClear
              showSearch
              optionFilterProp="label"
              value={filters.positionId}
              options={positionOptions}
              onChange={(positionId) => setFilters((current) => ({ ...current, positionId }))}
              style={{ width: 180 }}
            />
          </Form.Item>
          <Form.Item label="面试官">
            <Select
              placeholder="请选择面试官"
              allowClear
              showSearch
              optionFilterProp="label"
              value={filters.interviewerId}
              options={interviewerOptions}
              onChange={(interviewerId) => setFilters((current) => ({ ...current, interviewerId }))}
              style={{ width: 180 }}
            />
          </Form.Item>
          <Form.Item label="面试进度">
          <Select
            placeholder="筛选面试进度"
            allowClear
            value={filters.status}
            onChange={(status) => setFilters((current) => ({ ...current, status }))}
            style={{ width: 160 }}
            options={[
              { value: 'scheduled', label: '待面试' },
              { value: 'in_progress', label: '面试中' },
              { value: 'ending', label: '正在结束' },
              { value: 'pending_decision', label: '待确认面试结果' },
              { value: 'decided', label: '已确认' },
              { value: 'cancelled', label: '已取消' },
            ]}
          />
          </Form.Item>
          <Form.Item label="面试结果">
          <Select
            placeholder="筛选面试结果"
            allowClear
            value={filters.result}
            onChange={(result) => setFilters((current) => ({ ...current, result }))}
            style={{ width: 160 }}
            options={[
              { value: 'pending', label: '未出结果' },
              { value: 'next_round', label: '进入下一轮' },
              { value: 'passed', label: '通过' },
              { value: 'rejected', label: '淘汰' },
            ]}
          />
          </Form.Item>
          {viewMode === 'list' && selectedRowKeys.length > 0 && canDeleteInterview && (
            <>
              <Form.Item><span style={{ color: '#64748B' }}>已选 {selectedRowKeys.length} 项</span></Form.Item>
              <Form.Item><Button danger onClick={handleBatchDelete}>批量删除</Button></Form.Item>
              <Form.Item><Button onClick={() => setSelectedRowKeys([])}>取消选择</Button></Form.Item>
            </>
          )}
          <Form.Item>
            <Button onClick={() => setFilters(createEmptyInterviewListFilters())}>重置</Button>
          </Form.Item>
        </Form>
      </Card>
      {viewMode === 'list' ? (
        <Table
          columns={columns}
          dataSource={filteredData}
          loading={loading}
          rowKey="id"
          pagination={{ pageSize: 10, showSizeChanger: true }}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
            getCheckboxProps: (record: any) => ({
              disabled: !canDeleteInterview || !['scheduled', 'cancelled'].includes(getInterviewProgress(record)),
            }),
          }}
        />
      ) : (
        <InterviewCalendar
          interviews={filteredCalendarData}
          loading={calendarLoading}
          interviewerNameMap={interviewerNameMap}
          onRangeChange={handleCalendarRangeChange}
          onEmptyDoubleClick={handleCalendarEmptyDoubleClick}
          renderActions={renderInterviewActions}
        />
      )}

      <Modal
        title="编辑面试安排"
        open={scheduleModalVisible}
        onOk={handlePreviewScheduleEmails}
        onCancel={() => setScheduleModalVisible(false)}
        confirmLoading={scheduleSaving}
        okText="下一步：邮件通知"
        cancelText="取消"
        width={680}
        destroyOnClose
      >
        <Form form={scheduleForm} layout="vertical" preserve>
          <Form.Item
            name="panel_members"
            label="面试官"
            rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一位面试官' }]}
          >
            <Select mode="multiple" placeholder="选择面试官" optionFilterProp="children">
              {interviewers.map((interviewer: any) => (
                <Select.Option key={interviewer.id} value={interviewer.id}>
                  {interviewer.full_name || interviewer.email}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="interview_time"
                label="开始时间"
                rules={[{ required: true, message: '请选择开始时间' }]}
              >
                <DatePicker
                  showTime={{ format: 'HH:mm', minuteStep: INTERVIEW_MINUTE_STEP }}
                  format="YYYY-MM-DD HH:mm"
                  style={{ width: '100%' }}
                  onChange={(value) => {
                    const currentEnd = scheduleForm.getFieldValue('interview_end_time');
                    if (value && (!currentEnd || !currentEnd.isAfter(value))) {
                      scheduleForm.setFieldValue('interview_end_time', defaultInterviewEnd(value));
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
                <DatePicker showTime={{ format: 'HH:mm', minuteStep: INTERVIEW_MINUTE_STEP }} format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="interview_type"
            label="面试形式"
            rules={[{ required: true, message: '请选择面试形式' }]}
          >
            <Select
              options={[
                { value: 'onsite', label: '现场面试' },
                { value: 'video', label: '视频面试' },
                { value: 'phone', label: '电话面试' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(previous, current) => previous.interview_type !== current.interview_type}>
            {({ getFieldValue }) => getFieldValue('interview_type') === 'onsite' ? (
              <Form.Item
                name="interview_location"
                label="面试地点"
                rules={[{ required: true, whitespace: true, message: '请输入面试地点' }]}
              >
                <Input placeholder="请输入现场面试地点" />
              </Form.Item>
            ) : getFieldValue('interview_type') === 'video' ? (
              <Form.Item
                name="meeting_link"
                label="会议链接"
                rules={[{ required: true, whitespace: true, message: '请输入会议链接' }]}
              >
                <Input placeholder="请输入视频会议链接" />
              </Form.Item>
            ) : null}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="确认面试官邮件通知"
        open={scheduleEmailVisible}
        onCancel={() => {
          setScheduleEmailVisible(false);
          if (!scheduleSaved) setScheduleModalVisible(true);
        }}
        width={860}
        destroyOnClose
        footer={[
          <Button key="cancel" onClick={() => {
            setScheduleEmailVisible(false);
            if (!scheduleSaved) setScheduleModalVisible(true);
          }}>
            {scheduleSaved ? '关闭' : '返回修改'}
          </Button>,
          <Button key="save" type="primary" loading={scheduleSaving} onClick={handleSaveSchedule}>
            {(notificationFailures.current?.length || notificationFailures.removed?.length)
              ? '重试失败邮件'
              : '保存并发送所选通知'}
          </Button>,
        ]}
      >
        <Form form={scheduleEmailForm} layout="vertical" preserve>
          {(['current', 'removed'] as const).map((group) => {
            const preview = scheduleEmailPreview?.[group];
            const label = group === 'current' ? '通知当前面试官' : '通知被移除的面试官';
            const recipientText = preview?.recipients?.map((item: any) => (
              `${item.name}${item.email ? ` <${item.email}>` : '（无邮箱）'}`
            )).join('、') || '无';
            return (
              <div key={group} style={{ marginBottom: 20, padding: 16, border: '1px solid #e5e7eb', borderRadius: 8 }}>
                <Form.Item name={`notify_${group}`} valuePropName="checked" style={{ marginBottom: 8 }}>
                  <Checkbox disabled={!preview?.recipients?.length}>{label}</Checkbox>
                </Form.Item>
                <Text type="secondary">收件人：{recipientText}</Text>
                <Form.Item
                  name={`${group}_subject`}
                  label="邮件主题"
                  rules={[{ required: true, whitespace: true, message: '请输入邮件主题' }]}
                  style={{ marginTop: 12 }}
                >
                  <Input />
                </Form.Item>
                <Form.Item
                  name={`${group}_content`}
                  label="邮件正文"
                  rules={[{ required: true, whitespace: true, message: '请输入邮件正文' }]}
                >
                  <Input.TextArea rows={7} style={{ fontFamily: 'monospace' }} />
                </Form.Item>
                <Form.Item noStyle shouldUpdate>
                  {({ getFieldValue }) => (
                    <div
                      style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 12, maxHeight: 220, overflow: 'auto' }}
                      dangerouslySetInnerHTML={{ __html: getFieldValue(`${group}_content`) || '' }}
                    />
                  )}
                </Form.Item>
                {!!notificationFailures[group]?.length && (
                  <Text type="danger">{notificationFailures[group].length} 封邮件发送失败</Text>
                )}
              </div>
            );
          })}
        </Form>
      </Modal>

      {/* 取消面试弹窗 */}
      <Modal
        title="取消面试"
        open={cancelModalVisible}
        onOk={handleCancelInterview}
        onCancel={() => setCancelModalVisible(false)}
        confirmLoading={cancelling}
        okText="确认取消"
        cancelText="返回"
        okButtonProps={{ danger: true }}
      >
        <p style={{ marginBottom: 12, color: '#64748B' }}>请输入取消面试的原因：</p>
        <Input.TextArea
          rows={3}
          value={cancelReason}
          onChange={(e) => setCancelReason(e.target.value)}
          placeholder="请输入取消原因..."
          maxLength={500}
          showCount
        />
        <Checkbox
          checked={sendCancelNotification}
          onChange={(event) => setSendCancelNotification(event.target.checked)}
          style={{ marginTop: 12 }}
        >
          通知候选人和面试官
        </Checkbox>
      </Modal>

      {/* 选择简历弹窗 */}
      <Modal
        title="选择候选人"
        open={selectResumeModalVisible}
        onCancel={() => setSelectResumeModalVisible(false)}
        footer={null}
        width={900}
        centered
      >
        <Table
          columns={[
            { 
              title: '候选人', 
              dataIndex: 'candidate_name', 
              key: 'candidate_name',
              render: (text: string) => <span style={{ fontWeight: 500, color: '#0F172A' }}>{text || '解析中...'}</span>
            },
            { title: '联系方式', dataIndex: 'contact', key: 'contact' },
            { title: '应聘岗位', dataIndex: ['position', 'title'], key: 'position' },
            { 
              title: '匹配度', 
              dataIndex: 'match_score', 
              key: 'match_score',
              render: (score: number) => (
                <span style={{ 
                  color: score >= 80 ? '#10B981' : score >= 60 ? '#F59E0B' : '#EF4444',
                  fontWeight: 600 
                }}>
                  {score > 0 ? `${score}分` : '-'}
                </span>
              )
            },
            {
              title: '操作',
              key: 'action',
              render: (_, record: any) => (
                <Button 
                  type="primary" 
                  icon={<TeamOutlined />} 
                  onClick={() => handleSelectResume(record)}
                >
                  安排面试
                </Button>
              )
            }
          ]}
          dataSource={pendingInterviewResumes}
          loading={loadingResumes}
          rowKey="id"
          pagination={{ pageSize: 5 }}
          locale={{ emptyText: '暂无待面试的候选人' }}
        />
      </Modal>

      {/* 安排面试弹窗 */}
      <Modal
        title="安排面试"
        open={interviewModalVisible}
        onOk={handleInterviewOk}
        onCancel={() => setInterviewModalVisible(false)}
        confirmLoading={submitting}
        width={700}
        centered
        destroyOnClose
        okText="确认"
        cancelText="取消"
      >
        {selectedResume && (
          <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
            <Text strong>候选人：</Text>{selectedResume.candidate_name}
            <br />
            <Text strong>应聘岗位：</Text>{selectedResume.position?.title || '-'}
          </div>
        )}

        {existingInterviews.length > 0 && (
          <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
            <Text strong>该候选人已有 {existingInterviews.length} 轮面试：</Text>
            <div style={{ marginTop: 8 }}>
              {existingInterviews.map((i: any) => (
                <Tag key={i.id} color={i.status === 'completed' ? 'green' : 'blue'}>
                  第{i.round || 1}轮 - {i.status === 'completed' ? '已完成' : '待面试'}
                </Tag>
              ))}
            </div>
          </div>
        )}

        {calendarDraft && !calendarDraft.start && (
          <div style={{ marginBottom: 16, padding: '10px 12px', background: '#eef5ff', borderRadius: 8, color: '#174ea6' }}>
            已选择 {calendarDraft.date.format('YYYY年M月D日')}，请选择具体开始时间
          </div>
        )}

        <Form
          form={interviewForm}
          layout="vertical"
          style={{ marginTop: 24 }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="round"
                label="面试轮次"
                rules={[{ required: true, message: '请选择面试轮次' }]}
              >
                <Select placeholder="选择轮次" size="large">
                  <Select.Option value={1}>第1轮面试</Select.Option>
                  <Select.Option value={2}>第2轮面试</Select.Option>
                  <Select.Option value={3}>第3轮面试</Select.Option>
                  <Select.Option value={4}>第4轮面试</Select.Option>
                  <Select.Option value={5}>第5轮面试</Select.Option>
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
              <Form.Item
                name="interview_type"
                label="面试形式"
                rules={[{ required: true, message: '请选择面试形式' }]}
              >
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
            <Select
              mode="multiple"
              placeholder="选择面试官"
              size="large"
              style={{ width: '100%' }}
            >
              {interviewers.map((user: any) => (
                <Select.Option key={user.id} value={user.id}>{user.full_name || user.email}</Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="interview_time"
                label="开始时间"
                rules={[{ required: true, message: '请选择开始时间' }]}
              >
                <DatePicker
                  showTime={{ format: 'HH:mm', minuteStep: INTERVIEW_MINUTE_STEP }}
                  format="YYYY-MM-DD HH:mm"
                  style={{ width: '100%' }}
                  size="large"
                  autoFocus={Boolean(calendarDraft)}
                  defaultPickerValue={calendarDraft?.date}
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
                <DatePicker
                  showTime={{ format: 'HH:mm', minuteStep: INTERVIEW_MINUTE_STEP }}
                  format="YYYY-MM-DD HH:mm"
                  style={{ width: '100%' }}
                  size="large"
                  defaultPickerValue={calendarDraft?.date}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) => prevValues.interview_type !== currentValues.interview_type}
          >
            {({ getFieldValue }) => {
              const interviewType = getFieldValue('interview_type');
              return (
                <>
                  {interviewType === 'onsite' && (
                    <Form.Item
                      name="interview_location"
                      label="面试地点"
                      rules={[{ required: true, whitespace: true, message: '请输入面试地点' }]}
                    >
                      <Input placeholder="请输入面试地点，如：北京市朝阳区xxx大厦A座10层" size="large" />
                    </Form.Item>
                  )}
                  {interviewType === 'video' && (
                    <Form.Item
                      name="meeting_link"
                      label="会议链接"
                      rules={[{ required: true, whitespace: true, message: '请输入会议链接' }]}
                    >
                      <Input placeholder="请输入视频会议链接，如：https://meeting.xxx.com/xxx" size="large" />
                    </Form.Item>
                  )}
                </>
              );
            }}
          </Form.Item>

          <Form.Item
            name="skip_ai_questions"
            valuePropName="checked"
            initialValue={false}
            extra="勾选后将跳过AI生成面试题，您可以稍后手动添加题目"
          >
            <Checkbox>跳过AI生成面试题</Checkbox>
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) => prevValues.skip_ai_questions !== currentValues.skip_ai_questions}
          >
            {({ getFieldValue }) =>
              !getFieldValue('skip_ai_questions') ? (
                <>
                  <Form.Item
                    name="question_bank_ids"
                    label="参考题库"
                    extra="选择题库后，AI 将参考题库内容生成更精准的面试题"
                  >
                    <Select
                      mode="multiple"
                      placeholder="选择参考题库"
                      size="large"
                      style={{ width: '100%' }}
                    >
                      {questionBanks.map((qb: any) => (
                        <Select.Option key={qb.id} value={qb.id}>{qb.name}</Select.Option>
                      ))}
                    </Select>
                  </Form.Item>

                  <Form.Item
                    name="question_count"
                    label="生成题目数量"
                    initialValue={5}
                  >
                    <InputNumber min={1} max={20} size="large" style={{ width: '100%' }} />
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>

      {/* 邮件预览弹窗 */}
      <Modal
        title="邮件预览"
        open={emailPreviewVisible}
        onCancel={handleCancelPreview}
        width={800}
        centered
        destroyOnClose
        footer={[
          <Button key="cancel" onClick={handleCancelPreview}>
            取消
          </Button>,
          <Button key="confirm" type="primary" loading={sendingEmail} onClick={handleConfirmAndSend}>
            确认
          </Button>
        ]}
      >
        {emailContent && (
          <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
            <p><strong>收件人：</strong>{emailContent.to_email}</p>
            <p><strong>候选人：</strong>{emailContent.candidate_name}</p>
          </div>
        )}

        <Form form={emailForm} layout="vertical">
          <Form.Item
            name="subject"
            label="邮件主题"
            rules={[{ required: true, message: '请输入邮件主题' }]}
          >
            <Input placeholder="邮件主题" size="large" />
          </Form.Item>

          <Form.Item
            name="content"
            label="邮件内容"
            rules={[{ required: true, message: '请输入邮件内容' }]}
          >
            <Input.TextArea
              rows={10}
              placeholder="邮件内容（支持 HTML 格式）"
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>

          <Form.Item
            label="邮件预览"
          >
            <div
              style={{
                border: '1px solid #d9d9d9',
                borderRadius: 8,
                padding: 16,
                maxHeight: 300,
                overflow: 'auto',
                background: '#fff'
              }}
              dangerouslySetInnerHTML={{ __html: emailForm.getFieldValue('content') || '' }}
            />
          </Form.Item>

          <Form.Item
            name="send_email"
            valuePropName="checked"
            initialValue={true}
          >
            <Checkbox>发送邮件通知候选人</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default InterviewsList;
