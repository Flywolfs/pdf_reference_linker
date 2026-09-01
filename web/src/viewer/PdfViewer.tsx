import { useCallback, useEffect, useRef, useState } from 'react'
import type { Analysis, Note } from '../api'
import { api } from '../api'
import { getDocument, toCssPoint, type PDFDocumentProxy, type PDFPageProxy } from '../pdfjs'
import PageView from './PageView'

interface Props {
  docId: string
  analysis: Analysis
  missMode: boolean
  onMissBoxed: (pageNo: number, bboxPdf: number[]) => void
  jumpHotspotReq: { id: string } | null   // 右栏点击 → 跳转并高亮对应角标
}

export default function PdfViewer({ docId, analysis, missMode, onMissBoxed, jumpHotspotReq }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [pdf, setPdf] = useState<any>(null)
  const [pages, setPages] = useState<PDFPageProxy[]>([])
  const [scale, setScale] = useState(1.3)
  const [highlightNoteId, setHighlightNoteId] = useState<string | null>(null)
  const [highlightHotspotId, setHighlightHotspotId] = useState<string | null>(null)
  const fitDone = useRef(false)

  // 加载 PDF 文档与全部 page 对象（用于尺寸计算与坐标换算）
  useEffect(() => {
    let doc: any = null
    setHighlightNoteId(null)
    // cMap/standardFont 必备：Type0/CID 字体（如 AIA ETen-B5-H 中文）渲染需要
    getDocument({
      url: api.pdfUrl(docId),
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
    }).promise.then(async (d: PDFDocumentProxy) => {
      doc = d
      setPdf(d)
      const tasks: Promise<PDFPageProxy>[] = []
      for (let i = 1; i <= d.numPages; i++) tasks.push(d.getPage(i))
      setPages(await Promise.all(tasks))
    })
    return () => {
      doc?.destroy()
      setPdf(null)
      setPages([])
    }
  }, [docId])

  // 首页 fit-width（一次）
  useEffect(() => {
    if (!pages.length || fitDone.current) return
    const el = scrollRef.current
    if (!el) return
    const w = pages[0].getViewport({ scale: 1 }).width
    const target = Math.min(2, Math.max(0.6, (el.clientWidth - 48) / w))
    setScale(target)
    fitDone.current = true
  }, [pages])

  const registerRendered = useCallback(() => {}, [])

  /** 跳转到注释条目并高亮 2s（§8.2 / FR-5） */
  const jumpToNote = useCallback(
    (note: Note) => {
      const container = scrollRef.current
      const pageEl = container?.querySelector(`[data-page="${note.page}"]`) as HTMLElement | null
      const pdfPage = pages[note.page]
      if (!container || !pageEl || !pdfPage) return
      const [, vy] = toCssPoint(pdfPage, scale, 0, note.bbox[1])
      container.scrollTo({ top: pageEl.offsetTop + vy - 90, behavior: 'smooth' })
      // 高亮保持至下一次跳转/切换文档，不自动消失（用户反馈 2s 脉冲看不清）
      setHighlightNoteId(note.noteId)
    },
    [pages, scale],
  )

  /** 右栏点击：精确滚动到对应角标并持续高亮（同注释端交互，直至下一次点击） */
  const jumpToHotspot = useCallback(
    (hotspotId: string) => {
      const hs = analysis.hotspots.find((x) => x.id === hotspotId)
      const container = scrollRef.current
      if (!hs || !container) return
      const pageEl = container.querySelector(`[data-page="${hs.page}"]`) as HTMLElement | null
      const pdfPage = pages[hs.page]
      if (!pageEl || !pdfPage) return
      const [, vy] = toCssPoint(pdfPage, scale, 0, hs.bbox[1])
      container.scrollTo({ top: pageEl.offsetTop + vy - 120, behavior: 'smooth' })
      setHighlightHotspotId(hotspotId)
    },
    [analysis, pages, scale],
  )

  useEffect(() => {
    if (jumpHotspotReq) jumpToHotspot(jumpHotspotReq.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpHotspotReq])

  return (
    <main className="viewer-pane">
      <div className="toolbar">
        <button onClick={() => setScale((s) => Math.max(0.5, s - 0.15))}>－</button>
        <span className="zoom">{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale((s) => Math.min(3, s + 0.15))}>＋</button>
        <span className="meta">
          {analysis.meta.title} · {analysis.meta.pages} 頁 · 角標 {analysis.hotspots.length} · 註釋 {analysis.notes.length}
          {analysis.stats.resolved != null && ` · 已鏈接 ${analysis.stats.resolved}`}
        </span>
      </div>
      <div className="scroll" ref={scrollRef}>
        {!pdf && <div className="loading">載入中…</div>}
        {pages.map((p, i) => (
          <PageView
            key={i}
            page={p}
            pageNo={i}
            scale={scale}
            analysis={analysis}
            highlightNoteId={highlightNoteId}
            highlightHotspotId={highlightHotspotId}
            onJumpNote={jumpToNote}
            registerRendered={registerRendered}
            missMode={missMode}
            onMissBoxed={onMissBoxed}
          />
        ))}
      </div>
    </main>
  )
}
