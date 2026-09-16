import { useEffect, useMemo, useRef, useState } from 'react'
import type { Analysis, Hotspot, Note } from '../api'
import { renderPage, toCssRect, TextLayer, type PDFPageProxy } from '../pdfjs'

const HOVER_DELAY_MS = 120          // §8.2 hover 防抖
const TOOLTIP_W = 440

interface Props {
  page: PDFPageProxy
  pageNo: number                    // 0-based
  scale: number
  analysis: Analysis
  highlightNoteId: string | null
  highlightHotspotId: string | null   // 右栏点击跳转后的角标持续高亮
  misses: { key: string; page: number; bbox: number[]; members: { id: string; bbox: number[]; number: string | null; targetDisplay: string | null; targetNoteId: string | null }[] }[]  // 待审补标单元（本页过滤后渲染）
  highlightMissId: string | null      // 右栏补标点击跳转后的持续高亮
  onJumpNote: (note: Note) => void
  registerRendered: (pageNo: number, height: number) => void
  missMode: boolean                  // 補標模式：拖框选漏检角标
  onMissBoxed: (pageNo: number, bboxPdf: number[]) => void
  onLocateRef: (id: string) => void  // 点击 PDF 框 → 右栏列表定位到对应条目
}

interface HoverState {
  items: Hotspot[]                  // 同 group 的多编号引用（单编号时长度 1）
  rect: [number, number, number, number]
}

interface MissItem {               // 待审补标成员（右栏 annos 投影）
  id: string
  bbox: number[]
  number: string | null
  targetDisplay: string | null
  targetNoteId: string | null
}

interface MissUnit {               // 渲染单元：同 group 成员聚合为一个框
  key: string
  page: number
  bbox: number[]
  members: MissItem[]
}

