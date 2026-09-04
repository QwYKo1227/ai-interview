import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Modal } from 'antd'
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
  position_id: 'position-1',
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
  hr_review: '',
}

describe('ResumeDetail laptop layout', () => {
  let stylesheet: HTMLStyleElement | undefined

  afterEach(async () => {
    await act(async () => {
      Modal.destroyAll()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    cleanup()
    document.querySelectorAll('.ant-modal-root').forEach((element) => element.remove())
    stylesheet?.remove()
    vi.clearAllMocks()
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
    expect(actions.getByRole('button', { name: /指派部门评审人/ })).toBeInTheDocument()
    expect(actions.getByRole('button', { name: /HR直接决策/ })).toBeInTheDocument()

    const previewHeader = container.querySelector<HTMLElement>('.resume-preview-header')
    expect(previewHeader).toHaveStyle({ minWidth: '0px', flexWrap: 'wrap' })
    expect(resumeDetailCss).toMatch(/\.resume-preview-header\s*{\s*min-width:\s*0;\s*flex-wrap:\s*wrap;/)
  })

  it('shows restore review for a waitlisted candidate', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return {
          ...resume,
          status: 'waitlist',
        }
      }
      if (url === '/auth/interviewers') return []
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('冬云龙')
    await user.click(screen.getByRole('button', { name: /恢复评审/ }))
    await user.click(screen.getByRole('button', { name: /确\s*认/ }))
    await waitFor(() => {
      expect(request.put).toHaveBeenCalledWith('/resumes/resume-1', { status: 'pending_review' })
    })
  })

  it('uses the personal review view when an administrator enters with a review id', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1?review_id=review-1') {
        return {
          ...resume,
          status: 'pending_dept_review',
          department_reviews: [{
            id: 'review-1',
            reviewer_id: 'admin-1',
            reviewed_position_title: '测试工程师',
            is_completed: false,
          }],
        }
      }
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1?review_id=review-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('我的部门评审')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /提交评审/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /指派部门评审人/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /HR直接决策/ })).not.toBeInTheDocument()
    expect(request.get).not.toHaveBeenCalledWith('/auth/interviewers')
    expect(request.get).not.toHaveBeenCalledWith('/resumes/resume-1/department-reviews')
  })

  it('saves one trimmed HR review and preloads it in the decision dialog', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return { ...resume, hr_review: '原有评语' }
      }
      if (url === '/auth/interviewers') return []
      return {}
    })
    vi.mocked(request.put).mockResolvedValue({ ...resume, hr_review: '更新后的评语' })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    const reviewInput = await screen.findByRole('textbox', { name: 'HR 评语' })
    expect(reviewInput).toHaveValue('原有评语')
    await user.clear(reviewInput)
    await user.type(reviewInput, '  更新后的评语  ')
    await user.click(screen.getByRole('button', { name: /保存评语/ }))

    await waitFor(() => {
      expect(request.put).toHaveBeenCalledWith('/resumes/resume-1', {
        hr_review: '更新后的评语',
      })
    })

    await user.click(screen.getByRole('button', { name: /HR直接决策/ }))
    const dialog = await screen.findByRole('dialog', { name: 'HR决策' })
    expect(within(dialog).getByRole('textbox', { name: 'HR评语' })).toHaveValue('更新后的评语')
  })

  it('opens the interview scheduling dialog without leaving the detail page', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return { ...resume, status: 'pending_next_interview' }
      }
      if (url === '/auth/interviewers') return []
      if (url === '/interviews') return []
      if (url === '/question-banks') return []
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('冬云龙')
    await user.click(screen.getByRole('button', { name: /安排面试/ }))

    expect(await screen.findByRole('dialog', { name: '安排面试' })).toBeInTheDocument()
    expect(screen.getByText('冬云龙')).toBeInTheDocument()
    expect(request.get).toHaveBeenCalledWith('/interviews')
    expect(request.get).toHaveBeenCalledWith('/question-banks')
  })

  it('supports changing a pending reviewer and showing a rotated review link', async () => {
    const user = userEvent.setup()
    const review = {
      id: 'review-1',
      reviewer_id: 'interviewer-1',
      reviewer_name: '王评审',
      is_completed: false,
    }
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return { ...resume, status: 'pending_dept_review', department_reviews: [review] }
      }
      if (url === '/resumes/resume-1/department-reviews') {
        return {
          resume_id: 'resume-1',
          total_reviewers: 1,
          completed_reviewers: 0,
          recommend_ratio: 0,
          reviews: [review],
        }
      }
      if (url === '/auth/interviewers') {
        return [
          { id: 'interviewer-1', full_name: '王评审' },
          { id: 'interviewer-2', full_name: '李评审' },
        ]
      }
      return {}
    })
    vi.mocked(request.post).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1/department-reviews/review-1/review-link') {
        return { public_token: 'review-token' }
      }
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('王评审')
    await user.click(screen.getByRole('button', { name: /修改评审人/ }))
    expect(await screen.findByRole('dialog', { name: '修改部门评审人' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /取\s*消/ }))

    await user.click(screen.getByRole('button', { name: /评审链接/ }))
    await waitFor(() => {
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/review-link',
      )
    })
    expect(await screen.findByDisplayValue(
      `${window.location.origin}/public/review/review-token`,
    )).toBeInTheDocument()
  }, 15000)

  it('previews and sends email after changing a department reviewer', async () => {
    const user = userEvent.setup()
    const review = {
      id: 'review-1',
      reviewer_id: 'interviewer-1',
      reviewer_name: '王评审',
      is_completed: false,
    }
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return { ...resume, status: 'pending_dept_review', department_reviews: [review] }
      }
      if (url === '/resumes/resume-1/department-reviews') {
        return {
          resume_id: 'resume-1',
          total_reviewers: 1,
          completed_reviewers: 0,
          recommend_ratio: 0,
          reviews: [review],
        }
      }
      if (url === '/auth/interviewers') {
        return [
          { id: 'interviewer-1', full_name: '王评审', email: 'wang@example.com' },
          { id: 'interviewer-2', full_name: '李评审', email: 'li@example.com' },
        ]
      }
      return {}
    })
    vi.mocked(request.put).mockResolvedValue({
      id: 'review-1',
      reviewer_id: 'interviewer-2',
      public_token: 'replacement-token',
    })
    vi.mocked(request.post).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1/department-reviews/review-1/email-preview') {
        return {
          review_id: 'review-1',
          to_email: 'li@example.com',
          reviewer_name: '李评审',
          candidate_name: '冬云龙',
          subject: '简历评审邀请 - 测试工程师',
          content: '<p>请评审冬云龙</p>',
        }
      }
      if (url === '/resumes/resume-1/department-reviews/review-1/send-email') {
        return { message: '邮件发送成功' }
      }
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('王评审')
    await user.click(screen.getByRole('button', { name: /修改评审人/ }))
    const changeDialog = await screen.findByRole('dialog', { name: '修改部门评审人' })
    await user.click(within(changeDialog).getByRole('combobox'))
    await user.click(await screen.findByText('李评审'))
    await user.click(within(changeDialog).getByRole('button', { name: /确\s*认/ }))

    await waitFor(() => {
      expect(request.put).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/reviewer',
        expect.any(FormData),
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/email-preview',
        {
          public_token: 'replacement-token',
          review_url: `${window.location.origin}/public/review/replacement-token`,
        },
      )
    })

    const emailTitle = (await screen.findAllByText('邮件预览'))
      .find(element => element.classList.contains('ant-modal-title'))!
    const emailDialog = emailTitle.closest('.ant-modal') as HTMLElement
    expect(within(emailDialog).getByText('li@example.com')).toBeInTheDocument()
    await user.click(within(emailDialog).getByRole('button', { name: /确\s*认/ }))

    await waitFor(() => {
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/send-email',
        {
          subject: '简历评审邀请 - 测试工程师',
          content: '<p>请评审冬云龙</p>',
        },
      )
    })
  }, 15000)

  it('previews and sends email after assigning a department reviewer', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') return resume
      if (url === '/auth/interviewers') {
        return [{ id: 'interviewer-1', full_name: '王评审', email: 'reviewer@example.com' }]
      }
      if (url === '/resumes/resume-1/department-reviews') {
        return { total_reviewers: 0, completed_reviewers: 0, reviews: [] }
      }
      return {}
    })
    vi.mocked(request.post).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1/department-reviews') {
        return { id: 'review-1', public_token: 'department-review-token' }
      }
      if (url === '/resumes/resume-1/department-reviews/review-1/email-preview') {
        return {
          review_id: 'review-1',
          to_email: 'reviewer@example.com',
          reviewer_name: '王评审',
          candidate_name: '冬云龙',
          subject: '简历评审邀请 - 测试工程师',
          content: '<p>请评审冬云龙</p>',
        }
      }
      if (url === '/resumes/resume-1/department-reviews/review-1/send-email') {
        return { message: '邮件发送成功' }
      }
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('冬云龙')
    await user.click(screen.getAllByRole('button', { name: /指派部门评审人/ })[0])
    const assignDialog = await screen.findByRole('dialog', { name: '指派部门评审人' })
    await user.click(within(assignDialog).getByRole('combobox'))
    await user.click(await screen.findByText('王评审'))
    await user.click(within(assignDialog).getByRole('button', { name: /确认指派/ }))

    await waitFor(() => {
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews',
        expect.any(FormData),
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/email-preview',
        {
          public_token: 'department-review-token',
          review_url: `${window.location.origin}/public/review/department-review-token`,
        },
      )
    })
    const emailTitle = (await screen.findAllByText('邮件预览'))
      .find(element => element.classList.contains('ant-modal-title'))!
    const emailDialog = emailTitle.closest('.ant-modal') as HTMLElement
    expect(emailDialog).toBeInTheDocument()
    expect(within(emailDialog).getByText('reviewer@example.com')).toBeInTheDocument()
    expect(within(emailDialog).getByRole('textbox', { name: '王评审 的邮件主题' }))
      .toHaveValue('简历评审邀请 - 测试工程师')
    await user.click(within(emailDialog).getByRole('button', { name: /确\s*认/ }))

    await waitFor(() => {
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/send-email',
        {
          subject: '简历评审邀请 - 测试工程师',
          content: '<p>请评审冬云龙</p>',
        },
      )
    })
  }, 15000)

  it('previews and sends a reminder for a pending department review', async () => {
    const user = userEvent.setup()
    const review = {
      id: 'review-1',
      reviewer_id: 'interviewer-1',
      reviewer_name: '王评审',
      is_completed: false,
      last_reminded_at: null,
    }
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return { ...resume, status: 'pending_dept_review', department_reviews: [review] }
      }
      if (url === '/resumes/resume-1/department-reviews') {
        return {
          resume_id: 'resume-1', total_reviewers: 1, completed_reviewers: 0,
          recommend_ratio: 0, reviews: [review],
        }
      }
      if (url === '/auth/interviewers') return []
      return {}
    })
    vi.mocked(request.post).mockImplementation(async (url: string) => {
      if (url.endsWith('/review-link')) return { public_token: 'stable-review-token' }
      if (url.endsWith('/reminder-email-preview')) {
        return {
          to_email: 'wang@example.com', reviewer_name: '王评审',
          subject: '评审提醒｜测试工程师｜冬云龙', content: '<p>请完成评审</p>',
        }
      }
      if (url.endsWith('/send-email')) return { message: '邮件发送成功' }
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /邮件提醒/ }))
    expect(request.post).toHaveBeenCalledWith(
      '/resumes/resume-1/department-reviews/review-1/reminder-email-preview',
      {
        public_token: 'stable-review-token',
        review_url: `${window.location.origin}/public/review/stable-review-token`,
      },
    )
    const dialog = await screen.findByRole('dialog', { name: '邮件提醒预览' })
    expect(within(dialog).getByText('wang@example.com')).toBeInTheDocument()
    expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: /确\s*认/ }))

    await waitFor(() => {
      expect(request.post).toHaveBeenCalledWith(
        '/resumes/resume-1/department-reviews/review-1/send-email',
        { subject: '评审提醒｜测试工程师｜冬云龙', content: '<p>请完成评审</p>' },
      )
    })
  }, 15000)

  it('disables reminder during cooldown and shows remaining time on hover', async () => {
    const user = userEvent.setup()
    const review = {
      id: 'review-1', reviewer_id: 'interviewer-1', reviewer_name: '王评审',
      is_completed: false, last_reminded_at: new Date().toISOString(),
    }
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') {
        return { ...resume, status: 'pending_dept_review', department_reviews: [review] }
      }
      if (url === '/resumes/resume-1/department-reviews') {
        return {
          resume_id: 'resume-1', total_reviewers: 1, completed_reviewers: 0,
          recommend_ratio: 0, reviews: [review],
        }
      }
      if (url === '/auth/interviewers') return []
      return {}
    })

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    const button = await screen.findByRole('button', { name: /邮件提醒/ })
    expect(button).toBeDisabled()
    await user.hover(button.parentElement!)
    expect(await screen.findByText(/还需 7 小时.*可再次提醒|还需 8 小时.*可再次提醒/)).toBeInTheDocument()
  }, 15000)
})
