import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PositionsList from './List'
import request from '../../utils/request'
import '../../index.css'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../components/JDGeneratorModal', () => ({ default: () => null }))
const authState = vi.hoisted(() => ({
  user: { id: 'admin-1', role: 'admin' as 'admin' | 'hr' },
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => authState,
}))

const position = {
  id: 'position-1',
  title: 'Senior Frontend Engineer',
  description: 'Build responsive hiring workflows.',
  requirements: 'React and TypeScript',
  salary_range: '20k-30k',
  location: 'Shanghai',
  department: 'Engineering',
  status: 'open',
  priority: 3,
  category: 'domestic_rd',
  position_type: 'full_time',
  headcount: 1,
  hiring_manager_id: 'manager-1',
  hiring_manager_name: 'Hiring Manager',
  created_at: '2026-07-23T00:00:00.000Z',
  updated_at: '2026-07-23T00:00:00.000Z',
  stats: {
    total_resumes: 0,
    pending_screening: 0,
    pending_interview: 0,
    interview_completed: 0,
    interview_passed: 0,
    offer_pending: 0,
    offer_accepted: 0,
    rejected: 0,
  },
}

describe('PositionsList responsive table', () => {
  let getComputedStyleSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    authState.user = { id: 'admin-1', role: 'admin' }
    const nativeGetComputedStyle = window.getComputedStyle.bind(window)
    // Ant Design probes pseudo-elements; JSDOM cannot implement that overload.
    getComputedStyleSpy = vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  })

  afterEach(() => {
    getComputedStyleSpy.mockRestore()
    cleanup()
    vi.clearAllMocks()
  })

  it('contains horizontal overflow and fixes the action column to the right', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [position] : [])
    const { container } = render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))

    const actionHeader = screen.getByRole('columnheader', { name: '操作' })
    expect(actionHeader).toHaveClass('ant-table-cell-fix-end')
    const actionCell = container.querySelector('.ant-table-tbody .ant-table-cell-fix-end')
    expect(actionCell).toBeInTheDocument()
    expect(actionCell).toHaveClass('ant-table-cell-fix-end')
    expect(container.querySelector('.positions-table')).toBeInTheDocument()
    expect(container.querySelector('.ant-table-content')).toHaveStyle({ overflowX: 'auto' })
  })

  it('keeps the Ant Design column measurement row collapsed', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [position] : [])
    const { container } = render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))

    const measureCell = container.querySelector('.ant-table-measure-row td')
    expect(measureCell).toBeInTheDocument()
    expect(measureCell).toHaveStyle({
      padding: '0px',
      lineHeight: '0',
    })
  })

  it('reserves enough width for the row selection checkbox', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [position] : [])
    const { container } = render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))

    const selectionColumn = container.querySelector('.positions-table colgroup col:first-child')
    expect(selectionColumn).toHaveStyle({ width: '64px' })
  })

  it('shows every mutually exclusive recruitment progress bucket', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [{
      ...position,
      stats: {
        total_resumes: 19,
        pending_screening: 6,
        pending_interview: 4,
        interview_completed: 1,
        interview_passed: 1,
        offer_pending: 1,
        offer_accepted: 3,
        rejected: 3,
      },
    }] : [])
    const { container } = render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))
    const badge = container.querySelector('.ant-badge-count')
    expect(badge).not.toBeNull()
    await user.hover(badge as HTMLElement)

    for (const progressText of [
      '待筛选: 6',
      '待面试: 4',
      '面试完成: 1',
      '面试通过: 1',
      'Offer待定: 1',
      '已入职: 3',
      '已淘汰: 3',
    ]) {
      expect(await screen.findByText(progressText)).toBeInTheDocument()
    }
  })

  it('shows a readable primary action in the batch toolbar', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [position] : [])
    render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))
    await user.click(screen.getByRole('checkbox', { name: 'Select all' }))

    const toolbar = screen.getByRole('region', { name: '批量操作' })
    expect(within(toolbar).getByText('1')).toHaveClass('positions-batch-count')
    expect(within(toolbar).getByText('个岗位已选')).toBeInTheDocument()
    const publishButton = within(toolbar).getByRole('button', { name: '批量发布' })
    expect(publishButton).toHaveClass('ant-btn-primary')
    expect(publishButton).not.toHaveClass('ant-btn-background-ghost')
  })

  it('opens a dedicated recycle bin instead of showing a deleted toggle', async () => {
    const user = userEvent.setup()
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [] : [])
    render(<MemoryRouter><PositionsList /></MemoryRouter>)

    expect(screen.queryByText('显示已删除')).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /岗位回收站/ }))

    expect(await screen.findByRole('heading', { name: '岗位回收站' })).toBeInTheDocument()
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', {
      params: { deleted_only: true },
    }))
  })

  it('shows deleted as the sole status in the recycle bin', async () => {
    const user = userEvent.setup()
    const deletedPosition = {
      ...position,
      status: 'closed',
      deleted_at: '2026-08-17T03:00:00.000Z',
    }
    vi.mocked(request.get).mockImplementation(async (url: string, config?: { params?: { deleted_only?: boolean } }) => (
      url === '/positions' && config?.params?.deleted_only ? [deletedPosition] : []
    ))
    render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await user.click(await screen.findByRole('button', { name: /岗位回收站/ }))
    const row = (await screen.findByText(deletedPosition.title)).closest('tr')

    expect(row).not.toBeNull()
    expect(within(row as HTMLElement).getByText('已删除')).toBeInTheDocument()
    expect(within(row as HTMLElement).queryByText('已关闭')).not.toBeInTheDocument()
  })

  it('disables classification fields for HR when editing a published position', async () => {
    const user = userEvent.setup()
    const publishedPosition = { ...position, status: 'published' }
    authState.user = { id: 'manager-1', role: 'hr' }
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/positions') return [publishedPosition]
      if (url === `/positions/${publishedPosition.id}`) return publishedPosition
      return []
    })
    render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await user.click(await screen.findByRole('button', { name: 'edit' }))

    expect(await screen.findByLabelText('优先度')).toBeDisabled()
    expect(screen.getByLabelText('岗位分类')).toBeDisabled()
    expect(screen.getByPlaceholderText('例如：高级前端工程师')).toBeEnabled()
  })

  it('keeps classification fields enabled for admin on a published position', async () => {
    const user = userEvent.setup()
    const publishedPosition = { ...position, status: 'published' }
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/positions') return [publishedPosition]
      if (url === `/positions/${publishedPosition.id}`) return publishedPosition
      return []
    })
    render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await user.click(await screen.findByRole('button', { name: 'edit' }))

    expect(await screen.findByLabelText('优先度')).toBeEnabled()
    expect(screen.getByLabelText('岗位分类')).toBeEnabled()
  })
})
