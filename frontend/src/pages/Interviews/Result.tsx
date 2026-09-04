import React, { useEffect, useRef, useState } from 'react';
import { Alert, Card, Col, Descriptions, Button, Result, Typography, Divider, Tag, List, Space, message, Dropdown, Spin, Input, Modal, Row, Select } from 'antd';
import type { MenuProps } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import { DownloadOutlined, FileMarkdownOutlined, FilePdfOutlined, DownOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import { useOptionalAuth } from '../../contexts/AuthContext';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import html2pdf from 'html2pdf.js';
import { useReturnToList } from '../../hooks/useListPageState';

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
  waitlist: '备选',
  rejected: '淘汰',
  inconclusive: '证据不足',
};

type TranscriptSegment = {
  id?: string;
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

const joinTranscriptText = (left: string, right: string): string => {
  if (!left) return right;
  if (!right) return left;
  const needsSpace = /[A-Za-z0-9]$/.test(left) && /^[A-Za-z0-9]/.test(right);
  return `${left}${needsSpace ? ' ' : ''}${right}`;
};

export const mergeAdjacentTranscriptSegments = (
  segments: TranscriptSegment[],
  maxGapSeconds = 1.5,
): TranscriptSegment[] => {
  const merged: TranscriptSegment[] = [];

  segments.forEach((segment) => {
    const text = transcriptText(segment);
    if (!text) return;

    const current = { ...segment, text };
    const previous = merged[merged.length - 1];
    const hasTimeline = typeof previous?.end === 'number' && typeof current.start === 'number';
    const sameSpeaker = previous
      && previous.speaker !== undefined
      && previous.speaker !== null
      && current.speaker !== undefined
      && current.speaker !== null
      && String(previous.speaker) === String(current.speaker);
    const gap = hasTimeline ? current.start! - previous.end! : Number.POSITIVE_INFINITY;

    if (previous && sameSpeaker && gap <= maxGapSeconds) {
      previous.text = joinTranscriptText(previous.text || '', text);
      if (typeof current.end === 'number') previous.end = current.end;
      return;
    }
    merged.push(current);
  });

  return merged;
};

type TranscriptPaneProps = {
  title: string;
  subtitle: string;
  badge: string;
  accent: 'blue' | 'green';
  segments: TranscriptSegment[];
  text: string;
  emptyText: string;
  getSpeakerName: (speaker: string | number | undefined) => string;
  playbackReady?: boolean;
  playingSegmentKey?: string | null;
  onTogglePlayback?: (segment: TranscriptSegment, index: number) => void;
  maxHeight?: number;
};

const transcriptSegmentKey = (segment: TranscriptSegment, index: number) => (
  segment.id || `${segment.start}-${segment.end}-${index}`
);

const TranscriptPane: React.FC<TranscriptPaneProps> = ({
  title,
  subtitle,
  badge,
  accent,
  segments,
  text,
  emptyText,
  getSpeakerName,
  playbackReady = false,
  playingSegmentKey,
  onTogglePlayback,
  maxHeight = 560,
}) => {
  const palette = accent === 'blue'
    ? { border: '#BFDBFE', header: '#EFF6FF', tag: 'blue' }
    : { border: '#BBF7D0', header: '#F0FDF4', tag: 'green' };

  return (
    <section style={{ minWidth: 0, border: `1px solid ${palette.border}`, borderRadius: 10, overflow: 'hidden', background: '#FFFFFF' }}>
      <div style={{ padding: '12px 14px', background: palette.header, borderBottom: `1px solid ${palette.border}` }}>
        <Space wrap size={8}>
          <Text strong>{title}</Text>
          <Tag color={palette.tag}>{badge}</Tag>
        </Space>
        <div><Text type="secondary" style={{ fontSize: 12 }}>{subtitle}</Text></div>
      </div>
      <div style={{ maxHeight, overflowY: 'auto', padding: segments.length > 0 ? '0 14px' : 14 }}>
        {segments.length > 0 ? segments.map((segment, index) => {
          const start = formatTranscriptTime(segment.start);
          const end = formatTranscriptTime(segment.end);
          const timeRange = start && end ? `${start}–${end}` : start;
          const speaker = getSpeakerName(segment.speaker);
          const segmentKey = transcriptSegmentKey(segment, index);
          const canPlay = typeof segment.start === 'number'
            && Number.isFinite(segment.start)
            && typeof segment.end === 'number'
            && Number.isFinite(segment.end)
            && segment.end > segment.start;
          const isPlaying = playingSegmentKey === segmentKey;
          return (
            <div key={segmentKey} style={{ padding: '12px 0', borderBottom: index === segments.length - 1 ? undefined : '1px solid #E2E8F0' }}>
              {(timeRange || speaker) && (
                <Space size={6} wrap style={{ marginBottom: 6 }}>
                  {timeRange && <Text type="secondary" style={{ fontSize: 12 }}>{timeRange}</Text>}
                  {speaker && <Tag style={{ marginInlineEnd: 0 }}>{speaker}</Tag>}
                  {onTogglePlayback && canPlay && (
                    <Button
                      type="text"
                      size="small"
                      disabled={!playbackReady}
                      icon={isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                      aria-label={isPlaying ? `暂停 ${timeRange}` : `播放 ${timeRange}`}
                      title={playbackReady ? (isPlaying ? '暂停录音分片' : '播放录音分片') : '录音加载中'}
                      onClick={() => onTogglePlayback(segment, index)}
                      style={{ color: playbackReady ? '#16A34A' : undefined, paddingInline: 4 }}
                    />
                  )}
                </Space>
              )}
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.75, color: '#1E293B' }}>{transcriptText(segment)}</div>
            </div>
          );
        }) : text ? (
          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, color: '#1E293B' }}>{text}</div>
        ) : (
          <Text type="secondary">{emptyText}</Text>
        )}
      </div>
    </section>
  );
};

