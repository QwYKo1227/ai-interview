import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
  beforeEach(() => { screenState.xxl = false })
  afterEach(cleanup)

  it('collapses the sidebar and synchronizes the content offset on laptop screens', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(container.querySelector('.app-sider')).toHaveClass('ant-layout-sider-collapsed')
    expect(container.querySelector('.app-main-layout')).toHaveStyle({ marginLeft: '80px' })
  })

  it('keeps full menu names available in collapsed mode', () => {
    render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(screen.getByLabelText('岗位管理')).toBeVisible()
  })

  it('uses the expanded sidebar on large screens', () => {
    screenState.xxl = true
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(container.querySelector('.app-sider')).not.toHaveClass('ant-layout-sider-collapsed')
    expect(container.querySelector('.app-main-layout')).toHaveStyle({ marginLeft: '240px' })
  })
})
