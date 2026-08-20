import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PdfCanvasPreview from './PdfCanvasPreview'

const pdfMocks = vi.hoisted(() => {
  const renderPage = vi.fn(() => ({
    promise: Promise.resolve(),
    cancel: vi.fn(),
  }))
  const getViewport = vi.fn(({ scale }: { scale: number }) => ({
    width: 400 * scale,
    height: 600 * scale,
  }))
  const getPage = vi.fn(async (pageNumber: number) => ({
    getViewport,
    render: renderPage,
    pageNumber,
  }))
  const destroyDocument = vi.fn()
  const loadingTaskDestroy = vi.fn()
  const getDocument = vi.fn(() => ({
    promise: Promise.resolve({
      numPages: 2,
      getPage,
      destroy: destroyDocument,
    }),
    destroy: loadingTaskDestroy,
  }))
  return {
    destroyDocument,
    getDocument,
    getPage,
    getViewport,
    loadingTaskDestroy,
    renderPage,
  }
})

vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: pdfMocks.getDocument,
}))
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({
  default: '/assets/pdf.worker.js',
}))

describe('PdfCanvasPreview', () => {
  beforeEach(() => {
    pdfMocks.getPage.mockClear()
    pdfMocks.getViewport.mockClear()
    pdfMocks.renderPage.mockClear()
    pdfMocks.destroyDocument.mockClear()
    pdfMocks.loadingTaskDestroy.mockClear()
    pdfMocks.getDocument.mockClear()
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      value: 640,
    })
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
      configurable: true,
      value: vi.fn(() => ({})),
    })
    Object.defineProperty(window, 'devicePixelRatio', {
      configurable: true,
      value: 2,
    })
  })

  afterEach(() => cleanup())

  it('renders PDF pages to canvas and supports paging', async () => {
    const { container } = render(<PdfCanvasPreview url="blob:resume" />)

    expect(await screen.findByText('1 / 2')).toBeInTheDocument()
    expect(pdfMocks.getDocument).toHaveBeenCalledWith('blob:resume')
    expect(container.querySelector('iframe')).not.toBeInTheDocument()
    expect(screen.getByLabelText('PDF 第 1 页')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(pdfMocks.getPage).toHaveBeenLastCalledWith(2))
    expect(await screen.findByText('2 / 2')).toBeInTheDocument()
  })

  it('keeps PDF layout at CSS scale and applies high-DPI scaling as an output transform', async () => {
    render(<PdfCanvasPreview url="blob:resume" />)

    await waitFor(() => expect(pdfMocks.renderPage).toHaveBeenCalled())
    expect(pdfMocks.getViewport).toHaveBeenLastCalledWith({ scale: 1.52 })
    expect(pdfMocks.renderPage).toHaveBeenLastCalledWith(expect.objectContaining({
      transform: [2, 0, 0, 2, 0, 0],
      viewport: { width: 608, height: 912 },
    }))
    const canvas = screen.getByLabelText('PDF 第 1 页') as HTMLCanvasElement
    expect(canvas.width).toBe(1216)
    expect(canvas.height).toBe(1824)
    expect(canvas.style.width).toBe('608px')
    expect(canvas.style.height).toBe('912px')
  })

  it('shows a download fallback message when PDF loading fails', async () => {
    pdfMocks.getDocument.mockReturnValueOnce({
      promise: Promise.reject(new Error('invalid pdf')),
      destroy: pdfMocks.loadingTaskDestroy,
    })

    render(<PdfCanvasPreview url="blob:broken" />)

    expect(await screen.findByText(
      '简历预览加载失败，请下载原件查看',
    )).toHaveAttribute('data-error-detail', 'invalid pdf')
  })
})
