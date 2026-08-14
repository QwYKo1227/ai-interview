import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import appStyles from '../../index.css?inline'
import AppLayout from './index'

const screenState = vi.hoisted(() => ({ xxl: false }))

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...actual,
    Grid: { ...actual.Grid, useBreakpoint: () => ({ xxl: screenState.xxl }) },
  }
})

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'admin@example.com', full_name: 'HR Admin', role: 'admin' },
    companyName: '凯锐招聘',
    logout: vi.fn(),
  }),
}))

describe('AppLayout responsiveness', () => {
  let stylesheet: HTMLStyleElement

  beforeEach(() => {
    screenState.xxl = false
    stylesheet = document.createElement('style')
    stylesheet.textContent = appStyles
    document.head.append(stylesheet)
  })

  afterEach(() => {
    cleanup()
    stylesheet.remove()
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
