import { useEffect, useRef, useState } from 'react'
import type { Analysis, Hotspot, Note } from '../api'
import { renderPage, toCssRect, type PDFPageProxy } from '../pdfjs'

const HOVER_DELAY_MS = 120          // §8.2 hover 防抖
const TOOLTIP_W = 440
const TOOLTIP_EST_H = 240

interface Props {
  page: PDFPageProxy
  pageNo: number                    // 0-based
  scale: number
  analysis: Analysis
  highlightNoteId: string | null
  onJumpNote: (note: Note) => void
  registerRendered: (pageNo: number, height: number) => void
}

interface HoverState {
  hotspot: Hotspot
  rect: [number, number, number, number]
}

export default function PageView({ page, pageNo, scale, analysis, highlightNoteId, onJumpNote, registerRendered }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const hoverTimer = useRef<number | null>(null)
  const [hover, setHover] = useState<HoverState | null>(null)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  const hotspots = analysis.hotspots.filter((h) => h.page === pageNo)
  const notes = analysis.notes.filter((n) => n.page === pageNo && n.anchor !== 'inline')

  // 可见时渲染 canvas（IntersectionObserver 懒加载）
  useEffect(() => {
    const el = hostRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setDims((d) => (d ? d : { w: 0, h: 0 })) // 触发渲染 effect
          io.disconnect()
        }
      },
      { rootMargin: '600px 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // canvas 渲染（dims/scale 变化时重渲）
  useEffect(() => {
    if (!dims) return
    let cancelled = false
    const canvas = canvasRef.current
    if (!canvas) return
    renderPage(page, canvas, scale)
      .then(({ cssW, cssH }) => {
        if (!cancelled) {
          setDims({ w: cssW, h: cssH })
          registerRendered(pageNo, cssH)
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dims !== null, scale, page])

  const enter = (hs: Hotspot) => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current)
    const rect = toCssRect(page, scale, hs.bbox)
    hoverTimer.current = window.setTimeout(() => setHover({ hotspot: hs, rect }), HOVER_DELAY_MS)
  }
  const leave = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current)
    hoverTimer.current = window.setTimeout(() => setHover(null), 60)
  }

  const hoveredNote: Note | null = hover
    ? analysis.notes.find((n) => n.noteId === hover.hotspot.targets[0]) ?? null
    : null

  // tooltip 定位（§8.2：下方优先，空间不足上翻，水平 clamp）
  let tipStyle: React.CSSProperties | null = null
  if (hover && dims) {
    const [rx0, ry0, rx1, ry1] = hover.rect
    const w = Math.min(TOOLTIP_W, Math.max(280, dims.w - 16))
    const estH = Math.min(TOOLTIP_EST_H, dims.h * 0.5)
    let top = ry1 + 8
    if (top + estH > dims.h - 8) top = Math.max(8, ry0 - 8 - estH)
    const left = Math.min(Math.max(rx0 - 24, 8), Math.max(8, dims.w - w - 8))
    tipStyle = { top, left, width: w }
  }

  const hsClass = (hs: Hotspot) =>
    'hotspot ' + (hs.confidence >= 0.95 ? 'hs-certain' : hs.confidence >= 0.7 ? 'hs-probable' : 'hs-unresolved')

  return (
    <div className="page-host" data-page={pageNo} ref={hostRef}>
      <div className="page-canvas" style={dims ? { width: dims.w, height: dims.h } : undefined}>
        <canvas ref={canvasRef} />
        {dims && (
          <div className="ref-layer">
            {/* 注释条目框（跳转高亮脉冲） */}
            {notes.map((n) => {
              const r = toCssRect(page, scale, n.bbox)
              return (
                <div
                  key={n.noteId}
                  className={'note-box' + (highlightNoteId === n.noteId ? ' note-pulse' : '')}
                  style={{ left: r[0], top: r[1], width: r[2] - r[0], height: r[3] - r[1] }}
                />
              )
            })}
            {/* 角标命中区（§5.5 外扩命中） */}
            {hotspots.map((hs) => {
              const [x0, y0, x1, y1] = toCssRect(page, scale, hs.bbox)
              const pad = Math.max(3, (y1 - y0) * 0.18)
              const minHit = 7
              const w = Math.max(x1 - x0 + pad * 2, minHit)
              const h = Math.max(y1 - y0 + pad * 2, minHit)
              return (
                <div
                  key={hs.id}
                  className={hsClass(hs)}
                  style={{ left: x0 - (w - (x1 - x0)) / 2, top: y0 - (h - (y1 - y0)) / 2, width: w, height: h }}
                  onMouseEnter={() => enter(hs)}
                  onMouseLeave={leave}
                  onClick={() => {
                    const note = analysis.notes.find((n) => n.noteId === hs.targets[0])
                    if (note) onJumpNote(note)
                  }}
                />
              )
            })}
            {/* hover 浮层 */}
            {hover && tipStyle && (
              <div className="tooltip" style={tipStyle} onMouseEnter={() => { if (hoverTimer.current) window.clearTimeout(hoverTimer.current) }} onMouseLeave={leave}>
                <div className="tip-head">
                  <span className="tip-loc">{hover.hotspot.targetDisplay ?? '未找到對應註釋'}</span>
                  {hover.hotspot.source === 'native' && <span className="badge badge-native">原生鏈接</span>}
                  {hover.hotspot.confidence >= 0.95 && <span className="badge badge-certain">✓</span>}
                  {hover.hotspot.confidence >= 0.7 && hover.hotspot.confidence < 0.95 && <span className="badge badge-probable">可能</span>}
                  {hover.hotspot.confidence < 0.7 && <span className="badge badge-unresolved">?</span>}
                </div>
                <div className="tip-body">
                  {hoveredNote ? hoveredNote.text : '未能在文檔中找到此編號的註釋條目，可在右側引用總覽中人工校對。'}
                </div>
                {hoveredNote && (
                  <div className="tip-foot">
                    <button onClick={() => onJumpNote(hoveredNote)}>跳轉原文</button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="page-label">P{pageNo + 1}</div>
    </div>
  )
}
