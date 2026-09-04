import { useEffect, useMemo, useRef, useState } from 'react'
import type { Analysis, Hotspot, Note } from '../api'
import { renderPage, toCssRect, type PDFPageProxy } from '../pdfjs'

const HOVER_DELAY_MS = 120          // §8.2 hover 防抖
const TOOLTIP_W = 440

interface Props {
  page: PDFPageProxy
  pageNo: number                    // 0-based
  scale: number
  analysis: Analysis
  highlightNoteId: string | null
  highlightHotspotId: string | null   // 右栏点击跳转后的角标持续高亮
  misses: { id: string; page: number; bbox: number[]; number: string | null; targetDisplay: string | null; targetNoteId: string | null }[]  // 待审补标条目（本页过滤后渲染）
  highlightMissId: string | null      // 右栏补标点击跳转后的持续高亮
  onJumpNote: (note: Note) => void
  registerRendered: (pageNo: number, height: number) => void
  missMode: boolean                  // 補標模式：拖框选漏检角标
  onMissBoxed: (pageNo: number, bboxPdf: number[]) => void
}

interface HoverState {
  items: Hotspot[]                  // 同 group 的多编号引用（单编号时长度 1）
  rect: [number, number, number, number]
}

interface MissItem {               // 待审补标条目（右栏 annos 投影）
  id: string
  page: number
  bbox: number[]
  number: string | null
  targetDisplay: string | null
  targetNoteId: string | null
}

