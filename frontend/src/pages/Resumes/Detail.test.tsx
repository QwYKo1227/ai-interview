import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResumeDetail from './Detail'
import request from '../../utils/request'
import resumeDetailCss from '../../index.css?inline'

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
  let stylesheet: HTMLStyleElement | undefined

  afterEach(() => {
    cleanup()
    stylesheet?.remove()
  })

  it('keeps two shrinkable panes and wraps actions inside the analysis pane', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') return resume
      if (url === '/auth/interviewers') return []
      return {}
    })

    stylesheet = document.createElement('style')
    stylesheet.textContent = resumeDetailCss
    document.head.append(stylesheet)

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
    panes.forEach((pane) => expect(getComputedStyle(pane).minWidth).toBe('0px'))
    expect(resumeDetailCss).toMatch(/\.resume-detail-split,\s*\.resume-detail-pane\s*{\s*min-width:\s*0;/)
    expect(resumeDetailCss).toMatch(/\.resume-detail-pane\s*{\s*flex:\s*1\s+1\s+0;/)

    const analysisPane = container.querySelector<HTMLElement>('.resume-analysis-pane')
    const actionRow = container.querySelector<HTMLElement>('.resume-detail-actions')
    expect(actionRow).toBeInTheDocument()
    expect(analysisPane).toContainElement(actionRow)
    expect(actionRow).toHaveStyle({ flexWrap: 'wrap' })
    const actions = within(actionRow!)
    expect(actions.getByRole('button', { name: /重新解析/ })).toBeInTheDocument()
    expect(actions.getByRole('button', { name: /编辑/ })).toBeInTheDocument()
    expect(actions.getByRole('button', { name: /直接决策/ })).toBeInTheDocument()

    const previewHeader = container.querySelector<HTMLElement>('.resume-preview-header')
    expect(previewHeader).toHaveStyle({ minWidth: '0px', flexWrap: 'wrap' })
    expect(resumeDetailCss).toMatch(/\.resume-preview-header\s*{\s*min-width:\s*0;\s*flex-wrap:\s*wrap;/)
  })
})
