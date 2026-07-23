import { cleanup, render, screen } from '@testing-library/react'
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

  it('keeps full menu names available in collapsed mode', () => {
    render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(screen.getByLabelText('岗位管理')).toBeVisible()
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
  })
})
