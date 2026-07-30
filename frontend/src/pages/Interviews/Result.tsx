import React, { useEffect, useState } from 'react';
import { Alert, Card, Col, Descriptions, Button, Result, Typography, Divider, Tag, List, Space, message, Dropdown, Spin, Input, Modal, Row, Select } from 'antd';
import type { MenuProps } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import { DownloadOutlined, FileMarkdownOutlined, FilePdfOutlined, DownOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import { useOptionalAuth } from '../../contexts/AuthContext';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
// @ts-ignore
import html2pdf from 'html2pdf.js';

const { Title, Paragraph, Text } = Typography;
const { TextArea } = Input;

const scoreDimensions = [
  ['technical_fit', '技术匹配', 35, true],
  ['problem_solving', '问题解决', 20, true],
  ['learning_ability', '学习能力', 15, false],
  ['engineering_mindset', '工程化思维', 15, true],
  ['collaboration', '协作能力', 10, false],
  ['culture_fit', '文化匹配', 5, false],
] as const;

const decisionLabels: Record<string, string> = {
  next_round: '进入下一轮',
  passed: '通过',
  rejected: '淘汰',
  inconclusive: '证据不足',
};

type TranscriptSegment = {
  start?: number;
  end?: number;
  text?: string;
  speaker?: string | number;
};

const transcriptText = (value: unknown): string => {
  if (typeof value === 'string') return value.trim();
  if (value && typeof value === 'object' && 'text' in value) {
    const text = (value as { text?: unknown }).text;
    return typeof text === 'string' ? text.trim() : '';
  }
  return '';
};

const formatTranscriptTime = (seconds: unknown): string => {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '';
  const roundedSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(roundedSeconds / 60);
  const remainder = roundedSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
};

const InterviewResultPage: React.FC = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const user = useOptionalAuth()?.user;
  const [interview, setInterview] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [isEditingResult, setIsEditingResult] = useState(false);
  const [humanScores, setHumanScores] = useState<Record<string, number>>({});
  const [humanComments, setHumanComments] = useState('');
  const [humanRecommendation, setHumanRecommendation] = useState('next_round');
  const [decisionCorrectionOpen, setDecisionCorrectionOpen] = useState(false);
  const [correctedDecision, setCorrectedDecision] = useState('passed');
  const [correctionReason, setCorrectionReason] = useState('');
  const [correctingDecision, setCorrectingDecision] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  const [notes, setNotes] = useState<any[]>([]);
  const [reviewCandidates, setReviewCandidates] = useState<any[]>([]);
  const [replacementTarget, setReplacementTarget] = useState<string>('');
  const [replacementUser, setReplacementUser] = useState<string>('');
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [correctedSegments, setCorrectedSegments] = useState<TranscriptSegment[]>([]);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [speakerLabelsOpen, setSpeakerLabelsOpen] = useState(false);
  const [speakerLabelDraft, setSpeakerLabelDraft] = useState<Record<string, string>>({});
  const [savingSpeakerLabels, setSavingSpeakerLabels] = useState(false);

  useEffect(() => {
    if (id) {
      fetchInterview(id);
    }
  }, [id]);

  useEffect(() => {
    if (!id || interview?.lifecycle_state !== 'ended') return;
    request.get(`/interviews/${id}/notes`).then((value: any) => setNotes(value || [])).catch(() => {});
    const mine = interview.panels?.find((panel: any) => String(panel.interviewer_id) === String(user?.id));
    setHumanScores(mine?.human_scores || {});
    setHumanComments(mine?.human_comments || '');
    setHumanRecommendation(mine?.human_recommendation || 'next_round');
  }, [id, interview?.lifecycle_state, interview?.panels, user?.id]);

  useEffect(() => {
    if (interview?.lifecycle_state !== 'ended' || !['admin', 'hr'].includes(user?.role || '')) return;
    request.get('/auth/interviewers').then((items: any) => setReviewCandidates(items || [])).catch(() => {});
  }, [interview?.lifecycle_state, user?.role]);

  const fetchInterview = async (interviewId: string, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await request.get(`/interviews/${interviewId}`) as any;
      if (res && res.scores) {
          // Ensure comments is present
          if (!res.comments) res.comments = {};
      }
      setInterview(res);
    } catch (error) {
      // message.error('获取面试详情失败');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const isGeneratingEvaluation = !!interview && (
    ['pending', 'transcribing', 'analyzing'].includes(interview.ai_analysis_status)
    || (interview.result === 'pending' && !interview.evaluation && !interview.lifecycle_state)
  );

  useEffect(() => {
    if (!id || !isGeneratingEvaluation) return;
    const interval = setInterval(() => {
      fetchInterview(id, true);
    }, 3000);
    return () => clearInterval(interval);
  }, [id, isGeneratingEvaluation]);

  const handleConfirmResult = async (result: string) => {
      try {
          await request.post(`/interviews/${id}/confirm`, { result });
          message.success('已更新面试结果');
          setIsEditingResult(false);
          fetchInterview(id!);
      } catch (error) {
          message.error('操作失败');
      }
  };

  const submitHumanReview = async () => {
    setSavingReview(true);
    try {
      await request.post(`/interviews/${id}/human-review`, {
        scores: humanScores,
        comments: humanComments,
        recommendation: humanRecommendation,
      });
      message.success('人工评价已保存，最终确认前仍可修改');
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存人工评价失败');
    } finally {
      setSavingReview(false);
    }
  };

  const confirmModernDecision = async (decision: string) => {
    try {
      await request.post(`/interviews/${id}/final-decision`, { decision });
      message.success('最终面试结果已确认');
      await fetchInterview(id!, true);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '仍有面试官未完成人工评价');
    }
  };

  const correctModernDecision = async () => {
    if (!correctionReason.trim()) {
      message.error('请填写更正原因');
      return;
    }
    setCorrectingDecision(true);
    try {
      await request.post(`/interviews/${id}/final-decision/correct`, {
        decision: correctedDecision,
        reason: correctionReason.trim(),
      });
      message.success('最终结果已更正并记录审计信息');
      setDecisionCorrectionOpen(false);
      setCorrectionReason('');
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更正结果失败');
    } finally {
      setCorrectingDecision(false);
    }
  };

  const sendReviewReminders = async () => {
    try {
      const response = await request.post(`/interviews/${id}/review-reminders`) as any;
      message.success(`已提醒 ${response.sent?.length || 0} 位面试官`);
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '发送提醒失败');
    }
  };

  const retryAnalysis = async () => {
    try {
      await request.post(`/interviews/${id}/analysis/retry`);
      message.success('已重新启动 AI 分析');
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重试失败');
    }
  };

  const replaceReviewer = async () => {
    if (!replacementTarget || !replacementUser) return;
    try {
      await request.post(`/interviews/${id}/reviewers/replace`, {
        old_interviewer_id: replacementTarget,
        new_interviewer_id: replacementUser,
      });
      message.success('评审人已更换');
      setReplacementTarget('');
      setReplacementUser('');
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更换评审人失败');
    }
  };

  const openTranscriptCorrection = () => {
    const corrected = interview?.transcripts?.corrected_full_interview_data?.segments;
    const original = interview?.transcripts?.full_interview_data?.segments;
    setCorrectedSegments((Array.isArray(corrected) ? corrected : original || []).map((segment: any) => ({ ...segment })));
    setCorrectionOpen(true);
  };

  const saveTranscriptCorrection = async () => {
    if (correctedSegments.some((segment) => !segment.text?.trim())) {
      message.error('校订后的每个时间段都必须保留文本');
      return;
    }
    setSavingCorrection(true);
    try {
      await request.post(`/interviews/${id}/transcript/corrections`, { segments: correctedSegments });
      message.success('校订版已保存，AI 正在重新分析');
      setCorrectionOpen(false);
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存校订版失败');
    } finally {
      setSavingCorrection(false);
    }
  };

  const saveSpeakerLabels = async () => {
    const labels = Object.fromEntries(
      Object.entries(speakerLabelDraft)
        .map(([speaker, label]) => [speaker, label.trim()])
        .filter(([, label]) => label),
    );
    setSavingSpeakerLabels(true);
    try {
      await request.post(`/interviews/${id}/transcript/speaker-labels`, { labels });
      message.success('说话人标注已保存');
      setSpeakerLabelsOpen(false);
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存说话人标注失败');
    } finally {
      setSavingSpeakerLabels(false);
    }
  };

  const handleExport = async (format: string = 'markdown') => {
    // Avoid event object being passed as format
    if (typeof format !== 'string') format = 'markdown';
    
    if (format === 'pdf') {
        const element = document.getElementById('interview-result-content');
        if (!element) return;
        
        const opt = {
            margin:       [15, 15, 15, 15],
            filename:     `面试评估报告_${interview.resume?.candidate_name || '候选人'}_${interview.id}.pdf`,
            image:        { type: 'jpeg', quality: 0.98 },
            html2canvas:  { scale: 2, useCORS: true, logging: true },
            jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' },
            pagebreak:    { mode: ['avoid-all', 'css', 'legacy'] }
        } as any;
        
        // Remove buttons for PDF
        const extraButtons = document.getElementById('result-extra-buttons');
        if (extraButtons) extraButtons.style.display = 'none';
        
        html2pdf().from(element).set(opt).save().then(() => {
             if (extraButtons) extraButtons.style.display = 'block';
             message.success('导出 PDF 成功');
        });
        return;
    }
    
    try {
      const response = await request.get(`/interviews/${id}/export`, {
        params: { format },
        responseType: 'blob'
      });
      
      const mimeType = 'text/markdown';
      const ext = 'md';
      
      const blob = new Blob([response as any], { type: mimeType });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `面试评估报告_${interview.resume?.candidate_name || '候选人'}_${interview.id}.${ext}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      message.success('导出成功');
    } catch (error) {
      message.error('导出失败');
    }
  };

  if (loading || !interview) {
    return <Card loading={loading} />;
  }

  if (isGeneratingEvaluation && !interview.lifecycle_state) {
    return (
      <Card id="interview-result-content">
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 360 }}>
          <Spin size="large" />
          <Title level={4} style={{ marginTop: 16 }}>正在生成面试评估意见</Title>
          <Text type="secondary">AI 正在分析评分与评语，请稍候…</Text>
          <div style={{ marginTop: 16 }}>
            <Button onClick={() => navigate('/interviews')}>返回列表</Button>
          </div>
        </div>
      </Card>
    );
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'passed': return 'success';
      case 'rejected': return 'error';
      case 'next_round': return 'info';
      default: return 'info';
    }
  };

  const resultMap: Record<string, string> = {
    passed: '通过',
    rejected: '淘汰',
    next_round: '进入下一轮',
    pending: '未出结果'
  };

  const calculateAverage = () => {
    if (!interview.scores) return '0.0';
    const values = Object.values(interview.scores) as number[];
    if (values.length === 0) return '0.0';
    const sum = values.reduce((a, b) => a + b, 0);
    return (sum / values.length).toFixed(1);
  };

  const exportItems: MenuProps['items'] = [
    {
      key: 'markdown',
      label: '导出 Markdown',
      icon: <FileMarkdownOutlined />,
      onClick: () => handleExport('markdown'),
    },
    {
      key: 'pdf',
      label: '导出 PDF',
      icon: <FilePdfOutlined />,
      onClick: () => handleExport('pdf'),
    },
  ];

  const pendingConfirmContent = (
      <div style={{ marginTop: 24, textAlign: 'center', background: '#F0F9FF', padding: 24, borderRadius: 8, border: '1px solid #BAE6FD' }}>
          <Title level={4} style={{ color: '#0369A1' }}>AI 建议结果: {interview.suggestion || '无建议'} (待确认)</Title>
          <Paragraph style={{ marginBottom: 24 }}>
             请根据 AI 的评估意见和您的判断，确认最终面试结果。
          </Paragraph>
          <Space size="large">
              <Button type="primary" size="large" onClick={() => handleConfirmResult('passed')} style={{ backgroundColor: '#52c41a', borderColor: '#52c41a' }}>
                  通过
              </Button>
              <Button type="primary" size="large" onClick={() => handleConfirmResult('next_round')} style={{ backgroundColor: '#1890ff', borderColor: '#1890ff' }}>
                  进入下一轮
              </Button>
              <Button type="primary" size="large" danger onClick={() => handleConfirmResult('rejected')}>
                  淘汰
              </Button>
          </Space>
      </div>
  );
  
  const editResultContent = (
      <div style={{ marginTop: 16, marginBottom: 16, textAlign: 'center', background: '#F9F9F9', padding: 16, borderRadius: 8, border: '1px dashed #D9D9D9' }}>
          <Paragraph style={{ marginBottom: 16 }}>
             重新设置面试结果：
          </Paragraph>
          <Space>
              <Button type={interview.result === 'passed' ? 'primary' : 'default'} onClick={() => handleConfirmResult('passed')} style={interview.result === 'passed' ? { backgroundColor: '#52c41a', borderColor: '#52c41a' } : {}}>
                  通过
              </Button>
              <Button type={interview.result === 'next_round' ? 'primary' : 'default'} onClick={() => handleConfirmResult('next_round')} style={interview.result === 'next_round' ? { backgroundColor: '#1890ff', borderColor: '#1890ff' } : {}}>
                  进入下一轮
              </Button>
              <Button type={interview.result === 'rejected' ? 'primary' : 'default'} danger={interview.result === 'rejected'} onClick={() => handleConfirmResult('rejected')}>
                  淘汰
              </Button>
              <Button type="text" onClick={() => setIsEditingResult(false)}>取消</Button>
          </Space>
      </div>
  );

  const isPendingReview = interview.status !== 'completed' && interview.result === 'pending';
  const transcripts = interview.transcripts && typeof interview.transcripts === 'object'
    ? interview.transcripts as Record<string, unknown>
    : {};
  const fullInterviewData = transcripts.full_interview_data;
  const fullInterviewSegments = (
    fullInterviewData
    && typeof fullInterviewData === 'object'
    && Array.isArray((fullInterviewData as { segments?: unknown }).segments)
      ? (fullInterviewData as { segments: TranscriptSegment[] }).segments
      : []
  ).filter((segment) => transcriptText(segment));
  const speakerLabels = (
    transcripts.speaker_labels
    && typeof transcripts.speaker_labels === 'object'
    && !Array.isArray(transcripts.speaker_labels)
      ? transcripts.speaker_labels as Record<string, string>
      : {}
  );
  const speakerIds = Array.from(new Set(
    fullInterviewSegments
      .map((segment) => segment.speaker)
      .filter((speaker): speaker is string | number => speaker !== undefined && speaker !== null)
      .map(String),
  ));
  const speakerName = (speaker: string | number | undefined) => {
    if (speaker === undefined || speaker === null) return '';
    const key = String(speaker);
    if (speakerLabels[key]) return speakerLabels[key];
    const match = key.match(/(\d+)$/);
    return match ? `说话人 ${Number(match[1]) + 1}` : `说话人 ${key}`;
  };
  const openSpeakerLabels = () => {
    setSpeakerLabelDraft(Object.fromEntries(speakerIds.map((speaker) => [speaker, speakerLabels[speaker] || ''])));
    setSpeakerLabelsOpen(true);
  };
  const fullInterviewText = transcriptText(transcripts.full_interview)
    || transcriptText(fullInterviewData);
  const questionTranscripts = Object.entries(transcripts)
    .filter(([key, value]) => (
      key !== 'full_interview'
      && key !== 'full_interview_data'
      && key !== 'corrected_full_interview_data'
      && key !== 'speaker_labels'
      && transcriptText(value)
    ))
    .sort(([left], [right]) => {
      const leftIndex = Number(left);
      const rightIndex = Number(right);
      if (Number.isInteger(leftIndex) && Number.isInteger(rightIndex)) {
        return leftIndex - rightIndex;
      }
      return left.localeCompare(right);
    });
  const hasTranscripts = fullInterviewSegments.length > 0
    || !!fullInterviewText
    || questionTranscripts.length > 0;

  if (interview.lifecycle_state === 'ended') {
    const isHr = user?.role === 'admin' || user?.role === 'hr';
    const myPanel = interview.panels?.find((panel: any) => String(panel.interviewer_id) === String(user?.id));
    const requiredIds = new Set((interview.panel_members || []).map(String));
    const requiredPanels = (interview.panels || []).filter((panel: any) => requiredIds.has(String(panel.interviewer_id)));
    const allReviewed = requiredPanels.length === requiredIds.size
      && requiredPanels.every((panel: any) => !!panel.human_review_submitted_at);
    const analysis = interview.ai_analysis || {};
    const analysisDimensions = analysis.dimensions || {};
    const aiStatusMap: Record<string, [string, string]> = {
      pending: ['等待处理', 'default'],
      transcribing: ['录音转写中', 'processing'],
      analyzing: ['AI 分析中', 'processing'],
      completed: ['AI 分析完成', 'success'],
      failed: ['AI 分析失败', 'error'],
    };
    const [aiStatusText, aiStatusColor] = aiStatusMap[interview.ai_analysis_status] || [interview.ai_analysis_status, 'default'];

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Card>
          <Space style={{ justifyContent: 'space-between', width: '100%' }} wrap>
            <div>
              <Title level={3} style={{ margin: 0 }}>{interview.resume?.candidate_name || '候选人'} · 面试结果</Title>
              <Text type="secondary">面试已结束，AI 分析与人工评价相互独立</Text>
            </div>
            <Space>
              <Tag color={aiStatusColor}>{aiStatusText}</Tag>
              {interview.final_decision_at && <Tag color="success">最终结果：{decisionLabels[interview.result] || interview.result}</Tag>}
              <Button onClick={() => navigate('/interviews')}>返回列表</Button>
            </Space>
          </Space>
        </Card>

        <Card title="AI 录音分析" extra={isHr && interview.ai_analysis_status === 'failed' ? <Button onClick={retryAnalysis}>重试分析</Button> : null}>
          {['pending', 'transcribing', 'analyzing'].includes(interview.ai_analysis_status) && (
            <div style={{ textAlign: 'center', padding: 32 }}><Spin /><div style={{ marginTop: 12 }}>{aiStatusText}</div></div>
          )}
          {interview.ai_analysis_status === 'failed' && (
            <Alert type="error" showIcon message="AI 分析失败" description={interview.ai_analysis_error || '请联系 HR/Admin 重试'} />
          )}
          {interview.ai_analysis_status === 'completed' && (
            <>
              <Row gutter={[12, 12]}>
                {scoreDimensions.map(([key, label, weight, gate]) => {
                  const item = analysisDimensions[key] || {};
                  return (
                    <Col xs={24} md={12} lg={8} key={key}>
                      <Card size="small" title={<Space><span>{label}</span><Tag>{weight}%</Tag>{gate && <Tag color="error">Gate</Tag>}</Space>}>
                        <Title level={3} style={{ margin: 0 }}>{item.score == null ? '证据不足' : `${item.score} / 10`}</Title>
                        {item.assessment && <Paragraph style={{ marginTop: 8 }}>{item.assessment}</Paragraph>}
                        {(item.evidence || []).map((evidence: any, index: number) => (
                          <div key={index} style={{ marginTop: 8, padding: 8, background: '#F8FAFC', borderRadius: 6 }}>
                            <Text type="secondary">{formatTranscriptTime(evidence.start)}–{formatTranscriptTime(evidence.end)}</Text>
                            <div>“{evidence.quote}”</div>
                          </div>
                        ))}
                      </Card>
                    </Col>
                  );
                })}
              </Row>
              <Divider />
              <Descriptions bordered column={2}>
                <Descriptions.Item label="AI 综合分">{analysis.weighted_score == null ? '证据不足' : `${analysis.weighted_score} / 10`}</Descriptions.Item>
                <Descriptions.Item label="AI 建议"><Tag color="blue">{decisionLabels[analysis.recommendation] || analysis.recommendation || '暂无'}</Tag></Descriptions.Item>
                <Descriptions.Item label="证据覆盖率">{analysis.coverage == null ? '—' : `${analysis.coverage}%`}</Descriptions.Item>
                <Descriptions.Item label="分析版本">v{interview.ai_analysis_version}</Descriptions.Item>
              </Descriptions>
              {(analysis.summary || analysis.report) && <Paragraph style={{ marginTop: 16, whiteSpace: 'pre-wrap' }}>{analysis.summary || analysis.report}</Paragraph>}
            </>
          )}
        </Card>

        {myPanel && (
          <Card title="人工评价" extra={myPanel.human_review_submitted_at ? <Tag color="success">已提交，可继续修改</Tag> : <Tag color="warning">待评价</Tag>}>
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <div>
                <Text strong>评价结论</Text>
                <Select
                  aria-label="评价结论"
                  value={humanRecommendation}
                  disabled={!!interview.final_decision_at}
                  onChange={setHumanRecommendation}
                  style={{ width: '100%', marginTop: 6 }}
                  options={Object.entries(decisionLabels).filter(([key]) => key !== 'inconclusive').map(([value, label]) => ({ value, label }))}
                />
              </div>
              <div>
                <Text strong>评价说明</Text>
                <TextArea
                  rows={4}
                  value={humanComments}
                  disabled={!!interview.final_decision_at}
                  onChange={(event) => setHumanComments(event.target.value)}
                  placeholder="请输入评价说明"
                  style={{ marginTop: 6 }}
                />
              </div>
              <Button type="primary" loading={savingReview} disabled={!!interview.final_decision_at} onClick={submitHumanReview} style={{ alignSelf: 'flex-start' }}>保存人工评价</Button>
            </Space>
          </Card>
        )}

        <Card title="面试官评价状态" extra={isHr && !allReviewed ? <Button onClick={sendReviewReminders}>邮件提醒未评价面试官</Button> : null}>
          <List
            dataSource={requiredPanels}
            renderItem={(panel: any) => {
              const reviewed = !!panel.human_review_submitted_at;
              const recommendation = decisionLabels[panel.human_recommendation] || panel.human_recommendation || '未选择';
              return (
                <List.Item actions={isHr && !reviewed ? [<Button type="link" key="replace" onClick={() => setReplacementTarget(String(panel.interviewer_id))}>更换评审人</Button>] : []}>
                  <div style={{ width: '100%' }}>
                    <Space style={{ justifyContent: 'space-between', width: '100%' }} wrap>
                      <Text strong>{panel.interviewer_name || String(panel.interviewer_id)}</Text>
                      <Tag color={reviewed ? 'success' : 'warning'}>{reviewed ? '已评价' : '待评价'}</Tag>
                    </Space>
                    {reviewed && (
                      <div style={{ marginTop: 10, padding: '10px 12px', background: '#F8FAFC', borderRadius: 6 }}>
                        <Text style={{ display: 'block' }}>{`评价结论：${recommendation}`}</Text>
                        <Text style={{ display: 'block', marginTop: 6, whiteSpace: 'pre-wrap' }}>{`评价说明：${panel.human_comments?.trim() || '未填写'}`}</Text>
                      </div>
                    )}
                  </div>
                </List.Item>
              );
            }}
          />
        </Card>

        {notes.length > 0 && (
          <Card title="面试现场笔记（已冻结）">
            <List dataSource={notes} renderItem={(note: any) => <List.Item><div><Text strong>{note.interviewer_name || String(note.interviewer_id)}</Text><Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{note.notes || '无笔记'}</Paragraph></div></List.Item>} />
          </Card>
        )}

        {hasTranscripts && (
          <Card
            title="面试过程记录"
            extra={fullInterviewSegments.length > 0 ? (
              <Space wrap>
                {speakerIds.length > 0 && <Button onClick={openSpeakerLabels}>标注说话人</Button>}
                {isHr && <Button onClick={openTranscriptCorrection}>校订转写并重新分析</Button>}
              </Space>
            ) : null}
          >
            <List
              dataSource={fullInterviewSegments.length ? fullInterviewSegments : [{ text: fullInterviewText }]}
              renderItem={(segment: TranscriptSegment) => <List.Item><Space align="start"><Text type="secondary">{formatTranscriptTime(segment.start)}</Text>{speakerName(segment.speaker) && <Tag color="blue">{speakerName(segment.speaker)}</Tag>}<Text style={{ whiteSpace: 'pre-wrap' }}>{transcriptText(segment)}</Text></Space></List.Item>}
            />
          </Card>
        )}

        {isHr && (
          <Card title="HR/Admin 最终决定">
            {!allReviewed && <Alert type="warning" showIcon message="必须等待所有指定面试官完成人工评价，不能强制跳过。" style={{ marginBottom: 16 }} />}
            <Space wrap>
              {Object.entries(decisionLabels).filter(([key]) => key !== 'inconclusive').map(([decision, label]) => (
                <Button key={decision} type={interview.result === decision ? 'primary' : 'default'} disabled={!allReviewed || !!interview.final_decision_at} danger={decision === 'rejected'} onClick={() => confirmModernDecision(decision)}>{label}</Button>
              ))}
              {user?.role === 'admin' && interview.final_decision_at && (
                <Button onClick={() => {
                  setCorrectedDecision(interview.result === 'hired' ? 'passed' : interview.result);
                  setDecisionCorrectionOpen(true);
                }}>更正结果</Button>
              )}
            </Space>
            {Array.isArray(interview.decision_history) && interview.decision_history.length > 0 && (
              <>
                <Divider />
                <List
                  size="small"
                  header={<Text strong>结果审计记录</Text>}
                  dataSource={interview.decision_history}
                  renderItem={(item: any) => (
                    <List.Item>
                      <Text>
                        {item.action === 'corrected'
                          ? `${decisionLabels[item.from] || item.from} → ${decisionLabels[item.to] || item.to}`
                          : `确认：${decisionLabels[item.result] || item.result}`}
                        {item.reason ? `；原因：${item.reason}` : ''}
                        {item.at ? `；${new Date(item.at).toLocaleString()}` : ''}
                      </Text>
                    </List.Item>
                  )}
                />
              </>
            )}
          </Card>
        )}

        <Modal
          title="更正最终面试结果"
          open={decisionCorrectionOpen}
          onOk={correctModernDecision}
          confirmLoading={correctingDecision}
          onCancel={() => setDecisionCorrectionOpen(false)}
          okText="确认更正"
        >
          <Select
            value={correctedDecision}
            onChange={setCorrectedDecision}
            style={{ width: '100%', marginBottom: 12 }}
            options={Object.entries(decisionLabels)
              .filter(([key]) => key !== 'inconclusive')
              .map(([value, label]) => ({ value, label }))}
          />
          <TextArea
            rows={3}
            maxLength={500}
            showCount
            value={correctionReason}
            onChange={(event) => setCorrectionReason(event.target.value)}
            placeholder="请填写更正原因"
          />
        </Modal>

        <Modal title="更换评审人" open={!!replacementTarget} onOk={replaceReviewer} onCancel={() => { setReplacementTarget(''); setReplacementUser(''); }} okText="确认更换">
          <Select
            style={{ width: '100%' }}
            placeholder="选择新的面试官"
            value={replacementUser || undefined}
            onChange={setReplacementUser}
            options={reviewCandidates.filter((candidate) => !requiredIds.has(String(candidate.id))).map((candidate) => ({ value: String(candidate.id), label: candidate.full_name || candidate.email }))}
          />
        </Modal>
        <Modal title="校订面试转写" width={760} open={correctionOpen} onOk={saveTranscriptCorrection} confirmLoading={savingCorrection} onCancel={() => setCorrectionOpen(false)} okText="保存并重新分析">
          <Alert type="info" showIcon message="原始转写会永久保留；本次校订将创建新版本并重新生成 AI 分析。" style={{ marginBottom: 12 }} />
          <div style={{ maxHeight: 520, overflowY: 'auto' }}>
            {correctedSegments.map((segment, index) => (
              <div key={`${segment.start}-${index}`} style={{ marginBottom: 12 }}>
                <Text type="secondary">{formatTranscriptTime(segment.start)}–{formatTranscriptTime(segment.end)}</Text>
                <TextArea
                  rows={2}
                  value={segment.text}
                  onChange={(event) => setCorrectedSegments(correctedSegments.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item))}
                  style={{ marginTop: 4 }}
                />
              </div>
            ))}
          </div>
        </Modal>
        <Modal title="标注说话人" open={speakerLabelsOpen} onOk={saveSpeakerLabels} confirmLoading={savingSpeakerLabels} onCancel={() => setSpeakerLabelsOpen(false)} okText="保存标注">
          <Alert type="info" showIcon message="标注仅用于结果页展示，不会修改原始转写，也不会触发 AI 重新分析。" style={{ marginBottom: 16 }} />
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {speakerIds.map((speaker) => (
              <Input
                key={speaker}
                addonBefore={speakerName(speaker)}
                value={speakerLabelDraft[speaker] || ''}
                maxLength={100}
                placeholder="例如：候选人、面试官张三"
                onChange={(event) => setSpeakerLabelDraft((current) => ({ ...current, [speaker]: event.target.value }))}
              />
            ))}
          </Space>
        </Modal>
      </div>
    );
  }

  return (
    <Card id="interview-result-content">
      {isPendingReview ? (
         // Pending review state
         <>
            <Result
                status="info"
                title="面试评分已提交"
                subTitle="AI 评估意见已生成，请确认最终结果"
                extra={
                    <div id="result-extra-buttons">
                        <Button type="primary" key="console" onClick={() => navigate('/interviews')} style={{ marginRight: 8 }}>
                        返回列表
                        </Button>
                        <Dropdown key="export" menu={{ items: exportItems }}>
                        <Button icon={<DownloadOutlined />} style={{ marginRight: 8 }}>
                            导出结果 <DownOutlined />
                        </Button>
                        </Dropdown>
                        <Button key="buy" onClick={() => navigate(`/resumes/${interview.resume_id}`)}>
                        查看简历
                        </Button>
                    </div>
                }
            />
            {pendingConfirmContent}
         </>
      ) : (
          <>
            <Result
                status={getStatusIcon(interview.result)}
                title={`面试结果: ${resultMap[interview.result] || interview.result}`}
                subTitle={`总分: ${calculateAverage()} / 10`}
                extra={
                <div id="result-extra-buttons">
                    <Button type="primary" key="console" onClick={() => navigate('/interviews')} style={{ marginRight: 8 }}>
                    返回列表
                    </Button>
                    <Dropdown key="export" menu={{ items: exportItems }}>
                    <Button icon={<DownloadOutlined />} style={{ marginRight: 8 }}>
                        导出结果 <DownOutlined />
                    </Button>
                    </Dropdown>
                    <Button key="buy" onClick={() => navigate(`/resumes/${interview.resume_id}`)}>
                    查看简历
                    </Button>
                    {!isEditingResult && (
                        <Button type="dashed" onClick={() => setIsEditingResult(true)} style={{ marginLeft: 8 }}>
                        修改结果
                        </Button>
                    )}
                </div>
                }
            />
            {isEditingResult && editResultContent}
          </>
      )}

      <Divider />
      
      {interview.resume && (
        <>
          <Title level={4}>简历初审评价</Title>
          <Descriptions bordered column={1}>
             <Descriptions.Item label="匹配度评分">
                <Tag color={interview.resume.match_score >= 80 ? 'green' : interview.resume.match_score >= 60 ? 'orange' : 'red'}>
                   {interview.resume.match_score ?? 'N/A'} 分
                </Tag>
             </Descriptions.Item>
             <Descriptions.Item label="初审结果">
                <Tag color={interview.resume.screening_result === 'passed' ? 'success' : interview.resume.screening_result === 'rejected' ? 'error' : 'warning'}>
                   {interview.resume.screening_result === 'passed' ? '通过' : interview.resume.screening_result === 'rejected' ? '淘汰' : '待定'}
                </Tag>
             </Descriptions.Item>
             <Descriptions.Item label="AI 评价">
                <div style={{ fontSize: 14, lineHeight: 1.8, color: '#334155' }}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      h3: ({node, ...props}) => <h3 style={{ color: '#0F172A', marginTop: 12, marginBottom: 8, fontSize: 15 }} {...props} />,
                      p: ({node, ...props}) => <p style={{ marginBottom: 10 }} {...props} />,
                      ul: ({node, ...props}) => <ul style={{ paddingLeft: 18, marginBottom: 10 }} {...props} />,
                      li: ({node, ...props}) => <li style={{ marginBottom: 4 }} {...props} />
                    }}
                  >
                    {interview.resume.ai_review || '暂无评价'}
                  </ReactMarkdown>
                </div>
             </Descriptions.Item>
          </Descriptions>
          <Divider />
        </>
      )}

      {hasTranscripts && (
        <>
          <Title level={4}>面试过程记录</Title>
          {fullInterviewSegments.length > 0 ? (
            <List
              bordered
              dataSource={fullInterviewSegments}
              renderItem={(segment) => {
                const start = formatTranscriptTime(segment.start);
                const end = formatTranscriptTime(segment.end);
                const timeRange = start && end ? `${start}–${end}` : start;
                return (
                  <List.Item>
                    <div style={{ display: 'flex', gap: 12, width: '100%' }}>
                      {timeRange && (
                        <Text type="secondary" style={{ flexShrink: 0 }}>
                          {timeRange}
                        </Text>
                      )}
                      <Text style={{ whiteSpace: 'pre-wrap' }}>{transcriptText(segment)}</Text>
                    </div>
                  </List.Item>
                );
              }}
            />
          ) : fullInterviewText ? (
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, padding: 16, background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8 }}>
              {fullInterviewText}
            </div>
          ) : null}

          {questionTranscripts.length > 0 && (
            <List
              bordered
              style={{ marginTop: fullInterviewSegments.length > 0 || fullInterviewText ? 16 : 0 }}
              dataSource={questionTranscripts}
              renderItem={([key, value]) => {
                const questionIndex = Number(key);
                const question = Number.isInteger(questionIndex)
                  ? interview.questions?.[questionIndex]
                  : null;
                const label = Number.isInteger(questionIndex)
                  ? `第 ${questionIndex + 1} 题${question?.title ? `：${question.title}` : ''}`
                  : key;
                return (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Text strong>{label}</Text>
                      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, marginTop: 8 }}>
                        {transcriptText(value)}
                      </div>
                    </div>
                  </List.Item>
                );
              }}
            />
          )}
          <Divider />
        </>
      )}

      <Title level={4}>得分详情</Title>
      <List
        bordered
        dataSource={interview.questions}
        renderItem={(item: any, index: number) => (
          <List.Item>
            <div style={{ width: '100%' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                 <div style={{ flex: 1 }}>
                    <Space>
                        <Tag color="blue">第{index + 1}题</Tag>
                        <span style={{ fontWeight: 'bold', fontSize: '15px' }}>{item.title || '无标题'}</span>
                    </Space>
                 </div>
                 <div style={{ marginLeft: 16, textAlign: 'right' }}>
                    <Tag color="geekblue" style={{ fontSize: '14px', padding: '4px 10px' }}>
                        得分: {interview.scores?.[index] ?? 0}
                    </Tag>
                 </div>
              </div>
              
              <div style={{ background: '#F8FAFC', padding: '12px', borderRadius: 8, marginTop: 8, border: '1px solid #E2E8F0' }}>
                 {interview.comments?.[index] ? (
                     <div>
                        <Text strong style={{ marginRight: 8, color: '#0F172A' }}>面试官评语:</Text>
                        <Text>{interview.comments[index]}</Text>
                     </div>
                 ) : (
                    <Text type="secondary">暂无评语</Text>
                 )}
              </div>
            </div>
          </List.Item>
        )}
      />

      <Divider />

      <Title level={4}>综合评价</Title>
      <div style={{ fontSize: 16, lineHeight: 1.9, color: '#334155' }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({node, ...props}) => <h1 style={{ fontSize: 20, marginTop: 16, marginBottom: 12, color: '#0F172A' }} {...props} />,
            h2: ({node, ...props}) => <h2 style={{ fontSize: 18, marginTop: 16, marginBottom: 10, color: '#0F172A' }} {...props} />,
            h3: ({node, ...props}) => <h3 style={{ fontSize: 16, marginTop: 14, marginBottom: 8, color: '#0F172A' }} {...props} />,
            p: ({node, ...props}) => <p style={{ marginBottom: 12 }} {...props} />,
            ul: ({node, ...props}) => <ul style={{ paddingLeft: 18, marginBottom: 12 }} {...props} />,
            li: ({node, ...props}) => <li style={{ marginBottom: 4 }} {...props} />
          }}
        >
          {interview.evaluation || '暂无评价'}
        </ReactMarkdown>
      </div>
    </Card>
  );
};

export default InterviewResultPage;
