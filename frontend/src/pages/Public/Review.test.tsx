import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PublicReview from './Review'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const reviewPayload = {
  completed: false,
  resume: {
    id: 'resume-1',
    candidate_name: '测试候选人',
    email: 'candidate@example.com',
    contact: '13800000000',
    match_score: 88,
    ai_review: '',
    resume_markdown: '',
    parsed_data: {},
    position: {
      id: 'position-1',
      title: '测试工程师',
      description: '',
      requirements: '',
    },
    status: 'pending_dept_review',
    department_reviews: [],
  },
  existing_review: {
    id: 'review-1',
    technical_score: 0,
    experience_score: 0,
    overall_score: 0,
    recommendation: null,
    comment: null,
    is_completed: false,
  },
}

const renderReview = () => render(
  <MemoryRouter initialEntries={['/public/review/public-token']}>
    <Routes>
      <Route path="/public/review/:token" element={<PublicReview />} />
      <Route path="/resumes" element={<div>简历管理模块</div>} />
    </Routes>
  </MemoryRouter>,
)

describe('PublicReview', () => {
  beforeEach(() => {
    vi.mocked(request.get).mockReset().mockResolvedValue(reviewPayload)
    vi.mocked(request.post).mockReset().mockResolvedValue({
      message: 'Review submitted',
      review_id: 'review-1',
    })
  })

  afterEach(() => cleanup())

  it('shows completion without refetching the public token', async () => {
    renderReview()

    await screen.findByText('测试候选人')
    fireEvent.click(screen.getByRole('button', { name: 'check-circle推荐' }))
    fireEvent.click(screen.getByRole('button', { name: '提交审核' }))

    await screen.findByText('审核已完成')
    expect(request.post).toHaveBeenCalledWith('/public/review/public-token/submit', {
      technical_score: 0,
      experience_score: 0,
      overall_score: 0,
      recommendation: 'recommend',
      comment: '',
    })
    await waitFor(() => expect(request.get).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: '返回简历管理' }))
    expect(await screen.findByText('简历管理模块')).toBeInTheDocument()
  })

  it('uses semantic border colors for every recommendation option', async () => {
    renderReview()

    await screen.findByText('测试候选人')
    expect(screen.getByRole('button', { name: 'check-circle推荐' })).toHaveStyle({
      borderColor: '#52c41a',
    })
    expect(screen.getByRole('button', { name: 'close-circle不推荐' })).toHaveStyle({
      borderColor: '#ff4d4f',
    })
    expect(screen.getByRole('button', { name: 'clock-circle待定' })).toHaveStyle({
      borderColor: '#faad14',
    })
  })

  it('renders the same completed receipt when an unexpired link is reopened', async () => {
    vi.mocked(request.get).mockResolvedValueOnce({ completed: true })
    renderReview()

    await screen.findByText('审核已完成')
    fireEvent.click(screen.getByRole('button', { name: '返回简历管理' }))
    expect(await screen.findByText('简历管理模块')).toBeInTheDocument()
    expect(request.get).toHaveBeenCalledWith('/public/review/public-token')
  })

  it('shows an explicit expired-link result for HTTP 410', async () => {
    vi.mocked(request.get).mockRejectedValueOnce({ response: { status: 410 } })
    renderReview()

    expect(await screen.findByText('评审链接已过期')).toBeInTheDocument()
    expect(screen.queryByText('简历审核')).not.toBeInTheDocument()
  })
})
