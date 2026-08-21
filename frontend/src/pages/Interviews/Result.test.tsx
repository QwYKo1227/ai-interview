import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InterviewResultPage, { mergeAdjacentTranscriptSegments } from './Result'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('html2pdf.js', () => ({
  default: vi.fn(),
}))

vi.mock('../../contexts/AuthContext', () => ({
  useOptionalAuth: () => ({ user: { id: 'interviewer-1', role: 'interviewer' } }),
}))

const interviewPayload = {
  id: 'interview-1',
  resume_id: 'resume-1',
  status: 'completed',
  result: 'passed',
  evaluation: 'Evaluation',
  suggestion: 'Hire',
  scores: {},
  comments: {},
  questions: [
    { title: 'System design' },
  ],
  transcripts: {
    full_interview: 'Welcome. Please introduce yourself.',
    full_interview_data: {
      text: 'Welcome. Please introduce yourself.',
      segments: [
        { start: 0, end: 4.2, text: 'Welcome.' },
        { start: 4.2, end: 9, text: 'Please introduce yourself.' },
      ],
    },
    0: 'I designed a distributed task scheduler.',
  },
  resume: {
    match_score: 88,
    screening_result: 'passed',
    ai_review: 'Strong initial match.',
  },
}

const renderResult = () => render(
  <MemoryRouter initialEntries={['/interviews/interview-1/result']}>
    <Routes>
      <Route path="/interviews/:id/result" element={<InterviewResultPage />} />
    </Routes>
  </MemoryRouter>,
)

