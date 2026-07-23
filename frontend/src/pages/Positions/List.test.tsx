import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PositionsList from './List'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../components/JDGeneratorModal', () => ({ default: () => null }))

describe('PositionsList responsive table', () => {
  let getComputedStyleSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    const nativeGetComputedStyle = window.getComputedStyle.bind(window)
    // Ant Design probes pseudo-elements; JSDOM cannot implement that overload.
    getComputedStyleSpy = vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  })

  afterEach(() => {
    getComputedStyleSpy.mockRestore()
  })

  it('contains horizontal overflow and fixes the action column to the right', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [] : [])
    const { container } = render(<MemoryRouter><PositionsList /></MemoryRouter>)

    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))

    const actionHeader = screen.getByRole('columnheader', { name: '操作' })
    expect(actionHeader).toHaveClass('ant-table-cell-fix-end')
    expect(container.querySelector('.positions-table')).toBeInTheDocument()
    expect(container.querySelector('.ant-table-content')).toHaveStyle({ overflowX: 'auto' })
  })
})
