import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PublicReview from './Review'
import request from '../../utils/request'
import publicReviewCss from '../../index.css?inline'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('../../components/PdfCanvasPreview', () => ({
  default: ({ url }: { url: string }) => (
    <div data-testid="pdf-canvas-preview" data-url={url}>PDF Canvas Preview</div>
  ),
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
    file_available: true,
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
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:resume-preview'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.mocked(request.get).mockReset().mockImplementation(async (url: string) => {
      if (url === '/public/review/public-token') return reviewPayload
      if (url === '/public/review/public-token/resume-file') {
        return new Blob(['pdf'], { type: 'application/pdf' })
      }
      throw new Error(`Unexpected GET ${url}`)
    })
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
    await waitFor(() => {
      const reviewLoads = vi.mocked(request.get).mock.calls.filter(
        ([url]) => url === '/public/review/public-token',
      )
      expect(reviewLoads).toHaveLength(1)
    })
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

  it('requires login with the assigned reviewer account for HTTP 401', async () => {
    vi.mocked(request.get).mockRejectedValueOnce({ response: { status: 401 } })
    renderReview()

    expect(await screen.findByText('请先登录')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '登录指定账号' })).toBeInTheDocument()
    expect(screen.queryByText('简历审核')).not.toBeInTheDocument()
  })

  it('blocks a logged-in account that is not the assigned reviewer', async () => {
    vi.mocked(request.get).mockRejectedValueOnce({ response: { status: 403 } })
    renderReview()

    expect(await screen.findByText('无权访问此评审')).toBeInTheDocument()
    expect(screen.getByText('当前账号不是被指派的部门评审人，请切换到正确账号。')).toBeInTheDocument()
    expect(screen.queryByText('简历审核')).not.toBeInTheDocument()
  })

  it('renders a PDF preview and download action in the left pane', async () => {
    const { container } = renderReview()

    await screen.findByText('测试候选人')
    const layout = container.querySelector('.public-review-layout')
    expect(layout).toBeInTheDocument()
    expect(layout?.firstElementChild).toHaveClass('public-review-preview')
    expect(await screen.findByTestId('pdf-canvas-preview')).toHaveAttribute(
      'data-url', 'blob:resume-preview',
    )
    expect(container.querySelector('iframe')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /下载原件/ })).toHaveAttribute(
      'href', 'blob:resume-preview',
    )
    expect(publicReviewCss).toMatch(/\.public-review-layout\s*{[^}]*display:\s*flex;/s)
    expect(publicReviewCss).toMatch(/@media\s*\(max-width:\s*900px\)[\s\S]*\.public-review-layout\s*{[^}]*flex-direction:\s*column;/)
  })

  it('uses download-only fallback for a non-PDF resume', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/public/review/public-token') return reviewPayload
      return new Blob(['docx'], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      })
    })
    renderReview()

    expect(await screen.findByText('该文件格式暂不支持在线预览，请下载后查看')).toBeInTheDocument()
    expect(screen.queryByTestId('pdf-canvas-preview')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /下载原件/ })).toBeInTheDocument()
  })

  it('shows an unavailable state without requesting file bytes', async () => {
    vi.mocked(request.get).mockResolvedValueOnce({
      ...reviewPayload,
      resume: { ...reviewPayload.resume, file_available: false },
    })
    renderReview()

    expect(await screen.findByText('暂无简历原件')).toBeInTheDocument()
    expect(request.get).not.toHaveBeenCalledWith(
      '/public/review/public-token/resume-file',
      expect.anything(),
    )
  })

  it('keeps the review form usable when the original file fails to load', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/public/review/public-token') return reviewPayload
      throw new Error('file unavailable')
    })
    renderReview()

    expect(await screen.findByText('简历原件加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交审核' })).toBeEnabled()
  })
})
