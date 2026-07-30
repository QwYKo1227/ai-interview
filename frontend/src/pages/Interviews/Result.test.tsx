import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InterviewResultPage from './Result'
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
})