const InterviewResultPage: React.FC = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const returnToList = useReturnToList('/interviews');
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
  const [reviewersOpen, setReviewersOpen] = useState(false);
  const [reviewerDraft, setReviewerDraft] = useState<string[]>([]);
  const [savingReviewers, setSavingReviewers] = useState(false);
  const [replacementTarget, setReplacementTarget] = useState<string>('');
  const [replacementUser, setReplacementUser] = useState<string>('');
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [correctedSegments, setCorrectedSegments] = useState<TranscriptSegment[]>([]);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [speakerLabelsOpen, setSpeakerLabelsOpen] = useState(false);
  const [speakerLabelDraft, setSpeakerLabelDraft] = useState<Record<string, string>>({});
  const [savingSpeakerLabels, setSavingSpeakerLabels] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playbackEndRef = useRef<number | null>(null);
  const [playbackUrl, setPlaybackUrl] = useState('');
  const [playbackReady, setPlaybackReady] = useState(false);
  const [playingSegmentKey, setPlayingSegmentKey] = useState<string | null>(null);

  useEffect(() => {
    if (id) {
      fetchInterview(id);
    }
  }, [id]);

  useEffect(() => {
    const fullRecording = interview?.audio_records?.full_interview;
    const match = typeof fullRecording === 'string'
      ? /\/api\/files\/([0-9a-f-]{36})$/i.exec(fullRecording)
      : null;
    if (!match) {
      setPlaybackUrl('');
      setPlaybackReady(false);
      return;
    }
    setPlaybackUrl('');
    setPlaybackReady(false);
    let cancelled = false;
    request.post(`/files/${match[1]}/public-token`, { ttl_seconds: 3600 })
      .then((value: any) => {
        if (!cancelled && typeof value?.url === 'string') setPlaybackUrl(value.url);
      })
      .catch(() => {
        if (!cancelled) setPlaybackUrl('');
      });
    return () => { cancelled = true; };
  }, [interview?.audio_records?.full_interview]);

  useEffect(() => () => {
    audioRef.current?.pause();
  }, []);

  const toggleSegmentPlayback = (segment: TranscriptSegment, index: number) => {
    const audio = audioRef.current;
    if (!audio || !playbackReady || typeof segment.start !== 'number' || typeof segment.end !== 'number') return;
    const segmentKey = transcriptSegmentKey(segment, index);
    if (playingSegmentKey === segmentKey && !audio.paused) {
      audio.pause();
      setPlayingSegmentKey(null);
      return;
    }
    playbackEndRef.current = segment.end;
    audio.currentTime = segment.start;
    audio.play()
      .then(() => setPlayingSegmentKey(segmentKey))
      .catch(() => message.error('录音播放失败，请稍后重试'));
  };

  const stopAtSegmentEnd = () => {
    const audio = audioRef.current;
    if (!audio || playbackEndRef.current === null) return;
    if (audio.currentTime >= playbackEndRef.current) {
      audio.pause();
      playbackEndRef.current = null;
      setPlayingSegmentKey(null);
    }
  };

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

  const openReviewers = () => {
    setReviewerDraft((interview?.panel_members || []).map(String));
    setReviewersOpen(true);
  };

  const saveReviewers = async () => {
    if (reviewerDraft.length === 0) {
      message.error('请至少保留一位面试官');
      return;
    }
    setSavingReviewers(true);
    try {
      await request.put(`/interviews/${id}/reviewers`, { interviewer_ids: reviewerDraft });
      message.success('面试官已更新');
      setReviewersOpen(false);
      await fetchInterview(id!, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新面试官失败');
    } finally {
      setSavingReviewers(false);
    }
  };

  const openTranscriptCorrection = () => {
    const corrected = interview?.transcripts?.corrected_full_interview_data?.segments;
    const original = interview?.transcripts?.full_interview_data?.segments;
    setCorrectedSegments(mergeAdjacentTranscriptSegments(
      (Array.isArray(corrected) ? corrected : original || []).map((segment: any) => ({ ...segment })),
    ));
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
            <Button onClick={returnToList}>返回列表</Button>
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
  const realtimeInterviewData = transcripts.realtime_full_interview_data;
  const originalOfflineInterviewData = transcripts.full_interview_data;
  const correctedOfflineInterviewData = transcripts.corrected_full_interview_data;
  const displayedOfflineInterviewData = correctedOfflineInterviewData || originalOfflineInterviewData;
  const segmentsFrom = (value: unknown): TranscriptSegment[] => (
    value
    && typeof value === 'object'
    && Array.isArray((value as { segments?: unknown }).segments)
      ? (value as { segments: TranscriptSegment[] }).segments
      : []
  );
  const realtimeInterviewSegments = mergeAdjacentTranscriptSegments(segmentsFrom(realtimeInterviewData));
  const offlineInterviewSegments = mergeAdjacentTranscriptSegments(segmentsFrom(displayedOfflineInterviewData));
  const speakerLabels = (
    transcripts.speaker_labels
    && typeof transcripts.speaker_labels === 'object'
    && !Array.isArray(transcripts.speaker_labels)
      ? transcripts.speaker_labels as Record<string, string>
      : {}
  );
  const speakerIds = Array.from(new Set(
    offlineInterviewSegments
      .map((segment) => segment.speaker)
      .filter((speaker): speaker is string | number => speaker !== undefined && speaker !== null)
      .map(String),
  ));
  const defaultSpeakerName = (speaker: string | number | undefined) => {
    if (speaker === undefined || speaker === null) return '';
    const key = String(speaker);
    const match = key.match(/(\d+)$/);
    return match ? `说话人 ${Number(match[1]) + 1}` : `说话人 ${key}`;
  };
  const speakerName = (speaker: string | number | undefined) => {
    if (speaker === undefined || speaker === null) return '';
    return speakerLabels[String(speaker)] || defaultSpeakerName(speaker);
  };
  const openSpeakerLabels = () => {
    setSpeakerLabelDraft(Object.fromEntries(speakerIds.map((speaker) => [speaker, speakerLabels[speaker] || ''])));
    setSpeakerLabelsOpen(true);
  };
  const realtimeInterviewText = transcriptText(transcripts.realtime_full_interview)
    || transcriptText(realtimeInterviewData);
  const offlineInterviewText = transcriptText(displayedOfflineInterviewData)
    || transcriptText(transcripts.full_interview);
  const hasCorrectedOfflineTranscript = !!correctedOfflineInterviewData;
  const hasRealtimeTranscript = realtimeInterviewSegments.length > 0 || !!realtimeInterviewText;
  const hasOfflineTranscript = offlineInterviewSegments.length > 0 || !!offlineInterviewText;
  const questionTranscripts = Object.entries(transcripts)
    .filter(([key, value]) => (
      key !== 'full_interview'
      && key !== 'full_interview_data'
      && key !== 'corrected_full_interview_data'
      && key !== 'realtime_full_interview'
      && key !== 'realtime_full_interview_data'
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
  const hasTranscripts = hasRealtimeTranscript
    || hasOfflineTranscript
    || questionTranscripts.length > 0;
  const recordingPlayer = playbackUrl ? (
    <audio
      ref={audioRef}
      src={playbackUrl}
      preload="metadata"
      onLoadedMetadata={() => setPlaybackReady(true)}
      onTimeUpdate={stopAtSegmentEnd}
      onPause={() => setPlayingSegmentKey(null)}
      onEnded={() => {
        playbackEndRef.current = null;
        setPlayingSegmentKey(null);
      }}
      style={{ display: 'none' }}
    />
  ) : null;

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
      not_applicable: ['未使用录音分析', 'default'],
    };
    const [aiStatusText, aiStatusColor] = aiStatusMap[interview.ai_analysis_status] || [interview.ai_analysis_status, 'default'];

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {recordingPlayer}
        <Card>
          <Space style={{ justifyContent: 'space-between', width: '100%' }} wrap>
            <div>
              <Title level={3} style={{ margin: 0 }}>{interview.resume?.candidate_name || '候选人'} · 面试结果</Title>
              <Text type="secondary">面试已结束，AI 分析与人工评价相互独立</Text>
            </div>
            <Space>
              <Tag color={aiStatusColor}>{aiStatusText}</Tag>
              {interview.final_decision_at && <Tag color="success">最终结果：{decisionLabels[interview.result] || interview.result}</Tag>}
              <Button onClick={returnToList}>返回列表</Button>
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
          {interview.ai_analysis_status === 'not_applicable' && (
            <Alert type="info" showIcon message="无录音证据，未执行 AI 分析" />
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
              {analysis.format_version === 2 ? (
                <section style={{ marginTop: 24 }}>
                  <Title level={4}>AI 面试评价</Title>

                  <Title level={5}>综合表现</Title>
                  <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{analysis.summary}</Paragraph>

                  <Title level={5}>主要优势</Title>
                  {(analysis.strengths || []).length > 0 ? (
                    <List
                      dataSource={analysis.strengths}
                      renderItem={(item: any) => (
                        <List.Item>
                          <div style={{ width: '100%' }}>
                            <Text strong>{item.conclusion}</Text>
                            <div style={{ marginTop: 6, padding: 8, background: '#F0FDF4', borderRadius: 6 }}>
                              <Text type="secondary">{formatTranscriptTime(item.evidence?.start)}–{formatTranscriptTime(item.evidence?.end)}</Text>
                              <div>“{item.evidence?.quote}”</div>
                            </div>
                            <Paragraph style={{ margin: '6px 0 0' }}>岗位影响：{item.job_impact}</Paragraph>
                          </div>
                        </List.Item>
                      )}
                    />
                  ) : <Text type="secondary">未发现有充分录音证据支撑的明确优势</Text>}

                  <Title level={5} style={{ marginTop: 20 }}>风险与不足</Title>
                  {(analysis.risks || []).length > 0 ? (
                    <List
                      dataSource={analysis.risks}
                      renderItem={(item: any) => (
                        <List.Item>
                          <div style={{ width: '100%' }}>
                            <Text strong>{item.conclusion}</Text>
                            <div style={{ marginTop: 6, padding: 8, background: '#FFF7ED', borderRadius: 6 }}>
                              <Text type="secondary">{formatTranscriptTime(item.evidence?.start)}–{formatTranscriptTime(item.evidence?.end)}</Text>
                              <div>“{item.evidence?.quote}”</div>
                            </div>
                            <Paragraph style={{ margin: '6px 0 0' }}>岗位影响：{item.job_impact}</Paragraph>
                          </div>
                        </List.Item>
                      )}
                    />
                  ) : <Text type="secondary">未发现有充分录音证据支撑的明确风险</Text>}

                  <Title level={5} style={{ marginTop: 20 }}>录用建议</Title>
                  <Paragraph>
                    <Tag color="blue">{decisionLabels[analysis.recommendation] || analysis.recommendation}</Tag>
                    {analysis.recommendation_reason}
                  </Paragraph>
                  {(analysis.next_round_questions || []).length > 0 && (
                    <>
                      <Text strong>下一轮重点验证</Text>
                      <List
                        size="small"
                        dataSource={analysis.next_round_questions}
                        renderItem={(question: string) => <List.Item>{question}</List.Item>}
                      />
                    </>
                  )}
                </section>
              ) : (
                (analysis.summary || analysis.report) && <Paragraph style={{ marginTop: 16, whiteSpace: 'pre-wrap' }}>{analysis.summary || analysis.report}</Paragraph>
              )}
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

        <Card
          title="面试官评价状态"
          extra={isHr ? (
            <Space>
              {!interview.final_decision_at && <Button onClick={openReviewers}>管理面试官</Button>}
              {!allReviewed && <Button onClick={sendReviewReminders}>邮件提醒未评价面试官</Button>}
            </Space>
          ) : null}
        >
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

        <Modal
          title="管理面试官"
          open={reviewersOpen}
          onOk={saveReviewers}
          onCancel={() => setReviewersOpen(false)}
          confirmLoading={savingReviewers}
          okText="保存"
          cancelText="取消"
        >
          <Text type="secondary">可在最终面试结果确认前添加或删除面试官，历史评价和现场笔记会保留。</Text>
          <Select
            mode="multiple"
            value={reviewerDraft}
            onChange={setReviewerDraft}
            placeholder="请选择面试官"
            optionFilterProp="label"
            style={{ width: '100%', marginTop: 16 }}
            options={reviewCandidates.map((candidate: any) => ({
              value: String(candidate.id),
              label: candidate.full_name || candidate.email,
            }))}
          />
        </Modal>

        {notes.length > 0 && (
          <Card title="面试现场笔记（已冻结）">
            <List dataSource={notes} renderItem={(note: any) => <List.Item><div><Text strong>{note.interviewer_name || String(note.interviewer_id)}</Text><Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{note.notes || '无笔记'}</Paragraph></div></List.Item>} />
          </Card>
        )}

        {hasTranscripts && (
          <Card
            title="面试过程记录"
            extra={hasOfflineTranscript ? (
              <Space wrap>
                {speakerIds.length > 0 && <Button onClick={openSpeakerLabels}>标注说话人</Button>}
                {isHr && offlineInterviewSegments.length > 0 && <Button onClick={openTranscriptCorrection}>校订转写并重新分析</Button>}
              </Space>
            ) : null}
          >
            <Alert
              type="info"
              showIcon
              message="实时稿与离线稿独立保留；校订只会生成新的离线校订版本，不会覆盖实时稿。"
              style={{ marginBottom: 16 }}
            />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 340px), 1fr))', gap: 16, alignItems: 'start' }}>
              <TranscriptPane
                title="实时转写"
                subtitle="面试过程中持续保存，用于还原现场记录"
                badge="实时稿"
                accent="blue"
                segments={realtimeInterviewSegments}
                text={realtimeInterviewText}
                emptyText="本场面试没有保存实时转写"
                getSpeakerName={defaultSpeakerName}
              />
              <TranscriptPane
                title="离线转写"
                subtitle="面试结束后由离线模型生成，用于校订与 AI 分析"
                badge={hasCorrectedOfflineTranscript ? '已校订' : '离线稿'}
                accent="green"
                segments={offlineInterviewSegments}
                text={offlineInterviewText}
                emptyText="离线转写尚未生成"
                getSpeakerName={speakerName}
                playbackReady={playbackReady}
                playingSegmentKey={playingSegmentKey}
                onTogglePlayback={toggleSegmentPlayback}
              />
            </div>
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
        <Modal title="校订离线转写" width={1120} open={correctionOpen} onOk={saveTranscriptCorrection} confirmLoading={savingCorrection} onCancel={() => setCorrectionOpen(false)} okText="保存并重新分析">
          <Alert type="info" showIcon message="左侧实时稿仅供对照；右侧修改会创建新的离线校订版本。实时稿和原始离线稿都会保留。" style={{ marginBottom: 12 }} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 400px), 1fr))', gap: 16, alignItems: 'start' }}>
            <TranscriptPane
              title="实时转写"
              subtitle="只读对照，不参与本次修改"
              badge="实时稿"
              accent="blue"
              segments={realtimeInterviewSegments}
              text={realtimeInterviewText}
              emptyText="本场面试没有保存实时转写"
              getSpeakerName={defaultSpeakerName}
              maxHeight={520}
            />
            <section style={{ minWidth: 0, border: '1px solid #BBF7D0', borderRadius: 10, overflow: 'hidden', background: '#FFFFFF' }}>
              <div style={{ padding: '12px 14px', background: '#F0FDF4', borderBottom: '1px solid #BBF7D0' }}>
                <Space wrap size={8}><Text strong>离线转写</Text><Tag color="green">可校订</Tag></Space>
                <div><Text type="secondary" style={{ fontSize: 12 }}>按合并后的说话段落校订，保存后重新执行 AI 分析</Text></div>
              </div>
              <div style={{ maxHeight: 520, overflowY: 'auto', padding: '0 14px' }}>
                {correctedSegments.map((segment, index) => (
                  <div key={`${segment.start}-${index}`} style={{ padding: '12px 0', borderBottom: index === correctedSegments.length - 1 ? undefined : '1px solid #E2E8F0' }}>
                    <Space size={6} wrap>
                      <Text type="secondary" style={{ fontSize: 12 }}>{formatTranscriptTime(segment.start)}–{formatTranscriptTime(segment.end)}</Text>
                      {speakerName(segment.speaker) && <Tag style={{ marginInlineEnd: 0 }}>{speakerName(segment.speaker)}</Tag>}
                    </Space>
                    <TextArea
                      autoSize={{ minRows: 2, maxRows: 8 }}
                      value={segment.text}
                      onChange={(event) => setCorrectedSegments(correctedSegments.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item))}
                      style={{ marginTop: 6 }}
                    />
                  </div>
                ))}
              </div>
            </section>
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
      {recordingPlayer}
      {isPendingReview ? (
         // Pending review state
         <>
            <Result
                status="info"
                title="面试评分已提交"
                subTitle="AI 评估意见已生成，请确认最终结果"
                extra={
                    <div id="result-extra-buttons">
                        <Button type="primary" key="console" onClick={returnToList} style={{ marginRight: 8 }}>
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
                    <Button type="primary" key="console" onClick={returnToList} style={{ marginRight: 8 }}>
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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 340px), 1fr))', gap: 16, alignItems: 'start' }}>
            <TranscriptPane
              title="实时转写"
              subtitle="面试过程中持续保存，用于还原现场记录"
              badge="实时稿"
              accent="blue"
              segments={realtimeInterviewSegments}
              text={realtimeInterviewText}
              emptyText="本场面试没有保存实时转写"
              getSpeakerName={defaultSpeakerName}
            />
            <TranscriptPane
              title="离线转写"
              subtitle="面试结束后由离线模型生成，用于校订与 AI 分析"
              badge={hasCorrectedOfflineTranscript ? '已校订' : '离线稿'}
              accent="green"
              segments={offlineInterviewSegments}
              text={offlineInterviewText}
              emptyText="离线转写尚未生成"
              getSpeakerName={speakerName}
              playbackReady={playbackReady}
              playingSegmentKey={playingSegmentKey}
              onTogglePlayback={toggleSegmentPlayback}
            />
          </div>

          {questionTranscripts.length > 0 && (
            <List
              bordered
              style={{ marginTop: 16 }}
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