export default function PageView({ page, pageNo, scale, analysis, highlightNoteId, highlightHotspotId, misses, highlightMissId, onJumpNote, registerRendered, missMode, onMissBoxed, onLocateRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLDivElement>(null)   // pdf.js 文本层（可选中/复制）
  const hoverTimer = useRef<number | null>(null)
  const [hover, setHover] = useState<HoverState | null>(null)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)
  // 视口尺寸同步可得：canvas 懒渲染前先按真实尺寸预留占位，
  // 否则未渲染页高度塌陷，深层页码/注释跳转的 offsetTop 全错
  const vpSize = useMemo(() => {
    const v = page.getViewport({ scale })
    return { w: v.width, h: v.height }
  }, [page, scale])

  const hotspots = analysis.hotspots.filter((h) => h.page === pageNo)
  const notes = analysis.notes.filter((n) => n.page === pageNo && n.anchor !== 'inline')

  // pdf.js 文本层：与 canvas 同视口重建，使页面文字可选中/复制。
  // 置于 canvas 之上、引用层之下；引用层 pointer-events:none 放行选区
  useEffect(() => {
    const el = textRef.current
    if (!dims || !el) return
    el.replaceChildren()
    const vp = page.getViewport({ scale })
    el.style.setProperty('--scale-factor', String(vp.scale))
    const tl = new TextLayer({ textContentSource: page.streamTextContent(), container: el, viewport: vp })
    tl.render().catch(() => {})
    return () => { el.replaceChildren() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, scale, dims !== null])

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

  // 补标框 hover：与引擎热点同款浮层（编号 + 建议目标 + 注释内容 + 跳轉原文）；
  // 多成员单元逐条列出（同引擎多编号 tooltip）
  const [missHover, setMissHover] = useState<{ unit: MissUnit; rect: [number, number, number, number] } | null>(null)
  const missTimer = useRef<number | null>(null)
  const missNote = (m: MissItem) =>
    m.targetNoteId ? analysis.notes.find((n) => n.noteId === m.targetNoteId) ?? null : null
  const missEnter = (unit: MissUnit) => {
    if (missTimer.current) window.clearTimeout(missTimer.current)
    const rect = toCssRect(page, scale, unit.bbox)
    missTimer.current = window.setTimeout(() => setMissHover({ unit, rect }), HOVER_DELAY_MS)
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
  const missHoverNote = missHover ? missHover.unit.members.map((m) => missNote(m)).find(Boolean) ?? null : null

  const hsClassConf = (conf: number) =>
    'hotspot ' + (conf >= 0.95 ? 'hs-certain' : conf >= 0.7 ? 'hs-probable' : 'hs-unresolved')

  // 跳转聚光：高亮变更后 3s 内压暗其余框 + 高亮框脉冲扩散，解决页面框多难定位
  const [spotlight, setSpotlight] = useState(false)
  useEffect(() => {
    if (highlightHotspotId == null && highlightNoteId == null && highlightMissId == null) {
      setSpotlight(false)
      return
    }
    setSpotlight(true)
    const t = window.setTimeout(() => setSpotlight(false), 3000)
    return () => window.clearTimeout(t)
  }, [highlightHotspotId, highlightNoteId, highlightMissId])

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
      <div className="page-canvas" style={{ width: vpSize.w, height: vpSize.h }}>
        <canvas ref={canvasRef} />
        <div className="textLayer" ref={textRef} />
        {dims && (
          <div
              className={'ref-layer' + (missMode ? ' miss-mode' : '') + (spotlight ? ' spotlight' : '')}
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
            {/* 待审补标单元框：紫色虚线（同 group 簿记成员聚合为一个框）。
                hover 显示各成员建议目标浮层，点击跳转首个有目标的成员（同引擎热点） */}
            {misses.filter((u) => u.page === pageNo).map((u) => {
              const [x0, y0, x1, y1] = toCssRect(page, scale, u.bbox)
              const pad = Math.max(3, (y1 - y0) * 0.18)   // §5.5 外扩命中，角标太小须保证可 hover
              const w = Math.max(x1 - x0 + pad * 2, 10)
              const h = Math.max(y1 - y0 + pad * 2, 10)
              const firstNoteM = u.members.find((m) => missNote(m)) ?? null
              return (
                <div
                  key={u.key}
                  className={'miss-box' + (highlightMissId === u.key ? ' active note-pulse' : '')}
                  style={{ left: x0 - (w - (x1 - x0)) / 2, top: y0 - (h - (y1 - y0)) / 2, width: w, height: h }}
                  onMouseEnter={() => missEnter(u)}
                  onMouseLeave={missLeave}
                  onClick={() => {
                    if (firstNoteM) {
                      onJumpNote(missNote(firstNoteM)!)
                      onLocateRef(firstNoteM.id)   // 右栏列表同步定位
                    }
                  }}
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
                    onLocateRef(items[0].id)   // 右栏列表同步定位
                  }}
                />
              )
            })}
            {/* hover 浮層：單編號單條；多編號列表展示全部引用，逐條獨立跳轉。
                補標模式不渲染（框選時不留浮層，也清掉切換前殘留的 hover） */}
            {hover && tipStyle && !missMode && (
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
                        <span
                          className="tip-id" title="點擊複製引用 ID"
                          onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(hs.id).catch(() => {}) }}
                        >#{hs.id}</span>
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
                          <button onClick={() => { onJumpNote(note); onLocateRef(hs.id) }}>跳轉原文</button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
            {/* 補標 hover 浮層：多成員逐條列出（編號 + 建議目標 + 註釋內容 + 跳轉原文）。
                補標模式下也顯示（框選後即時核對），僅拖框過程中隱藏 */}
            {missHover && tipStyle && !dragRect && (
              <div
                className="tooltip"
                style={tipStyle}
                onMouseEnter={() => { if (missTimer.current) window.clearTimeout(missTimer.current) }}
                onMouseLeave={missLeave}
              >
                {missHover.unit.members.length > 1 && (
                  <div className="tip-multi">此處補標 {missHover.unit.members.length} 條註釋</div>
                )}
                {missHover.unit.members.map((m) => {
                  const note = missNote(m)
                  return (
                    <div className="tip-item" key={m.id}>
                      <div className="tip-head">
                        <span className="tip-num">{m.number ?? '?'}</span>
                        <span className="tip-loc">{m.targetDisplay ?? '未找到匹配條目'}</span>
                        <span
                          className="tip-id" title="點擊複製補標 ID"
                          onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(m.id).catch(() => {}) }}
                        >#{m.id}</span>
                        <span className="badge badge-pending">補標</span>
                      </div>
                      <div className="tip-body">
                        {note ? note.text : '未能在文檔中找到此編號的註釋條目，可導出 AI 任務處理。'}
                      </div>
                      {note && (
                        <div className="tip-foot">
                          <button onClick={() => { onJumpNote(note); onLocateRef(m.id) }}>跳轉原文</button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="page-label">P{pageNo + 1}</div>
    </div>
  )
}
