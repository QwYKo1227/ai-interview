# Public Review PDF.js Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blank browser-native PDF iframe on the public department review page with a reliable, same-origin PDF.js Canvas preview.

**Architecture:** Add a focused `PdfCanvasPreview` component that accepts the existing protected Blob URL, loads it with `pdfjs-dist`, and renders the selected page to a Canvas. Keep token authorization, file loading, download behavior, non-PDF fallback, and responsive page layout unchanged.

**Tech Stack:** React 19, TypeScript, Ant Design, pdfjs-dist 5.4.624, Vitest, Testing Library, Vite, Docker Compose

## Global Constraints

- PDF bytes must remain on the same-origin path `review token -> file endpoint -> Blob -> PDF.js -> Canvas`.
- The worker must ship with the Vite bundle; no public CDN or third-party document viewer.
- Preserve the existing download button, non-PDF fallback, missing-file state, desktop two-column layout, and mobile stacked layout.
- Do not change PDF preview behavior on resume detail or interview score pages.
- Add only previous-page, next-page, and `current / total` controls; do not add search, annotation, printing, or thumbnails.

---

### Task 1: Add the reusable PDF Canvas renderer

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/components/PdfCanvasPreview.tsx`
- Create: `frontend/src/components/PdfCanvasPreview.test.tsx`

**Interfaces:**
- Consumes: `url: string`, an existing same-origin Blob URL containing a PDF.
- Produces: default React component `PdfCanvasPreview({ url }: { url: string }): JSX.Element`.
- Visible states: `PDF 加载中...`, a Canvas with accessible label `PDF 第 N 页`, page counter `N / M`, and `简历预览加载失败，请下载原件查看`.

- [ ] **Step 1: Add the pinned compatible PDF.js dependency**

Run:

```powershell
cd frontend
npm install pdfjs-dist@5.4.624 --save-exact
```

Expected: `package.json` and `package-lock.json` add exactly `pdfjs-dist: "5.4.624"`. This release supports the Node 20 image used by `frontend/Dockerfile`.

- [ ] **Step 2: Write the failing component tests**

Create `frontend/src/components/PdfCanvasPreview.test.tsx`:

```tsx
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

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: pdfMocks.getDocument,
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({
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
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```powershell
cd frontend
npm test -- src/components/PdfCanvasPreview.test.tsx
```

Expected: FAIL because `PdfCanvasPreview.tsx` does not exist.

- [ ] **Step 4: Implement the minimal Canvas renderer**

Create `frontend/src/components/PdfCanvasPreview.tsx`:

```tsx
import React, { useEffect, useRef, useState } from 'react'
import { Button, Space, Spin, Typography } from 'antd'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import {
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentProxy,
  type RenderTask,
} from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const { Text } = Typography

interface PdfCanvasPreviewProps {
  url: string
}

const PdfCanvasPreview: React.FC<PdfCanvasPreviewProps> = ({ url }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const renderTaskRef = useRef<RenderTask | null>(null)
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const [containerWidth, setContainerWidth] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const updateWidth = () => setContainerWidth(element.clientWidth)
    updateWidth()
    const observer = new ResizeObserver(updateWidth)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let active = true
    let loadedDocument: PDFDocumentProxy | null = null
    const loadingTask = getDocument(url)
    setLoading(true)
    setError(false)
    setPageNumber(1)
    setDocument(null)

    loadingTask.promise
      .then(pdf => {
        loadedDocument = pdf
        if (active) setDocument(pdf)
      })
      .catch(() => {
        if (active) setError(true)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
      renderTaskRef.current?.cancel()
      loadingTask.destroy()
      loadedDocument?.destroy()
    }
  }, [url])

  useEffect(() => {
    if (!document || !canvasRef.current || containerWidth <= 0) return
    let active = true
    const canvas = canvasRef.current

    document.getPage(pageNumber)
      .then(page => {
        if (!active) return
        const baseViewport = page.getViewport({ scale: 1 })
        const displayScale = Math.max((containerWidth - 32) / baseViewport.width, 0.1)
        const outputScale = window.devicePixelRatio || 1
        const viewport = page.getViewport({ scale: displayScale * outputScale })
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Canvas is unavailable')

        canvas.width = Math.floor(viewport.width)
        canvas.height = Math.floor(viewport.height)
        canvas.style.width = `${Math.floor(viewport.width / outputScale)}px`
        canvas.style.height = `${Math.floor(viewport.height / outputScale)}px`
        renderTaskRef.current?.cancel()
        const task = page.render({ canvas, canvasContext: context, viewport })
        renderTaskRef.current = task
        return task.promise
      })
      .catch(reason => {
        if (active && reason?.name !== 'RenderingCancelledException') setError(true)
      })

    return () => {
      active = false
      renderTaskRef.current?.cancel()
    }
  }, [containerWidth, document, pageNumber])

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', overflow: 'auto', background: '#e2e8f0' }}
    >
      {error ? (
        <div style={{ minHeight: 240, display: 'grid', placeItems: 'center', padding: 24 }}>
          <Text type="secondary">简历预览加载失败，请下载原件查看</Text>
        </div>
      ) : loading || !document ? (
        <div style={{ minHeight: 240, display: 'grid', placeItems: 'center' }}>
          <Space direction="vertical" align="center">
            <Spin />
            <Text type="secondary">PDF 加载中...</Text>
          </Space>
        </div>
      ) : (
        <>
          <div
            style={{
              position: 'sticky',
              top: 0,
              zIndex: 1,
              display: 'flex',
              justifyContent: 'center',
              padding: 8,
              background: 'rgba(255, 255, 255, 0.96)',
              borderBottom: '1px solid #cbd5e1',
            }}
          >
            <Space>
              <Button
                aria-label="上一页"
                icon={<LeftOutlined />}
                disabled={pageNumber <= 1}
                onClick={() => setPageNumber(page => page - 1)}
              />
              <Text>{pageNumber} / {document.numPages}</Text>
              <Button
                aria-label="下一页"
                icon={<RightOutlined />}
                disabled={pageNumber >= document.numPages}
                onClick={() => setPageNumber(page => page + 1)}
              />
            </Space>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}>
            <canvas
              ref={canvasRef}
              aria-label={`PDF 第 ${pageNumber} 页`}
              style={{ display: 'block', background: '#fff', boxShadow: '0 4px 18px rgba(15, 23, 42, 0.16)' }}
            />
          </div>
        </>
      )}
    </div>
  )
}

export default PdfCanvasPreview
```

- [ ] **Step 5: Run the component tests and verify GREEN**

Run:

```powershell
cd frontend
npm test -- src/components/PdfCanvasPreview.test.tsx
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit the component**

```powershell
git add -- frontend/package.json frontend/package-lock.json frontend/src/components/PdfCanvasPreview.tsx frontend/src/components/PdfCanvasPreview.test.tsx
git commit -m "feat: render protected PDFs with PDF.js"
```

---

### Task 2: Replace the public review iframe

**Files:**
- Modify: `frontend/src/pages/Public/Review.tsx`
- Modify: `frontend/src/pages/Public/Review.test.tsx`

**Interfaces:**
- Consumes: `PdfCanvasPreview({ url: string })` from Task 1.
- Produces: the public review page renders PDF Blob URLs through Canvas and never creates a native PDF `iframe`.

- [ ] **Step 1: Update the review-page test to require Canvas preview integration**

Add this module mock before the tests in `frontend/src/pages/Public/Review.test.tsx`:

```tsx
vi.mock('../../components/PdfCanvasPreview', () => ({
  default: ({ url }: { url: string }) => (
    <div data-testid="pdf-canvas-preview" data-url={url}>PDF Canvas Preview</div>
  ),
}))
```

Replace the iframe assertion in `renders a PDF preview and download action in the left pane` with:

```tsx
expect(screen.getByTestId('pdf-canvas-preview')).toHaveAttribute(
  'data-url',
  'blob:resume-preview',
)
expect(container.querySelector('iframe')).not.toBeInTheDocument()
```

Replace the non-PDF assertion `screen.queryByTitle('Resume Preview')` with:

```tsx
expect(screen.queryByTestId('pdf-canvas-preview')).not.toBeInTheDocument()
```

- [ ] **Step 2: Run the page test and verify RED**

Run:

```powershell
cd frontend
npm test -- src/pages/Public/Review.test.tsx
```

Expected: FAIL because the page still renders `iframe` and does not render `PdfCanvasPreview`.

- [ ] **Step 3: Replace the iframe with the PDF.js component**

In `frontend/src/pages/Public/Review.tsx`:

```tsx
import PdfCanvasPreview from '../../components/PdfCanvasPreview'
```

Remove:

```tsx
import { getMaximizedPdfPreviewUrl } from '../../utils/pdfPreview'
```

Remove:

```tsx
const pdfPreviewUrl = isPdf ? getMaximizedPdfPreviewUrl(resumeFile.url) : ''
```

Replace the PDF `iframe` block with:

```tsx
<PdfCanvasPreview url={resumeFile.url} />
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
cd frontend
npm test -- src/components/PdfCanvasPreview.test.tsx src/pages/Public/Review.test.tsx
```

Expected: both test files PASS.

- [ ] **Step 5: Commit the page integration**

```powershell
git add -- frontend/src/pages/Public/Review.tsx frontend/src/pages/Public/Review.test.tsx
git commit -m "fix: use PDF.js on public review page"
```

---

### Task 3: Verify and deploy the fix locally

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: the completed frontend build from Tasks 1 and 2.
- Produces: the running `ai_interview_frontend` container serving the PDF.js Canvas preview at the reported public review URL.

- [ ] **Step 1: Run all frontend tests**

Run:

```powershell
cd frontend
npm test -- --testTimeout=10000
```

Expected: all test files PASS with zero failures.

- [ ] **Step 2: Run the production build**

Run:

```powershell
cd frontend
npm run build
```

Expected: TypeScript and Vite complete with exit code 0. A bundle-size warning is acceptable; compilation errors are not.

- [ ] **Step 3: Rebuild only the frontend service**

Run from the repository root:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps --build frontend
```

Expected: `ai_interview_frontend` is recreated and reaches `running`. Do not recreate Postgres or delete any volume.

- [ ] **Step 4: Verify the deployed asset and real page**

Open:

```text
https://interview-local.careray.com/public/review/CZdi_HkGrX6beGHOdwiZqtokbkAA--tcnr3wPTEmdMU
```

Verify in the rendered DOM:

```text
.public-review-preview exists
canvas[aria-label="PDF 第 1 页"] exists
canvas width > 0
canvas height > 0
iframe count == 0
.public-review-layout computed flex-direction == "row" at 1440px
```

Verify the page visually displays PDF content in the left pane and the review form in the right pane. Confirm the “下载原件” link remains present.
