import { useEffect, useMemo, useState } from 'react'
import type { Analysis, Annotations, DocInfo, Hotspot } from './api'
import { api } from './api'
import PdfViewer from './viewer/PdfViewer'

export default function App() {
  const [docs, setDocs] = useState<DocInfo[]>([])
  const [root, setRoot] = useState('')
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<{ doc: DocInfo; analysis: Analysis } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // ---- 人工标注闭环状态 ----
  const [annos, setAnnos] = useState<Annotations | null>(null)
  const [reviewMode, setReviewMode] = useState(false)
  const [missMode, setMissMode] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    api.documents()
      .then((r) => {
        setDocs(r.documents)
        setRoot(r.root)
      })
      .catch((e) => setError(String(e)))
  }, [])

  const open = async (doc: DocInfo) => {
    setLoading(true)
    setError('')
    setExpandedId(null)
    setMissMode(false)
    try {
      const r = await api.analyze(doc.path)
      setSelected({ doc, analysis: r.analysis })
      api.annotations(doc.docId).then(setAnnos).catch(() => setAnnos({ version: 1, entries: {} }))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  // 标注生效后刷新分析数据（overrides 重绑 / 人工补标热点注入）
  const refreshAnalysis = async (docId: string) => {
    const a = await api.analysis(docId)
    setSelected((s) => (s && s.doc.docId === docId ? { ...s, analysis: a } : s))
  }

  const reloadAnnos = async (docId: string) => {
    setAnnos(await api.annotations(docId))
  }

  const doVerdict = async (hotspotId: string, correct: boolean, rebindTo?: string) => {
    if (!selected) return
    await api.verdict(selected.doc.docId, hotspotId, correct, rebindTo)
    await reloadAnnos(selected.doc.docId)
    await refreshAnalysis(selected.doc.docId)
  }

  const doReview = async (entryId: string, accept: boolean) => {
    if (!selected) return
    await api.review(selected.doc.docId, entryId, accept)
    await reloadAnnos(selected.doc.docId)
    await refreshAnalysis(selected.doc.docId)
  }

  // 补标框选回调（PageView 拖框 → PDF pt bbox）
  const handleMissBoxed = async (pageNo: number, bboxPdf: number[]) => {
    if (!selected) return
    try {
      const r = await api.miss(selected.doc.docId, pageNo, bboxPdf)
      const e = r.entry
      const desc = e.number
        ? `識別到角標「${e.number}」${e.targetDisplay ? `→ ${e.targetDisplay}` : '，未找到匹配條目'}`
        : '未識別到角標編號（可框得更精確一些）'
      alert(`補標完成：${desc}\n狀態：${e.status === 'ai_proposed' ? '待複審（見右欄底部）' : '待 AI 處理（可導出任務文件）'}`)
      await reloadAnnos(selected.doc.docId)
    } catch (e) {
      alert(`補標失敗：${e}`)
    }
  }

  const doExport = async () => {
    if (!selected) return
    try {
      const r = await api.exportTasks(selected.doc.docId)
      alert(`已導出 ${r.taskCount} 項待處理任務 →\n${r.file}\n\n可交由 AI 會話或指定 LLM 按約定 schema 處理後導入。`)
    } catch (e) {
      alert(`導出失敗：${e}`)
    }
  }

  const doImport = async () => {
    if (!selected) return
    const txt = window.prompt('粘貼 AI 處理結果 JSON：\n{"results":[{"id":"h0014","targetNoteId":"p19:5","method":"llm","reason":"…"}]}')
    if (!txt) return
    try {
      const r = await api.importResults(selected.doc.docId, JSON.parse(txt))
      alert(`已導入 ${r.imported} 條 AI 提案，請在右欄複審（接受/拒絕）。`)
      await reloadAnnos(selected.doc.docId)
    } catch (e) {
      alert(`導入失敗：${JSON.stringify(e)}`)
    }
  }

  const shown = useMemo(
    () => docs.filter((d) => (d.relPath + d.name).toLowerCase().includes(filter.toLowerCase())),
    [docs, filter],
  )

  const byFolder = useMemo(() => {
    const m = new Map<string, DocInfo[]>()
    for (const d of shown) {
      const list = m.get(d.folder) ?? []
      list.push(d)
      m.set(d.folder, list)
    }
    return [...m.entries()]
  }, [shown])

  const hotspots = selected?.analysis.hotspots ?? []
  // 同编号注释条目 = 错链候选（跨注释区复用编号场景）
  const candidatesOf = (h: Hotspot) =>
    (selected?.analysis.notes ?? []).filter((n) => n.anchor !== 'inline' && n.number === h.text)

  const verdictEntries = annos ? Object.entries(annos.entries).filter(([, e]) => e.kind === 'verdict') : []
  const missEntries = annos ? Object.entries(annos.entries).filter(([, e]) => e.kind === 'miss') : []
  const pendingAi = annos ? Object.values(annos.entries).filter((e) => e.status === 'pending_ai').length : 0

  return (
    <div className="app">
      {/* 左：文档列表（FR-1） */}
      <aside className="doc-list">
        <h1>條款角標閱讀器</h1>
        <div className="root-path" title={root}>{root}</div>
        <input
          className="search"
          placeholder="搜索文檔…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="doc-scroll">
          {byFolder.map(([folder, list]) => (
            <div key={folder}>
              <div className="folder">{folder}</div>
              {list.map((d) => (
                <div
                  key={d.docId}
                  className={'doc-item' + (selected?.doc.docId === d.docId ? ' active' : '')}
                  onClick={() => open(d)}
                >
                  {d.name}
                </div>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* 中：阅读器 */}
      {selected ? (
        <PdfViewer docId={selected.doc.docId} analysis={selected.analysis} missMode={missMode} onMissBoxed={handleMissBoxed} />
      ) : (
        <main className="viewer-pane empty">
          <div className="placeholder">
            <h2>選擇左側 PDF 開始閱讀</h2>
            <p>載入後自動鏈接角標引用與註釋，滑鼠懸停角標即可查看引用內容。</p>
            {loading && <p className="loading-inline">解析中…</p>}
            {error && <p className="error-inline">{error}</p>}
          </div>
        </main>
      )}

      {/* 右：引用总览 + 人工标注闭环（FR-7） */}
      {selected && (
        <aside className="ref-pane">
          <div className="ref-head">
            <h3>引用總覽</h3>
            <label className="rev-toggle">
              <input
                type="checkbox"
                checked={reviewMode}
                onChange={(e) => {
                  setReviewMode(e.target.checked)
                  if (!e.target.checked) {
                    setMissMode(false)
                    setExpandedId(null)
                  }
                }}
              />
              審核模式
            </label>
          </div>
          <div className="ref-stats">
            {hotspots.filter((h) => h.targets.length).length} / {hotspots.length} 已鏈接
            {reviewMode && ` · 已審 ${verdictEntries.length} · 待AI ${pendingAi}`}
          </div>
          {reviewMode && (
            <div className="rev-actions">
              <button className={missMode ? 'on' : ''} onClick={() => setMissMode((m) => !m)}>
                {missMode ? '補標中…（在頁面拖框）' : '補標漏檢'}
              </button>
              <button onClick={doExport}>導出AI任務</button>
              <button onClick={doImport}>導入結果</button>
            </div>
          )}
          <div className="ref-scroll">
            {hotspots.map((h) => {
              const v = annos?.entries[h.id]
              const reviewed = v?.kind === 'verdict' && v.status === 'confirmed' && v.correct
              return (
                <div key={h.id}>
                  <div
                    className={'ref-item' + (h.targets.length ? '' : ' unresolved')}
                    title={h.targetDisplay ?? ''}
                    onClick={() => {
                      const pageEl = document.querySelector(`[data-page="${h.page}"]`) as HTMLElement | null
                      const container = document.querySelector('.scroll')
                      if (pageEl && container) {
                        const vpTop = h.bbox[1] * (pageEl.querySelector('.page-canvas')?.clientHeight ?? 0) / pageHeightPt(selected.analysis, h.page)
                        container.scrollTo({ top: pageEl.offsetTop + vpTop - 120, behavior: 'smooth' })
                      }
                    }}
                  >
                    <span className="ref-page">P{h.page + 1}</span>
                    <span className="ref-ctx">{h.contextBefore || '…'}</span>
                    <sup className="ref-num">{h.text}</sup>
                    <span className="ref-arrow">→</span>
                    <span className="ref-target">{h.targetDisplay ?? '未匹配'}</span>
                    <span className={'dot ' + (h.confidence >= 0.95 ? 'green' : h.confidence >= 0.7 ? 'amber' : 'gray')} />
                    {reviewMode && (
                      <span className="rev-btns" onClick={(e) => e.stopPropagation()}>
                        {reviewed ? (
                          <span className="rev-done">✓</span>
                        ) : (
                          <>
                            <button title="鏈接正確" onClick={() => doVerdict(h.id, true)}>✓</button>
                            <button title="鏈接錯誤" onClick={() => setExpandedId(expandedId === h.id ? null : h.id)}>✗</button>
                          </>
                        )}
                        {v?.status === 'pending_ai' && <span className="badge badge-pending">待AI</span>}
                      </span>
                    )}
                  </div>
                  {reviewMode && expandedId === h.id && (
                    <div className="cand-panel">
                      <div className="cand-title">選擇正確目標，或標記待 AI 處理：</div>
                      {candidatesOf(h).map((n) => (
                        <button key={n.noteId} onClick={() => { setExpandedId(null); doVerdict(h.id, false, n.noteId) }}>
                          P{n.page + 1} · {n.text.slice(0, 44)}{n.text.length > 44 ? '…' : ''}
                        </button>
                      ))}
                      <button className="cand-ai" onClick={() => { setExpandedId(null); doVerdict(h.id, false) }}>
                        均不正確 → 標記待 AI 處理
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
            {/* 補標（miss）條目複審 */}
            {reviewMode && missEntries.length > 0 && (
              <>
                <div className="miss-sep">補標條目（{missEntries.length}）</div>
                {missEntries.map(([id, e]) => (
                  <div key={id} className="ref-item miss-item">
                    <span className="ref-page">P{(e.page ?? 0) + 1}</span>
                    <span className="ref-ctx">補標 {e.number ?? '?'}</span>
                    <span className="ref-arrow">→</span>
                    <span className="ref-target">{e.targetDisplay ?? e.rebindTo ?? e.targetNoteId ?? '未匹配'}</span>
                    {e.status === 'ai_proposed' && (
                      <span className="rev-btns" >
                        <button title="接受補標" onClick={() => doReview(id, true)}>✓</button>
                        <button title="拒絕補標" onClick={() => doReview(id, false)}>✗</button>
                      </span>
                    )}
                    {e.status === 'pending_ai' && <span className="badge badge-pending">待AI</span>}
                    {e.status === 'confirmed' && <span className="rev-done">✓已生效</span>}
                    {e.status === 'rejected' && <span className="rev-done">已拒絕</span>}
                  </div>
                ))}
              </>
            )}
          </div>
        </aside>
      )}
    </div>
  )
}

function pageHeightPt(analysis: Analysis, page: number): number {
  // 页面 pt 高度近似（A4 842pt）；仅用于总览跳转的粗略定位
  void analysis
  return 842 / 1
}
