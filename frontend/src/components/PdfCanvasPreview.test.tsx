import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PdfCanvasPreview from './PdfCanvasPreview'

const pdfMocks = vi.hoisted(() => {
  const renderPage = vi.fn(() => ({
    promise: Promise.resolve(),
    cancel: vi.fn(),
  }))
  const getPage = vi.fn(async (pageNumber: number) => ({
    getViewport: ({ scale }: { scale: number }) => ({
      width: 400 * scale,
      height: 600 * scale,
    }),
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

  it('shows a download fallback message when PDF loading fails', async () => {
    pdfMocks.getDocument.mockReturnValueOnce({
      promise: Promise.reject(new Error('invalid pdf')),
      destroy: pdfMocks.loadingTaskDestroy,
    })

    render(<PdfCanvasPreview url="blob:broken" />)

    expect(await screen.findByText(
      '简历预览加载失败，请下载原件查看',
    )).toBeInTheDocument()
  })
})
