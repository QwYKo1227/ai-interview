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
      void loadingTask.destroy()
      void loadedDocument?.destroy()
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
              style={{
                display: 'block',
                background: '#fff',
                boxShadow: '0 4px 18px rgba(15, 23, 42, 0.16)',
              }}
            />
          </div>
        </>
      )}
    </div>
  )
}

export default PdfCanvasPreview
