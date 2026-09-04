import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import appStyles from '../../index.css?inline'
import request from '../../utils/request'
import AppLayout from './index'

const screenState = vi.hoisted(() => ({ xxl: false }))
const authState = vi.hoisted(() => ({ role: 'admin' }))

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...actual,
    Grid: { ...actual.Grid, useBreakpoint: () => ({ xxl: screenState.xxl }) },
  }
})

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'admin@example.com', full_name: 'HR Admin', role: authState.role },
    companyName: '凯锐招聘',
    logout: vi.fn(),
  }),
}))

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn() },
}))

describe('AppLayout responsiveness', () => {
  let stylesheet: HTMLStyleElement

  beforeEach(() => {
    screenState.xxl = false
    authState.role = 'admin'
    stylesheet = document.createElement('style')
    stylesheet.textContent = appStyles
    document.head.append(stylesheet)
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/my-pending-review-count') return { count: 0 }
      if (url === '/resumes/pending-hr-decision-count') return { count: 0 }
      if (url === '/offers/my-pending-count') return { count: 0 }
      return {}
    })
  })

  afterEach(() => {
    cleanup()
    stylesheet.remove()
    vi.clearAllMocks()
  })

  it('collapses the sidebar and synchronizes the content offset on laptop screens', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(container.querySelector('.app-sider')).toHaveClass('ant-layout-sider-collapsed')
    expect(container.querySelector('.app-main-layout')).toHaveStyle({ marginLeft: '80px' })
  })

  it('shows the current company identity without a company switcher', () => {
    render(<MemoryRouter initialEntries={['/dashboard']}><AppLayout /></MemoryRouter>)

    expect(screen.getByText('凯锐招聘')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: '公司' })).not.toBeInTheDocument()
  })

  it('hides offer management from interviewers', () => {
    authState.role = 'interviewer'
    render(<MemoryRouter initialEntries={['/dashboard']}><AppLayout /></MemoryRouter>)

    expect(screen.queryByRole('menuitem', { name: /Offer管理/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '招聘绩效' })).not.toBeInTheDocument()
  })

  it('shows interviewers only the review-specific resume entry', () => {
    authState.role = 'interviewer'
    render(<MemoryRouter initialEntries={['/resumes/my-reviews']}><AppLayout /></MemoryRouter>)

    expect(screen.getByRole('menuitem', { name: '我的评审' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '简历管理' })).not.toBeInTheDocument()
  })

  it('shows administrators both resume entries', () => {
    authState.role = 'admin'
    render(<MemoryRouter initialEntries={['/resumes']}><AppLayout /></MemoryRouter>)

    expect(screen.getByRole('menuitem', { name: '简历管理' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '我的评审' })).toBeInTheDocument()
  })

  it('does not show HR users the personal review entry', () => {
    authState.role = 'hr'
    render(<MemoryRouter initialEntries={['/resumes']}><AppLayout /></MemoryRouter>)

    expect(screen.getByRole('menuitem', { name: '简历管理' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '我的评审' })).not.toBeInTheDocument()
  })

  it('shows pending counts beside expanded menu labels and caps them at 99+', async () => {
    screenState.xxl = true
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/my-pending-review-count') return { count: 4 }
      if (url === '/resumes/pending-hr-decision-count') return { count: 120 }
      return { count: 0 }
    })

    render(<MemoryRouter initialEntries={['/resumes']}><AppLayout /></MemoryRouter>)

    expect(await screen.findByText('4')).toBeInTheDocument()
    expect(screen.getAllByText('99+').length).toBeGreaterThan(0)
  })

  it('keeps the pending review badge visible in collapsed mode', async () => {
    authState.role = 'interviewer'
    vi.mocked(request.get).mockResolvedValue({ count: 7 })

    render(<MemoryRouter initialEntries={['/resumes/my-reviews']}><AppLayout /></MemoryRouter>)

    expect(await screen.findByText('7')).toBeVisible()
  })

  it('hides the complete title beside a direct menu icon in collapsed mode', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    const menuItem = container.querySelector<HTMLElement>('.ant-menu-item-selected')!
    const icon = menuItem.querySelector(':scope > .ant-menu-item-icon')
    const title = within(menuItem).getByText('岗位管理')

    expect(icon).toBeInTheDocument()
    expect(title).toHaveClass('ant-menu-title-content')
    expect(getComputedStyle(title).opacity).toBe('0')
  })

  it('shows one complete collapsed menu tooltip on pointer hover', async () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    const menuItem = container.querySelector<HTMLElement>('.ant-menu-item-selected')!
    const icon = within(menuItem).getByLabelText('user')

    fireEvent.mouseEnter(icon)

    await waitFor(() => expect(screen.getAllByRole('tooltip')).toHaveLength(1))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/^岗位管理$/)
  })

  it('shows one complete collapsed menu tooltip when the menuitem receives focus', async () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    const menuItem = container.querySelector<HTMLElement>('.ant-menu-item-selected')!

    fireEvent.focus(menuItem)

    await waitFor(() => expect(screen.getAllByRole('tooltip')).toHaveLength(1))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/^岗位管理$/)
  })

  it('keeps the complete accessible name on the collapsed menuitem without an inner tab stop', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    const menuItem = screen.getByRole('menuitem', { name: '岗位管理' })
    const focusableDescendants = [...menuItem.querySelectorAll<HTMLElement>('*')]
      .filter((element) => element.tabIndex >= 0)

    expect(container.querySelector('.collapsed-menu-icon')).not.toBeInTheDocument()
    expect(focusableDescendants).toHaveLength(0)
  })

  it('uses compact branding on laptop screens', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)

    expect(container.querySelector('.app-brand')).toHaveTextContent(/^AI$/)
  })

  it('uses compact header padding at laptop widths', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    const header = container.querySelector('.app-header')

    expect(getComputedStyle(header!).paddingLeft).toBe('20px')
    expect(getComputedStyle(header!).paddingRight).toBe('20px')
  })

  it('uses the expanded sidebar on large screens', () => {
    screenState.xxl = true
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(container.querySelector('.app-sider')).not.toHaveClass('ant-layout-sider-collapsed')
    expect(container.querySelector('.app-main-layout')).toHaveStyle({ marginLeft: '240px' })
    expect(container.querySelector('.app-brand')).toHaveTextContent(/^AIRecruiting$/)
  })
})