describe('InterviewResultPage', () => {
  beforeEach(() => {
    vi.mocked(request.get).mockReset().mockResolvedValue(interviewPayload)
    vi.mocked(request.post).mockReset()
  })

  afterEach(() => cleanup())

  it('shows the complete interview and per-question transcripts', async () => {
    renderResult()

    expect(await screen.findByText('面试过程记录')).toBeInTheDocument()
    expect(screen.getByText('Welcome.')).toBeInTheDocument()
    expect(screen.getByText('Please introduce yourself.')).toBeInTheDocument()
    expect(screen.getByText('I designed a distributed task scheduler.')).toBeInTheDocument()
  })

  it('shows persisted realtime segments while the offline transcript is unavailable', async () => {
    vi.mocked(request.get).mockResolvedValue({
      ...interviewPayload,
      transcripts: {
        realtime_full_interview: '实时保存的候选人回答',
        realtime_full_interview_data: {
          text: '实时保存的候选人回答',
          source: 'realtime',
          segments: [
            {
              id: 'stream-1:segment-1',
              start: 1,
              end: 3,
              speaker: 'speaker_0',
              text: '实时保存的候选人回答',
            },
          ],
        },
      },
    })

    renderResult()

    expect(await screen.findByText('实时保存的候选人回答')).toBeInTheDocument()
    expect(screen.getByText('实时转写')).toBeInTheDocument()
    expect(screen.getByText('离线转写')).toBeInTheDocument()
    expect(screen.getByText('离线转写尚未生成')).toBeInTheDocument()
  })

  it('keeps realtime and offline transcripts visible side by side', async () => {
    vi.mocked(request.get).mockResolvedValue({
      ...interviewPayload,
      transcripts: {
        realtime_full_interview_data: {
          segments: [{ start: 0, end: 2, speaker: 'speaker_0', text: '实时稿内容' }],
        },
        full_interview_data: {
          segments: [{ start: 0, end: 2, speaker: 'speaker_1', text: '离线稿内容' }],
        },
      },
    })

    renderResult()

    expect(await screen.findByText('实时稿内容')).toBeInTheDocument()
    expect(screen.getByText('离线稿内容')).toBeInTheDocument()
    expect(screen.getByText('实时稿')).toBeInTheDocument()
    expect(screen.getByText('离线稿')).toBeInTheDocument()
  })

  it('shows process records and scores below resume review, with evaluation last', async () => {
    renderResult()

    const sectionTitles = [
      await screen.findByText('简历初审评价'),
      screen.getByText('面试过程记录'),
      screen.getByText('得分详情'),
      screen.getByText('综合评价'),
    ]

    sectionTitles.slice(0, -1).forEach((title, index) => {
      expect(
        title.compareDocumentPosition(sectionTitles[index + 1])
          & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy()
    })
  })

  it('plays an offline transcript segment and stops at its end time', async () => {
    vi.mocked(request.get).mockResolvedValue({
      ...interviewPayload,
      audio_records: {
        full_interview: '/api/files/11111111-1111-1111-1111-111111111111',
      },
    })
    vi.mocked(request.post).mockResolvedValue({
      url: '/api/public/files/playback-token',
    })

    const view = renderResult()

    await waitFor(() => expect(request.post).toHaveBeenCalledWith(
      '/files/11111111-1111-1111-1111-111111111111/public-token',
      { ttl_seconds: 3600 },
    ))
    const audio = view.container.querySelector('audio') as HTMLAudioElement
    audio.play = vi.fn().mockResolvedValue(undefined)
    audio.pause = vi.fn()
    fireEvent.loadedMetadata(audio)

    const playButton = await screen.findByRole('button', { name: '播放 00:00–00:04' })
    fireEvent.click(playButton)

    await waitFor(() => expect(audio.play).toHaveBeenCalledOnce())
    expect(audio.currentTime).toBe(0)

    audio.currentTime = 4.2
    fireEvent.timeUpdate(audio)
    expect(audio.pause).toHaveBeenCalledOnce()
  })

  it('uses a compact human review form and displays interviewer names', async () => {
    const endedInterview = {
      ...interviewPayload,
      lifecycle_state: 'ended',
      ai_analysis_status: 'completed',
      ai_analysis: { dimensions: {} },
      panel_members: ['interviewer-1', 'interviewer-2'],
      panels: [
        {
          interviewer_id: 'interviewer-1',
          interviewer_name: '面试官王老师',
          human_comments: '',
          human_recommendation: 'next_round',
        },
        {
          interviewer_id: 'interviewer-2',
          interviewer_name: '面试官李老师',
          human_comments: '技术基础扎实，沟通清晰。',
          human_recommendation: 'passed',
          human_review_submitted_at: '2026-07-30T09:00:00Z',
        },
      ],
    }
    vi.mocked(request.get).mockImplementation((path: string) => (
      path.endsWith('/notes')
        ? Promise.resolve([{ interviewer_id: 'interviewer-1', interviewer_name: '面试官王老师', notes: '现场笔记' }])
        : Promise.resolve(endedInterview)
    ))

    renderResult()

    expect(await screen.findByText('人工评价')).toBeInTheDocument()
    expect(screen.queryByText('我的人工评价')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入评价说明')).toBeInTheDocument()
    expect(screen.getAllByText('面试官王老师')).toHaveLength(2)
    expect(screen.getByText('评价结论：通过')).toBeInTheDocument()
    expect(screen.getByText('评价说明：技术基础扎实，沟通清晰。')).toBeInTheDocument()
  })

  it('shows the detailed evidence-based AI interview evaluation for version 2 analyses', async () => {
    vi.mocked(request.get).mockResolvedValue({
      ...interviewPayload,
      lifecycle_state: 'ended',
      ai_analysis_status: 'completed',
      ai_analysis_version: 2,
      ai_analysis: {
        format_version: 2,
        dimensions: {},
        weighted_score: 7.2,
        coverage: 90,
        recommendation: 'next_round',
        summary: '候选人能够说明嵌入式项目的基础实现，但关键工程细节仍需继续验证。',
        strengths: [{
          conclusion: '具备 Bootloader 分包思路',
          evidence: { start: 1960, end: 1963, quote: '需要进行一个分包操作' },
          job_impact: '能够支撑固件升级功能的基础开发',
        }],
        risks: [{
          conclusion: '未说明校验与恢复边界',
          evidence: { start: 1999, end: 2003, quote: '失败的话，我会选择重传' },
          job_impact: '可能影响升级链路的可靠性',
        }],
        recommendation_reason: '建议进入下一轮，重点验证工程实现深度。',
        next_round_questions: ['Bootloader 如何完成分包校验与断点恢复？'],
      },
    })

    renderResult()

    expect(await screen.findByText('AI 面试评价')).toBeInTheDocument()
    expect(screen.getByText('综合表现')).toBeInTheDocument()
    expect(screen.getByText('主要优势')).toBeInTheDocument()
    expect(screen.getByText('风险与不足')).toBeInTheDocument()
    expect(screen.getByText('具备 Bootloader 分包思路')).toBeInTheDocument()
    expect(screen.getByText('“需要进行一个分包操作”')).toBeInTheDocument()
    expect(screen.getByText('Bootloader 如何完成分包校验与断点恢复？')).toBeInTheDocument()
  })

  it('marks interviews without recording evidence as not analyzed', async () => {
    vi.mocked(request.get).mockResolvedValue({
      ...interviewPayload,
      lifecycle_state: 'ended',
      ai_analysis_status: 'not_applicable',
    })

    renderResult()

    expect(await screen.findByText('无录音证据，未执行 AI 分析')).toBeInTheDocument()
  })
})

describe('mergeAdjacentTranscriptSegments', () => {
  it('merges nearby adjacent segments from the same speaker', () => {
    expect(mergeAdjacentTranscriptSegments([
      { start: 0, end: 1, speaker: 'speaker_0', text: '我负责' },
      { start: 1.4, end: 3, speaker: 'speaker_0', text: '后端开发。' },
      { start: 3.1, end: 4, speaker: 'speaker_1', text: '请继续。' },
    ])).toEqual([
      { start: 0, end: 3, speaker: 'speaker_0', text: '我负责后端开发。' },
      { start: 3.1, end: 4, speaker: 'speaker_1', text: '请继续。' },
    ])
  })

  it('does not merge across a long pause or when the speaker is unknown', () => {
    expect(mergeAdjacentTranscriptSegments([
      { start: 0, end: 1, speaker: 'speaker_0', text: 'First' },
      { start: 3, end: 4, speaker: 'speaker_0', text: 'Second' },
      { start: 4, end: 5, text: 'Unknown one' },
      { start: 5, end: 6, text: 'Unknown two' },
    ])).toHaveLength(4)
  })
})
