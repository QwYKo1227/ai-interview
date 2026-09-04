import React, { useEffect, useRef, useState } from 'react';
import { Alert, Card, Descriptions, Button, InputNumber, Form, Input, Row, Col, Typography, message, Divider, Tag, Space, Spin, Modal, Popconfirm, Select, Collapse, Tooltip, List, Progress } from 'antd';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { EditOutlined, DeleteOutlined, PlusOutlined, SaveOutlined, CloseOutlined, DownloadOutlined, FilePdfOutlined, FileWordOutlined, LeftOutlined, RightOutlined, CheckCircleOutlined, CheckCircleFilled, CaretRightOutlined, AudioOutlined, LoadingOutlined, ExpandOutlined, CompressOutlined, PlayCircleOutlined, StopOutlined, ClockCircleOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import { useAuth } from '../../contexts/AuthContext';
import { getMaximizedPdfPreviewUrl } from '../../utils/pdfPreview';
import { useAuthenticatedFileUrl } from '../../hooks/useAuthenticatedFileUrl';
import { canRecordFullInterview } from './recordingControls';
import RealtimeTranscriptPanel from './RealtimeTranscriptPanel';
import { getInterviewStartTiming } from './interviewTiming';
import {
  RealtimeTranscriptionClient,
  type RealtimeSegment,
  type RealtimeStatus,
} from './realtimeTranscription';
import { useReturnToList } from '../../hooks/useListPageState';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const InterviewScore: React.FC = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const returnToList = useReturnToList('/interviews');
  const { user } = useAuth();
  const [interview, setInterview] = useState<any>(null);
  const protectedResumeFile = useAuthenticatedFileUrl(interview?.resume?.file_path);
  const [loading, setLoading] = useState(false);
  const [questions, setQuestions] = useState<any[]>([]);
  const [editingIndex, setEditingIndex] = useState<number>(-1);
  const [editForm] = Form.useForm();

  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);

  // Add Question Modal State
  const [isAddModalVisible, setIsAddModalVisible] = useState(false);
  const [addForm] = Form.useForm();

  // Scoring state
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comments, setComments] = useState<Record<string, string>>({});

  const [submitting, setSubmitting] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // 整场面试录音状态
  const [fullRecording, setFullRecording] = useState(false);
  const [fullRecordingTime, setFullRecordingTime] = useState(0);
  const [fullRecordingTimer, setFullRecordingTimer] = useState<ReturnType<typeof setInterval> | null>(null);
  const [fullRecordingBlob, setFullRecordingBlob] = useState<Blob | null>(null);
  const [fullMediaRecorder, setFullMediaRecorder] = useState<MediaRecorder | null>(null);
  const [uploadingRecording, setUploadingRecording] = useState(false);
  const [recordingUploaded, setRecordingUploaded] = useState(false); // 是否已上传
  const [fullTranscript, setFullTranscript] = useState<string>('');
  const [transcriptSegments, setTranscriptSegments] = useState<any[]>([]);
  const [realtimePartial, setRealtimePartial] = useState('');
  const [realtimeSegments, setRealtimeSegments] = useState<RealtimeSegment[]>([]);
  const [realtimeStatus, setRealtimeStatus] = useState<RealtimeStatus>('stopped');
  const [transcriptExpanded, setTranscriptExpanded] = useState(false);
  const [recordingSessionId, setRecordingSessionId] = useState<string>('');
  const [endingInterview, setEndingInterview] = useState(false);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const chunkIndexRef = useRef(0);
  const uploadQueueRef = useRef<Promise<void>>(Promise.resolve());
  const realtimeClientRef = useRef<RealtimeTranscriptionClient | null>(null);
  const realtimePersistBufferRef = useRef<RealtimeSegment[]>([]);
  const realtimePersistQueueRef = useRef<Promise<void>>(Promise.resolve());
  const realtimePersistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [liveNotes, setLiveNotes] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  const notesLoadedRef = useRef(false);

  // 直接填写评价状态
  const [directEvaluation, setDirectEvaluation] = useState('');
  const [directSuggestion, setDirectSuggestion] = useState('');
  const [directScore, setDirectScore] = useState(5);
  const [submittingDirect, setSubmittingDirect] = useState(false);

  const [startingInterview, setStartingInterview] = useState(false);
  const [scheduleClockMs, setScheduleClockMs] = useState(() => Date.now());

  // 面试计时状态
  const [elapsedTime, setElapsedTime] = useState(0); // 秒
  const [timerInterval, setTimerInterval] = useState<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (id) {
      fetchInterview(id);
    }
  }, [id]);

  useEffect(() => {
    if (interview?.lifecycle_state !== 'scheduled') return;
    setScheduleClockMs(Date.now());
    const interval = setInterval(() => setScheduleClockMs(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [interview?.lifecycle_state, interview?.interview_time]);

  useEffect(() => {
    if (!id || interview?.lifecycle_state !== 'scheduled') return;
    const interval = setInterval(() => fetchInterview(id, true), 30_000);
    return () => clearInterval(interval);
  }, [id, interview?.lifecycle_state]);

  useEffect(() => () => {
    realtimeClientRef.current?.stop();
    realtimeClientRef.current = null;
    if (realtimePersistTimerRef.current) clearTimeout(realtimePersistTimerRef.current);
    realtimePersistTimerRef.current = null;
  }, []);

  useEffect(() => {
    if (!id || !interview || notesLoadedRef.current || interview.lifecycle_state === 'scheduled') return;
    request.get(`/interviews/${id}/notes`).then((items: any) => {
      const mine = (items || []).find((item: any) => String(item.interviewer_id) === String(user?.id));
      setLiveNotes(mine?.notes || '');
      notesLoadedRef.current = true;
    }).catch(() => {});
  }, [id, interview?.lifecycle_state, user?.id]);

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onChange);
    onChange();
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  // 面试计时器
  useEffect(() => {
    if (interview?.status === 'in_progress' && interview?.started_at) {
      const startTime = new Date(interview.started_at).getTime();
      
      const updateTimer = () => {
        const now = Date.now();
        const elapsed = Math.floor((now - startTime) / 1000);
        setElapsedTime(elapsed);
      };
      
      updateTimer();
      const interval = setInterval(updateTimer, 1000);
      setTimerInterval(interval);
      
      return () => {
        clearInterval(interval);
        setTimerInterval(null);
      };
    } else {
      setElapsedTime(0);
      if (timerInterval) {
        clearInterval(timerInterval);
        setTimerInterval(null);
      }
    }
  }, [interview?.status, interview?.started_at]);

  // 格式化时间显示
  const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hours > 0) {
      return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  useEffect(() => {
    if (!id || !interview) return;
    
    if (interview.lifecycle_state === 'ended' || interview.status === 'completed') {
      navigate(`/interviews/${id}/result`, { state: location.state });
      return;
    }
    
    const panelMembers = interview?.panel_members || [];
    const isMultiInterviewer = panelMembers.length > 1;
    const userIdStr = String(user?.id);
    const myPanel = interview.panels?.find((p: any) => String(p.interviewer_id) === userIdStr);
    
    const isGeneratingQuestions = interview.questions === null || interview.questions === undefined;
    
    const shouldPoll = 
      isGeneratingQuestions ||
      interview.status === 'analyzing' ||
      (isMultiInterviewer && myPanel?.is_submitted) ||
      (!isMultiInterviewer && interview.status === 'in_progress' && interview.scores && Object.keys(interview.scores).length > 0);
    
    if (shouldPoll) {
      const interval = setInterval(async () => {
        try {
          const res = await request.get(`/interviews/${id}`) as any;
          setInterview(res);
          setQuestions(res.questions || []);
          
          if (res.status === 'completed') {
            clearInterval(interval);
            navigate(`/interviews/${id}/result`, { state: location.state });
          }
        } catch (error) {
          console.error('面试状态轮询失败');
        }
      }, 3000);
      
      return () => clearInterval(interval);
    }
  }, [id, interview?.status, interview?.panels]);

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (e) {
      message.error('无法切换全屏');
    }
  };
  
  // ... (polling logic)

  const fetchInterview = async (interviewId: string, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await request.get(`/interviews/${interviewId}`) as any;

      if (res.lifecycle_state === 'ended' || res.status === 'completed') {
         navigate(`/interviews/${interviewId}/result`, { state: location.state });
         return;
      }

      if (res.status === 'analyzing') {
         setInterview(res);
         setQuestions(res.questions || []);
         return;
      }

      setInterview(res);
      setQuestions(res.questions || []);
    } catch (error) {
      if (!silent) message.error('获取面试详情失败');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // “开始面试”与开始录音是同一个原子化用户动作。
  const handleStartInterview = () => {
    const timing = getInterviewStartTiming(interview?.interview_time);
    if (!timing.isEarlyStart) {
      void startFullRecording();
      return;
    }

    Modal.confirm({
      title: '确认提前开始面试',
      content: '当前尚未到计划开始时间。提前开始后将立即启动录音，是否继续？',
      okText: '继续',
      cancelText: '取消',
      onOk: startFullRecording,
    });
  };

  const handleAddQuestionClick = () => {
    addForm.resetFields();
    addForm.setFieldsValue({
      difficulty: 'intermediate',
      type: 'technical'
    });
    setIsAddModalVisible(true);
  };

  const handleAddModalOk = async () => {
    try {
      const values = await addForm.validateFields();
      const newQuestion = {
        ...values,
        follow_up: values.follow_up ? values.follow_up.split('\n').filter(Boolean) : [],
        resume_association: values.resume_association || '',
        reference_answer: values.reference_answer || '',
        grading_criteria: values.grading_criteria || ''
      };
      // Sync to backend
      const updatedQuestions = [...questions, newQuestion];
      await request.put(`/interviews/${id}/questions`, updatedQuestions);

      setQuestions(updatedQuestions);
      setIsAddModalVisible(false);
      message.success('添加成功');
      
      // Scroll to bottom
      setTimeout(() => {
        // Switch to the new question
        setCurrentQuestionIndex(updatedQuestions.length - 1);
      }, 100);
    } catch (error) {
      message.error('添加失败');
    }
  };

  const handleEdit = (index: number) => {
    setEditingIndex(index);
    const q = questions[index];
    editForm.setFieldsValue({
        ...q,
        follow_up: Array.isArray(q.follow_up) ? q.follow_up.join('\n') : q.follow_up
    });
  };

  const handleSaveQuestion = async () => {
    try {
      const values = await editForm.validateFields();
      const newQuestions = [...questions];
      newQuestions[editingIndex] = { 
          ...newQuestions[editingIndex], 
          ...values,
          follow_up: values.follow_up ? values.follow_up.split('\n').filter(Boolean) : []
      };
      
      // Sync to backend
      await request.put(`/interviews/${id}/questions`, newQuestions);
      
      setQuestions(newQuestions);
      setEditingIndex(-1);
      message.success('保存成功');
    } catch (error) {
      message.error('保存失败');
    }
  };

  const handleCancelEdit = () => {
    setEditingIndex(-1);
  };

  const handleDelete = async (index: number) => {
    try {
      const newQuestions = [...questions];
      newQuestions.splice(index, 1);

      // 调整分数和评语的索引
      const newScores: Record<string, number> = {};
      const newComments: Record<string, string> = {};
      
      Object.keys(scores).forEach(key => {
        const idx = parseInt(key);
        if (idx < index) {
          newScores[key] = scores[key];
        } else if (idx > index) {
          newScores[String(idx - 1)] = scores[key];
        }
      });
      
      Object.keys(comments).forEach(key => {
        const idx = parseInt(key);
        if (idx < index) {
          newComments[key] = comments[key];
        } else if (idx > index) {
          newComments[String(idx - 1)] = comments[key];
        }
      });

      // Sync to backend
      await request.put(`/interviews/${id}/questions`, newQuestions);
      
      // 更新分数和评语到后端
      if (Object.keys(newScores).length > 0 || Object.keys(newComments).length > 0) {
        await request.post(`/interviews/${id}/score`, {
          scores: newScores,
          comments: newComments
        });
      }

      setQuestions(newQuestions);
      setScores(newScores);
      setComments(newComments);
      message.success('删除成功');

      // Adjust current index if needed
      if (currentQuestionIndex >= newQuestions.length && newQuestions.length > 0) {
        setCurrentQuestionIndex(newQuestions.length - 1);
      }
    } catch (error) {
      message.error('删除失败');
    }
  };

  const uploadRecordingChunk = async (sessionId: string, index: number, blob: Blob) => {
    if (!id) return;
    let lastError: unknown;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        const formData = new FormData();
        formData.append('session_id', sessionId);
        formData.append('file', blob, `chunk-${index}.webm`);
        await request.post(`/interviews/${id}/recording/chunks/${index}`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        return;
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)));
      }
    }
    throw lastError;
  };

  const postRealtimeTranscriptBatch = async (sessionId: string, segments: RealtimeSegment[]) => {
    let lastError: unknown;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        await request.post(`/interviews/${id}/recording/realtime-transcript`, {
          session_id: sessionId,
          segments,
        });
        return;
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)));
      }
    }
    throw lastError;
  };

  const flushRealtimeTranscript = (sessionId: string): Promise<void> => {
    if (realtimePersistTimerRef.current) {
      clearTimeout(realtimePersistTimerRef.current);
      realtimePersistTimerRef.current = null;
    }
    const batch = realtimePersistBufferRef.current.splice(0);
    if (!batch.length) return realtimePersistQueueRef.current;

    const operation = realtimePersistQueueRef.current.then(() => (
      postRealtimeTranscriptBatch(sessionId, batch)
    ));
    realtimePersistQueueRef.current = operation.catch(() => {
      const bufferedIds = new Set(realtimePersistBufferRef.current.map((segment) => segment.id));
      realtimePersistBufferRef.current.unshift(
        ...batch.filter((segment) => !bufferedIds.has(segment.id)),
      );
    });
    return operation;
  };

  const queueRealtimeTranscript = (sessionId: string, segment: RealtimeSegment) => {
    if (realtimePersistBufferRef.current.some((item) => item.id === segment.id)) return;
    realtimePersistBufferRef.current.push(segment);
    if (realtimePersistBufferRef.current.length >= 10) {
      void flushRealtimeTranscript(sessionId).catch(() => {});
      return;
    }
    if (!realtimePersistTimerRef.current) {
      realtimePersistTimerRef.current = setTimeout(() => {
        realtimePersistTimerRef.current = null;
        void flushRealtimeTranscript(sessionId).catch(() => {});
      }, 2000);
    }
  };

  // 整场面试录音功能：录音分片在后台按顺序自动上传。
  const startFullRecording = async () => {
    if (!id) return;
    setStartingInterview(true);
    try {
      const reservation = await request.post(`/interviews/${id}/recording/reserve`) as any;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported?.('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';
      const recorder = new MediaRecorder(stream, { mimeType });
      const sessionId = String(reservation.session_id);
      chunkIndexRef.current = reservation.next_chunk_index || 0;
      uploadQueueRef.current = Promise.resolve();
      realtimePersistBufferRef.current = [];
      realtimePersistQueueRef.current = Promise.resolve();
      if (realtimePersistTimerRef.current) clearTimeout(realtimePersistTimerRef.current);
      realtimePersistTimerRef.current = null;
      recordingStreamRef.current = stream;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          const index = chunkIndexRef.current;
          chunkIndexRef.current += 1;
          uploadQueueRef.current = uploadQueueRef.current.then(() => (
            uploadRecordingChunk(sessionId, index, e.data)
          ));
        }
      };

      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop());
        recordingStreamRef.current = null;
      };

      recorder.start(20_000);
      try {
        await request.post(`/interviews/${id}/recording/confirm`, { session_id: sessionId });
      } catch (error) {
        recorder.stop();
        throw error;
      }
      setRecordingSessionId(sessionId);
      setFullMediaRecorder(recorder);
      setFullRecording(true);
      setFullRecordingTime(0);
      setRealtimePartial('');
      setRealtimeSegments([]);
      setRealtimeStatus('connecting');
      setRecordingUploaded(false);

      // 启动计时器
      const timer = setInterval(() => {
        setFullRecordingTime(prev => prev + 1);
      }, 1000);
      setFullRecordingTimer(timer);

      const realtimeClient = new RealtimeTranscriptionClient(id, sessionId, stream, {
        onStatus: setRealtimeStatus,
        onPartial: setRealtimePartial,
        onSegment: (segment) => {
          setRealtimeSegments((current) => (
            current.some((item) => item.id === segment.id) ? current : [...current, segment]
          ));
          queueRealtimeTranscript(sessionId, segment);
        },
      });
      realtimeClientRef.current = realtimeClient;
      void realtimeClient.start();

      message.success(interview?.lifecycle_state === 'in_progress' ? '已接管面试录音' : '面试已开始并自动录音');
      fetchInterview(id, true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '无法开始面试，请检查麦克风权限');
    } finally {
      setStartingInterview(false);
    }
  };

  useEffect(() => {
    if (!id || !recordingSessionId || !fullRecording) return;
    const heartbeat = setInterval(() => {
      request.post(`/interviews/${id}/recording/heartbeat`, { session_id: recordingSessionId }).catch(() => {});
    }, 15_000);
    return () => clearInterval(heartbeat);
  }, [id, recordingSessionId, fullRecording]);

  const performEndInterview = async () => {
    if (!id || !recordingSessionId || !fullMediaRecorder) return;
    setEndingInterview(true);
    try {
      realtimeClientRef.current?.stop();
      realtimeClientRef.current = null;
      if (fullMediaRecorder.state !== 'inactive') {
        await new Promise<void>((resolve) => {
          fullMediaRecorder.addEventListener('stop', () => resolve(), { once: true });
          fullMediaRecorder.stop();
        });
      }
      setFullRecording(false);
      if (fullRecordingTimer) clearInterval(fullRecordingTimer);
      setFullRecordingTimer(null);

      await uploadQueueRef.current;
      try {
        await flushRealtimeTranscript(recordingSessionId);
        await realtimePersistQueueRef.current;
      } catch {
        message.warning('实时字幕暂未全部保存，完整录音仍会正常转写');
      }
      await request.post(`/interviews/${id}/end`, { session_id: recordingSessionId });
      await request.post(`/interviews/${id}/recording/seal`, { session_id: recordingSessionId });
      message.success('面试已结束，AI 正在分析录音');
      navigate(`/interviews/${id}/result`, { state: location.state });
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '录音尚未完整封存，请稍后重试结束面试');
    } finally {
      setEndingInterview(false);
    }
  };

  const handleEndInterview = () => {
    Modal.confirm({
      title: '结束面试',
      content: '结束后将停止并封存录音，随后自动进行 AI 分析。是否继续？',
      okText: '结束面试',
      cancelText: '继续面试',
      okButtonProps: { danger: true },
      onOk: performEndInterview,
    });
  };

  const handleForceEndInterview = () => {
    let reason = '';
    Modal.confirm({
      title: '强制结束面试',
      content: <Input.TextArea rows={3} placeholder="请填写强制结束原因" onChange={(event) => { reason = event.target.value; }} />,
      okText: '强制结束',
      cancelText: '返回',
      okButtonProps: { danger: true },
      onOk: async () => {
        if (!reason.trim()) {
          message.error('请填写强制结束原因');
          return Promise.reject();
        }
        if (!id) return Promise.reject();
        setEndingInterview(true);
        try {
          await request.post(`/interviews/${id}/force-end`, { reason: reason.trim() });
          message.success('面试已强制结束，可继续填写人工评价');
          navigate(`/interviews/${id}/result`, { state: location.state });
        } catch (error: any) {
          message.error(error?.response?.data?.detail || '强制结束面试失败');
          return Promise.reject();
        } finally {
          setEndingInterview(false);
        }
      },
    });
  };

  const uploadFullRecording = async () => {
    if (!fullRecordingBlob || !id || recordingUploaded) return;

    setUploadingRecording(true);
    try {
      const formData = new FormData();
      formData.append('file', fullRecordingBlob, 'full_interview.webm');

      const response = await request.post(`/interviews/${id}/full-audio`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      }) as any;

      if (response.transcript) {
        // transcript 可能是字符串或对象
        const transcriptText = typeof response.transcript === 'string' 
          ? response.transcript 
          : (response.transcript.text || '');
        setFullTranscript(response.formatted_transcript || transcriptText);
        if (response.segments && Array.isArray(response.segments)) {
          setTranscriptSegments(response.segments);
        }
        setRecordingUploaded(true);
        message.success('录音已上传，AI正在分析...');
      } else {
        setRecordingUploaded(true);
        message.success('录音已上传');
      }
    } catch (error) {
      message.error('上传录音失败');
    } finally {
      setUploadingRecording(false);
    }
  };

  // 直接提交评价（支持同时上传录音）
  const handleSubmitDirectEvaluation = async () => {
    if (!directEvaluation.trim()) {
      message.error('请填写面试评价');
      return;
    }

    setSubmittingDirect(true);
    try {
      const panelMembers = interview?.panel_members || [];
      const isMultiInterviewer = panelMembers.length > 1;
      
      // 如果有录音未上传，先上传录音
      if (fullRecordingBlob && !recordingUploaded) {
        setUploadingRecording(true);
        const formData = new FormData();
        formData.append('file', fullRecordingBlob, 'full_interview.webm');
        formData.append('evaluation', directEvaluation);
        formData.append('suggestion', directSuggestion);
        formData.append('score', directScore.toString());

        const response = await request.post(`/interviews/${id}/direct-evaluation-with-audio`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });

        setInterview(response);
        setRecordingUploaded(true);
        
        if (isMultiInterviewer) {
          const updatedInterview = await request.get(`/interviews/${id}`) as any;
          setInterview(updatedInterview);
          
          const allSubmitted = panelMembers.every((memberId: string) => 
            updatedInterview.panels?.some((p: any) => String(p.interviewer_id) === String(memberId) && p.is_submitted)
          );
          
          if (allSubmitted) {
            message.success('所有面试官已提交，AI正在综合分析...');
          } else {
            message.success('评价已提交，等待其他面试官...');
          }
        } else {
          message.success('评价和录音已提交，AI正在综合分析...');
        }
      } else {
        const res = await request.post(`/interviews/${id}/direct-evaluation`, {
          evaluation: directEvaluation,
          suggestion: directSuggestion,
          score: directScore,
          transcript: fullTranscript || null
        });
        setInterview(res);
        
        if (isMultiInterviewer) {
          const updatedInterview = await request.get(`/interviews/${id}`) as any;
          setInterview(updatedInterview);
          
          const allSubmitted = panelMembers.every((memberId: string) => 
            updatedInterview.panels?.some((p: any) => String(p.interviewer_id) === String(memberId) && p.is_submitted)
          );
          
          if (allSubmitted) {
            message.success('所有面试官已提交，AI正在综合分析...');
          } else {
            message.success('评价已提交，等待其他面试官...');
          }
        } else {
          message.success('评价已提交');
        }
      }
    } catch (error) {
      message.error('提交评价失败');
    } finally {
      setSubmittingDirect(false);
      setUploadingRecording(false);
    }
  };

  const handleSubmitScore = async () => {
    for (let i = 0; i < questions.length; i++) {
      if (scores[i] === undefined) {
        message.error(`请为第 ${i + 1} 题打分`);
        return;
      }
    }

    try {
      setSubmitting(true);
      
      // 如果有录音未上传，先上传录音
      if (fullRecordingBlob && !recordingUploaded) {
        setUploadingRecording(true);
        try {
          const formData = new FormData();
          formData.append('file', fullRecordingBlob, 'full_interview.webm');
          const response = await request.post(`/interviews/${id}/full-audio`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          }) as any;
          
          if (response.transcript) {
            const transcriptText = typeof response.transcript === 'string' 
              ? response.transcript 
              : (response.transcript.text || '');
            setFullTranscript(response.formatted_transcript || transcriptText);
            if (response.segments && Array.isArray(response.segments)) {
              setTranscriptSegments(response.segments);
            }
          }
          setRecordingUploaded(true);
        } catch (e) {
          console.error('上传录音失败');
        } finally {
          setUploadingRecording(false);
        }
      }
      
      const panelMembers = interview?.panel_members || [];
      const isMultiInterviewer = panelMembers.length > 1;
      
      if (isMultiInterviewer) {
        await request.post(`/interviews/${id}/panel-score`, {
          scores,
          comments 
        }) as any;
        
        const updatedInterview = await request.get(`/interviews/${id}`) as any;
        setInterview(updatedInterview);
        
        const allSubmitted = panelMembers.every((memberId: string) => {
          const found = updatedInterview.panels?.some((p: any) => {
            const match = String(p.interviewer_id) === String(memberId) && p.is_submitted;
            return match;
          });
          return found;
        });
        
        if (allSubmitted) {
          message.success('所有面试官已提交，AI正在分析...');
        } else {
          message.success('评分已提交，等待其他面试官...');
        }
      } else {
        const res = await request.post(`/interviews/${id}/score`, {
          scores,
          comments 
        }) as any;
        
        setInterview(res);
        message.success('评分已提交，AI正在分析...');
      }
      
    } catch (error) {
      message.error('提交评分失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const fileUrl = protectedResumeFile.url;
  const isPdf = protectedResumeFile.contentType === 'application/pdf';
  const pdfPreviewUrl = isPdf ? getMaximizedPdfPreviewUrl(fileUrl) : '';

  if (loading && !interview) {
    return (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
            <Spin size="large" tip="加载中..." />
        </div>
    );
  }

  const handlePrevQuestion = () => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(currentQuestionIndex - 1);
    }
  };

  const handleNextQuestion = () => {
    if (currentQuestionIndex < questions.length - 1) {
      setCurrentQuestionIndex(currentQuestionIndex + 1);
    }
  };

  const handleJumpToQuestion = (index: number) => {
    setCurrentQuestionIndex(index);
  };

  const handleSaveNotes = async () => {
    if (!id || interview?.lifecycle_state !== 'in_progress') return;
    setSavingNotes(true);
    try {
      await request.put(`/interviews/${id}/notes`, { notes: liveNotes });
      message.success('面试笔记已保存');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存笔记失败');
    } finally {
      setSavingNotes(false);
    }
  };

  const currentQuestion = questions[currentQuestionIndex];

  if (!interview) return null;

  if (interview.questions === null || interview.questions === undefined) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
            <Spin size="large" />
            <Title level={4} style={{ marginTop: 24, color: '#64748B' }}>AI 正在生成面试题，请稍候...</Title>
            <Text type="secondary">根据简历内容和题库生成定制化题目通常需要 10-20 秒</Text>
        </div>
      );
  }

  const panelMembers = interview?.panel_members || [];
  const isMultiInterviewer = panelMembers.length > 1;
  
  if (isMultiInterviewer && interview.panels) {
    const userIdStr = String(user?.id);
    
    const myPanel = interview.panels.find((p: any) => {
      const match = String(p.interviewer_id) === userIdStr;
      return match;
    });
    
    const allSubmitted = panelMembers.every((memberId: string) => {
      const found = interview.panels?.some((p: any) => {
        const match = String(p.interviewer_id) === String(memberId) && p.is_submitted;
        return match;
      });
      return found;
    });
    
    if (myPanel?.is_submitted && !allSubmitted) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
            <CheckCircleOutlined style={{ fontSize: 64, color: '#52c41a', marginBottom: 24 }} />
            <Title level={4} style={{ color: '#64748B' }}>评分已提交</Title>
            <Text type="secondary">等待其他面试官提交评分...</Text>
            <div style={{ marginTop: 24 }}>
              <Space direction="vertical" size="small">
                {panelMembers.map((memberId: string) => {
                  const panel = interview.panels?.find((p: any) => String(p.interviewer_id) === String(memberId));
                  const isMe = String(memberId) === String(user?.id);
                  return (
                    <Tag key={memberId} color={panel?.is_submitted ? 'success' : 'processing'}>
                      {isMe ? '我' : `面试官 ${String(memberId).slice(0, 8)}`}
                      {panel?.is_submitted ? ' - 已提交' : ' - 待提交'}
                    </Tag>
                  );
                })}
              </Space>
            </div>
            <div style={{ marginTop: 24 }}>
              <Button onClick={returnToList}>返回列表</Button>
            </div>
        </div>
      );
    }
  }

  if (interview.status === 'analyzing' && interview.lifecycle_state !== 'ended') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
            <Spin size="large" />
            <Title level={4} style={{ marginTop: 24, color: '#64748B' }}>AI 正在分析面试结果，请稍候...</Title>
            <Text type="secondary">正在根据评分生成综合评价报告</Text>
            <div style={{ marginTop: 24 }}>
              <Button onClick={returnToList}>返回列表</Button>
            </div>
        </div>
      );
  }

  const skippedAiQuestions = interview.questions.length === 0;
  const canOperateRecording = canRecordFullInterview(interview?.panel_members || [], user?.id);
  const isHrOrAdmin = user?.role === 'admin' || user?.role === 'hr';
  const startTiming = getInterviewStartTiming(interview?.interview_time, scheduleClockMs);

  const questionFormContent = (
    <>
      <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
        <Input placeholder="例如：Java并发编程" />
      </Form.Item>
      <Form.Item name="content" label="问题内容" rules={[{ required: true, message: '请输入问题内容' }]}>
        <TextArea rows={3} placeholder="详细的问题描述" />
      </Form.Item>
      <Form.Item name="resume_association" label="简历关联">
        <TextArea rows={2} placeholder="关联的简历经历" />
      </Form.Item>
      <Form.Item name="reference_answer" label="参考答案">
        <TextArea rows={3} placeholder="理想的回答要点" />
      </Form.Item>
      <Form.Item name="grading_criteria" label="评分标准">
        <TextArea rows={3} placeholder="评分细则" />
      </Form.Item>
      <Form.Item name="follow_up" label="追问方向 (每行一个)">
        <TextArea rows={2} placeholder="追问1&#10;追问2" />
      </Form.Item>
      <Row gutter={16}>
          <Col span={12}>
              <Form.Item name="difficulty" label="难度">
                  <Select>
                      <Select.Option value="junior">初级</Select.Option>
                      <Select.Option value="intermediate">中级</Select.Option>
                      <Select.Option value="senior">高级</Select.Option>
                  </Select>
              </Form.Item>
          </Col>
          <Col span={12}>
              <Form.Item name="type" label="类型">
                  <Select>
                      <Select.Option value="technical">技术</Select.Option>
                      <Select.Option value="project">项目</Select.Option>
                      <Select.Option value="behavioral">行为</Select.Option>
                  </Select>
              </Form.Item>
          </Col>
      </Row>
    </>
  );

  const headerExtra = (
      <Space>
         <Tooltip title="返回面试列表">
           <Button icon={<LeftOutlined />} onClick={returnToList} />
         </Tooltip>

         {/* 面试计时器 */}
         {interview?.status === 'in_progress' && (
           <Tag color="processing" style={{ fontSize: 16, padding: '4px 12px', marginRight: 8 }}>
             <ClockCircleOutlined style={{ marginRight: 4 }} />
             {formatTime(elapsedTime)}
           </Tag>
         )}

         {/* 开始面试即开始录音；断线后可从同一入口接管。 */}
         {canOperateRecording && (interview?.lifecycle_state === 'scheduled'
           || (interview?.lifecycle_state === 'in_progress' && !fullRecording)) && (
           <Tooltip title={interview?.lifecycle_state === 'scheduled' && !startTiming.canStart
             ? `面试尚未进入可提前开始时间，距离按钮启用还有 ${startTiming.countdownText}`
             : interview?.lifecycle_state === 'scheduled' && startTiming.isEarlyStart
               ? '当前已可提前开始面试'
               : interview?.lifecycle_state === 'scheduled' ? '开始面试并录音' : '接管录音'}>
             <Button
               type="primary"
               icon={<PlayCircleOutlined />}
               onClick={handleStartInterview}
               loading={startingInterview}
               disabled={interview?.lifecycle_state === 'scheduled' && !startTiming.canStart}
             >
               {interview?.lifecycle_state === 'scheduled' ? '开始面试' : '接管录音'}
             </Button>
           </Tooltip>
         )}

         {fullRecording && (
           <Tooltip title="停止录音并结束面试">
             <Button danger type="primary" icon={<StopOutlined />} loading={endingInterview} onClick={handleEndInterview}>
               结束面试
             </Button>
           </Tooltip>
         )}

         {isHrOrAdmin && interview?.lifecycle_state === 'in_progress' && !fullRecording && (
           <Tooltip title="填写原因并强制结束面试">
             <Button danger icon={<StopOutlined />} loading={endingInterview} onClick={handleForceEndInterview}>强制结束</Button>
           </Tooltip>
         )}

         <Tooltip title={isFullscreen ? '退出全屏' : '全屏模式'}>
           <Button icon={isFullscreen ? <CompressOutlined /> : <ExpandOutlined />} onClick={toggleFullscreen} />
         </Tooltip>
         
         <Tooltip title="添加题目">
           <Button icon={<PlusOutlined />} onClick={handleAddQuestionClick} />
         </Tooltip>

         {fullRecording && <Tag color="error" icon={<AudioOutlined />}>录音中 {formatTime(fullRecordingTime)}</Tag>}
      </Space>
  );

  return (
    <div style={{ height: isFullscreen ? '100vh' : 'calc(100vh - 100px)', display: 'flex', gap: '24px' }}>
      {/* Left: Resume Preview */}
      <div style={{ flex: 1, background: '#fff', borderRadius: '16px', border: '1px solid #E2E8F0', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '12px 24px', borderBottom: '1px solid #E2E8F0', background: '#F8FAFC', display: 'flex', justifyContent: 'space-between' }}>
          <Text strong>简历预览: {interview.resume?.candidate_name}</Text>
          <Button type="link" icon={<DownloadOutlined />} href={fileUrl} download>下载</Button>
        </div>
        <div style={{ flex: 1, minHeight: 0, background: '#F1F5F9', display: transcriptExpanded ? 'none' : 'block' }}>
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
                <Text type="secondary">暂不支持预览，请下载查看</Text>
              </div>
            )
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#94A3B8' }}>暂无文件</div>
          )}
        </div>
        {(fullRecording || realtimeSegments.length > 0 || realtimePartial || realtimeStatus !== 'stopped') && (
          <RealtimeTranscriptPanel
            active={fullRecording}
            status={realtimeStatus}
            segments={realtimeSegments}
            partial={realtimePartial}
            expanded={transcriptExpanded}
            onExpandedChange={setTranscriptExpanded}
          />
        )}
      </div>

      {/* Right: Interview Questions & Scoring */}
      <div id="questions-container" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ flexShrink: 0, paddingRight: '4px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <Title level={4} style={{ margin: 0 }}>面试题目 & 评分</Title>
            {headerExtra}
          </div>

          {interview?.lifecycle_state === 'scheduled' && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={`面试计划于 ${new Date(interview.interview_time).toLocaleString()} 开始`}
              description={!startTiming.canStart
                ? `当前可提前查看资料，距离“开始面试”按钮启用还有 ${startTiming.countdownText}。`
                : startTiming.isEarlyStart
                  ? '当前已可提前开始面试。'
                  : '当前已可开始面试。'}
            />
          )}

          {/* Question Navigation */}
          <div style={{ marginBottom: 16, overflowX: 'auto', whiteSpace: 'nowrap', paddingBottom: 8, paddingTop: 4, paddingLeft: 4 }}>
            <Space>
              {questions.map((_, index) => {
                const isScored = scores[index] !== undefined;
                const isCurrent = index === currentQuestionIndex;
                return (
                  <Button
                    key={index}
                    type={isCurrent ? 'primary' : 'default'}
                    shape="circle"
                    onClick={() => handleJumpToQuestion(index)}
                    style={{
                      borderColor: isScored ? '#10B981' : undefined,
                      color: !isCurrent && isScored ? '#10B981' : undefined,
                      fontWeight: isCurrent ? 'bold' : 'normal'
                    }}
                  >
                    {index + 1}
                  </Button>
                );
              })}
            </Space>
          </div>

        </div>

        <div style={{ flex: 1, overflow: 'hidden', paddingRight: '4px', paddingBottom: '4px', display: 'flex', flexDirection: 'column' }}>
          {skippedAiQuestions ? (
            <Card
              style={{ flex: 1, borderRadius: '12px', border: '1px solid #E2E8F0', overflow: 'auto' }}
              title={<Text strong>实时面试笔记</Text>}
            >
              <Text type="secondary">本场面试未预生成题目。录音由“开始面试”自动启动，正式人工评价将在面试结束后的结果页填写。</Text>
              <TextArea
                rows={14}
                style={{ marginTop: 20 }}
                placeholder="记录现场观察；面试结束后笔记将冻结并向本场参与者公开。"
                value={liveNotes}
                onChange={(e) => setLiveNotes(e.target.value)}
                onBlur={handleSaveNotes}
              />
              <Button icon={<SaveOutlined />} loading={savingNotes} onClick={handleSaveNotes} style={{ marginTop: 12 }}>
                保存笔记
              </Button>
            </Card>
          ) : currentQuestion && (
            <Card 
              key={currentQuestionIndex}
              style={{ flex: 1, borderRadius: '12px', border: '1px solid #E2E8F0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
              bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', paddingBottom: 0 }}
              title={
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space>
                    <Tag color="blue">第 {currentQuestionIndex + 1} / {questions.length} 题</Tag>
                    <Text strong>{currentQuestion.title || '无标题'}</Text>
                  </Space>
                  {editingIndex !== currentQuestionIndex && (
                    <Space>
                      <Button type="text" icon={<EditOutlined />} onClick={() => handleEdit(currentQuestionIndex)} />
                      <Popconfirm title="确定删除此题吗？" onConfirm={() => handleDelete(currentQuestionIndex)}>
                        <Button type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Space>
                  )}
                </div>
              }
            >
              {editingIndex === currentQuestionIndex ? (
                <div style={{ flex: 1, overflowY: 'auto' }}>
                  <Form form={editForm} layout="vertical">
                    {questionFormContent}
                    <Space style={{ justifyContent: 'flex-end', width: '100%', marginTop: 16, marginBottom: 16 }}>
                      <Button onClick={handleCancelEdit}>取消</Button>
                      <Button type="primary" onClick={handleSaveQuestion}>保存</Button>
                    </Space>
                  </Form>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                  <div style={{ flex: 1, overflowY: 'auto' }}>
                    <Descriptions column={1} size="small" bordered>
                      <Descriptions.Item label="问题内容">
                        <Paragraph style={{ margin: 0, fontSize: 16 }}>{currentQuestion.content}</Paragraph>
                      </Descriptions.Item>
                      {currentQuestion.resume_association && (
                        <Descriptions.Item label="简历关联">
                          <Text type="secondary">{currentQuestion.resume_association}</Text>
                        </Descriptions.Item>
                      )}
                    </Descriptions>

                    <div style={{ marginTop: 16 }}>
                      {currentQuestion.follow_up && (
                        <div style={{ marginBottom: 16, background: '#F0F9FF', padding: '12px 16px', borderRadius: 8, border: '1px solid #BAE6FD' }}>
                          <Text strong style={{ color: '#0369A1', display: 'block', marginBottom: 8 }}>追问方向</Text>
                          <ul style={{ paddingLeft: 20, margin: 0, color: '#0C4A6E' }}>
                            {(Array.isArray(currentQuestion.follow_up) ? currentQuestion.follow_up : [currentQuestion.follow_up]).map((item: string, i: number) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      
                      <Collapse
                        ghost
                        expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
                        items={[
                          {
                            key: '1',
                            label: <Text strong>参考答案</Text>,
                            children: <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#64748B' }}>{currentQuestion.reference_answer}</Paragraph>,
                          },
                          {
                            key: '2',
                            label: <Text strong>评分标准</Text>,
                            children: <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#64748B' }}>{typeof currentQuestion.grading_criteria === 'string' ? currentQuestion.grading_criteria : JSON.stringify(currentQuestion.grading_criteria)}</Paragraph>,
                          }
                        ]}
                      />
                    </div>
                  
                    <div style={{ marginTop: 24, background: '#F8FAFC', padding: 16, borderRadius: 8 }}>
                      <Text strong>我的实时面试笔记</Text>
                      <TextArea
                        rows={4}
                        style={{ marginTop: 8 }}
                        placeholder="记录现场观察；面试结束后笔记将冻结并向本场参与者公开。"
                        value={liveNotes}
                        onChange={(e) => setLiveNotes(e.target.value)}
                        onBlur={handleSaveNotes}
                      />
                    </div>
                  </div>
                  
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, marginTop: 24, paddingTop: 16, borderTop: '1px solid #E2E8F0', flexShrink: 0 }}>
                    <Button 
                      icon={<LeftOutlined />} 
                      onClick={handlePrevQuestion} 
                      disabled={currentQuestionIndex === 0}
                      style={{ paddingLeft: 24, paddingRight: 24, background: '#F8FAFC' }}
                    >
                      上一题
                    </Button>
                    {currentQuestionIndex < questions.length - 1 ? (
                      <Button 
                        type="primary" 
                        icon={<RightOutlined />} 
                        onClick={handleNextQuestion}
                        style={{ paddingLeft: 24, paddingRight: 24}}
                      >
                        下一题
                      </Button>
                    ) : (
                      <Button icon={<SaveOutlined />} onClick={handleSaveNotes} loading={savingNotes}>
                        保存笔记
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>

      {/* Add Question Modal */}
      <Modal
        title="添加面试题"
        open={isAddModalVisible}
        onOk={handleAddModalOk}
        onCancel={() => setIsAddModalVisible(false)}
        width={600}
        okText="添加"
        cancelText="取消"
      >
        <Form form={addForm} layout="vertical">
            {questionFormContent}
        </Form>
      </Modal>

    </div>
  );
};

export default InterviewScore;
