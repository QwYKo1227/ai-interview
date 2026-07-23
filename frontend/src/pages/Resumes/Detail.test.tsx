import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ResumeDetail from './Detail'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'admin-1', role: 'admin' } }),
}))

const resume = {
  id: 'resume-1',
  candidate_name: '冬云龙',
  email: 'candidate@example.com',
  contact: '13800000000',
  status: 'pending_review',
  parse_status: 'success',
  match_score: 68,
  file_path: 'uploads/resume.pdf',
  parsed_data: {},
  position: { title: '测试工程师' },
  department_reviews: [],
}

describe('ResumeDetail laptop layout', () => {
  it('keeps two shrinkable panes and wraps actions inside the analysis pane', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') return resume
      if (url === '/auth/interviewers') return []
      return {}
    })

    const { container } = render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('冬云龙')
    const split = container.querySelector('.resume-detail-split')
    expect(split).toBeInTheDocument()
    expect(split).toHaveStyle({ flexDirection: 'row' })
    const panes = container.querySelectorAll('.resume-detail-pane')
    expect(panes).toHaveLength(2)
    panes.forEach((pane) => expect(pane).toHaveStyle({ flex: '1 1 0px' }))
    expect(container.querySelector('.resume-detail-actions')).toHaveStyle({ flexWrap: 'wrap' })
  })
})