export default function PageView({ page, pageNo, scale, analysis, highlightNoteId, highlightHotspotId, misses, highlightMissId, onJumpNote, registerRendered, missMode, onMissBoxed }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const hoverTimer = useRef<number | null>(null)
  const [hover, setHover] = useState<HoverState | null>(null)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  const hotspots = analysis.hotspots.filter((h) => h.page === pageNo)
  const notes = analysis.notes.filter((n) => n.page === pageNo && n.anchor !== 'inline')

  // 同一多编号角标（如 '2,3' 共享 group）聚合为单一命中区，tooltip 列出全部引用
  const hsGroups = useMemo(() => {
    const map = new Map<string, Hotspot[]>()
    for (const h of hotspots) {
      const key = h.group ?? h.id
      const arr = map.get(key)
      if (arr) arr.push(h)
      else map.set(key, [h])
    }
    return [...map.values()]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis, pageNo])

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

  const enter = (items: Hotspot[]) => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current)
    const rect = toCssRect(page, scale, items[0].bbox)
    hoverTimer.current = window.setTimeout(() => setHover({ items, rect }), HOVER_DELAY_MS)
  }
  const leave = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current)
    hoverTimer.current = window.setTimeout(() => setHover(null), 60)
  }

  // 补标框 hover：与引擎热点同款浮层（编号 + 建议目标 + 注释内容 + 跳轉原文）
  const [missHover, setMissHover] = useState<{ miss: MissItem; rect: [number, number, number, number] } | null>(null)
  const missTimer = useRef<number | null>(null)
  const missNote = (m: MissItem) =>
    m.targetNoteId ? analysis.notes.find((n) => n.noteId === m.targetNoteId) ?? null : null
  const missEnter = (m: MissItem) => {
    if (missTimer.current) window.clearTimeout(missTimer.current)
    const rect = toCssRect(page, scale, m.bbox)
    missTimer.current = window.setTimeout(() => setMissHover({ miss: m, rect }), HOVER_DELAY_MS)
  }
  const missLeave = () => {
    if (missTimer.current) window.clearTimeout(missTimer.current)
    missTimer.current = window.setTimeout(() => setMissHover(null), 60)
  }

  // tooltip 定位（§8.2：下方优先，空间不足上翻，水平 clamp）；高度按条目数估算
  const activeRect = hover?.rect ?? missHover?.rect ?? null
  const tipItems = hover ? hover.items.length : missHover ? 1 : 0
  let tipStyle: React.CSSProperties | null = null
  if (activeRect && dims) {
    const [rx0, ry0, rx1, ry1] = activeRect
    const w = Math.min(TOOLTIP_W, Math.max(280, dims.w - 16))
    const estH = Math.min(120 + 110 * tipItems, dims.h * 0.6)
    let top = ry1 + 8
    if (top + estH > dims.h - 8) top = Math.max(8, ry0 - 8 - estH)
    const left = Math.min(Math.max(rx0 - 24, 8), Math.max(8, dims.w - w - 8))
    tipStyle = { top, left, width: w }
  }
  const missHoverNote = missHover ? missNote(missHover.miss) : null

  const hsClassConf = (conf: number) =>
    'hotspot ' + (conf >= 0.95 ? 'hs-certain' : conf >= 0.7 ? 'hs-probable' : 'hs-unresolved')

  // ---- 補標框选（missMode）----
  const [dragRect, setDragRect] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)
  const dragStart = useRef<{ x: number; y: number } | null>(null)

  const missDown = (e: React.MouseEvent) => {
    if (!missMode) return
    const { offsetX, offsetY } = e.nativeEvent
    dragStart.current = { x: offsetX, y: offsetY }
    setDragRect({ x0: offsetX, y0: offsetY, x1: offsetX, y1: offsetY })
  }
  const missMove = (e: React.MouseEvent) => {
    if (!dragStart.current) return
    const { offsetX, offsetY } = e.nativeEvent
    setDragRect((r) => (r ? { ...r, x1: offsetX, y1: offsetY } : r))
  }
  const missUp = () => {
    const st = dragStart.current
    const r = dragRect
    dragStart.current = null
    setDragRect(null)
    if (!st || !r) return
    const x0 = Math.min(r.x0, r.x1)
    const x1 = Math.max(r.x0, r.x1)
    const y0 = Math.min(r.y0, r.y1)
    const y1 = Math.max(r.y0, r.y1)
    if (x1 - x0 < 4 || y1 - y0 < 4) return       // 误触
    // css 坐标 → PDF pt（左上原点，同管线 bbox）
    onMissBoxed(pageNo, [x0 / scale, y0 / scale, x1 / scale, y1 / scale])
  }

  return (
    <div className="page-host" data-page={pageNo} ref={hostRef}>
      <div className="page-canvas" style={dims ? { width: dims.w, height: dims.h } : undefined}>
        <canvas ref={canvasRef} />
        {dims && (
          <div
            className={'ref-layer' + (missMode ? ' miss-mode' : '')}
            onMouseDown={missMode ? missDown : undefined}
            onMouseMove={missMode ? missMove : undefined}
            onMouseUp={missMode ? missUp : undefined}
          >
            {dragRect && (
              <div
                className="miss-drag"
                style={{
                  left: Math.min(dragRect.x0, dragRect.x1),
                  top: Math.min(dragRect.y0, dragRect.y1),
                  width: Math.abs(dragRect.x1 - dragRect.x0),
                  height: Math.abs(dragRect.y1 - dragRect.y0),
                }}
              />
            )}
            {/* 注释条目框（跳转高亮脉冲） */}
            {notes.map((n) => {
              const r = toCssRect(page, scale, n.bbox)
              return (
                <div
                  key={n.noteId}
                  className={'note-box' + (highlightNoteId === n.noteId ? ' active note-pulse' : '')}
                  style={{ left: r[0], top: r[1], width: r[2] - r[0], height: r[3] - r[1] }}
                />
              )
            })}
            {/* 待审补标条目框：紫色虚线（确认后注入为常规热点，此框消失）。
                hover 显示建议目标浮层，点击跳转建议目标（同引擎热点） */}
            {misses.filter((m) => m.page === pageNo).map((m) => {
              const [x0, y0, x1, y1] = toCssRect(page, scale, m.bbox)
              const pad = Math.max(3, (y1 - y0) * 0.18)   // §5.5 外扩命中，角标太小须保证可 hover
              const w = Math.max(x1 - x0 + pad * 2, 10)
              const h = Math.max(y1 - y0 + pad * 2, 10)
              return (
                <div
                  key={m.id}
                  className={'miss-box' + (highlightMissId === m.id ? ' active note-pulse' : '')}
                  style={{ left: x0 - (w - (x1 - x0)) / 2, top: y0 - (h - (y1 - y0)) / 2, width: w, height: h }}
                  onMouseEnter={() => missEnter(m)}
                  onMouseLeave={missLeave}
                  onClick={() => { const n = missNote(m); if (n) onJumpNote(n) }}
                />
              )
            })}
            {/* 角标命中区（§5.5 外扩命中；同 group 多编号聚合为一个命中区） */}
            {hsGroups.map((items) => {
              const [x0, y0, x1, y1] = toCssRect(page, scale, items[0].bbox)
              const pad = Math.max(3, (y1 - y0) * 0.18)
              const minHit = 7
              const w = Math.max(x1 - x0 + pad * 2, minHit)
              const h = Math.max(y1 - y0 + pad * 2, minHit)
              const conf = Math.max(...items.map((s) => s.confidence))
              // 右栏跳转高亮：命中组内任一编号（多编号角标整组高亮）
              const lit = highlightHotspotId != null && items.some((s) => s.id === highlightHotspotId)
              return (
                <div
                  key={items[0].id}
                  className={hsClassConf(conf) + (lit ? ' active' : '')}
                  style={{ left: x0 - (w - (x1 - x0)) / 2, top: y0 - (h - (y1 - y0)) / 2, width: w, height: h }}
                  onMouseEnter={() => enter(items)}
                  onMouseLeave={leave}
                  onClick={() => {
                    const note = items
                      .map((s) => analysis.notes.find((n) => n.noteId === s.targets[0]))
                      .find(Boolean)
                    if (note) onJumpNote(note)
                  }}
                />
              )
            })}
            {/* hover 浮层：单编号单条；多编号列表展示全部引用，逐条独立跳转 */}
            {hover && tipStyle && (
              <div className="tooltip" style={tipStyle} onMouseEnter={() => { if (hoverTimer.current) window.clearTimeout(hoverTimer.current) }} onMouseLeave={leave}>
                {hover.items.length > 1 && (
                  <div className="tip-multi">此處引用 {hover.items.length} 條註釋</div>
                )}
                {hover.items.map((hs) => {
                  const note = analysis.notes.find((n) => n.noteId === hs.targets[0]) ?? null
                  return (
                    <div className="tip-item" key={hs.id}>
                      <div className="tip-head">
                        <span className="tip-num">{hs.text}</span>
                        <span className="tip-loc">{hs.targetDisplay ?? '未找到對應註釋'}</span>
                        {hs.source === 'native' && <span className="badge badge-native">原生鏈接</span>}
                        {hs.confidence >= 0.95 && <span className="badge badge-certain">✓</span>}
                        {hs.confidence >= 0.7 && hs.confidence < 0.95 && <span className="badge badge-probable">可能</span>}
                        {hs.confidence < 0.7 && <span className="badge badge-unresolved">?</span>}
                      </div>
                      <div className="tip-body">
                        {note ? note.text : '未能在文檔中找到此編號的註釋條目，可在右側引用總覽中人工校對。'}
                      </div>
                      {note && (
                        <div className="tip-foot">
                          <button onClick={() => onJumpNote(note)}>跳轉原文</button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
            {/* 补标 hover 浮层：编号 + 建议目标 + 注释内容 + 跳轉原文 */}
            {missHover && tipStyle && (
              <div
                className="tooltip"
                style={tipStyle}
                onMouseEnter={() => { if (missTimer.current) window.clearTimeout(missTimer.current) }}
                onMouseLeave={missLeave}
              >
                <div className="tip-head">
                  <span className="tip-num">{missHover.miss.number ?? '?'}</span>
                  <span className="tip-loc">{missHover.miss.targetDisplay ?? '未找到匹配條目'}</span>
                  <span className="badge badge-pending">補標</span>
                </div>
                <div className="tip-body">
                  {missHoverNote
                    ? missHoverNote.text
                    : '未能在文檔中找到此編號的註釋條目，可導出 AI 任務處理。'}
                </div>
                {missHoverNote && (
                  <div className="tip-foot">
                    <button onClick={() => onJumpNote(missHoverNote)}>跳轉原文</button>
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
