import { useEffect, useMemo, useState } from 'react'
import type { Analysis, DocInfo } from './api'
import { api } from './api'
import PdfViewer from './viewer/PdfViewer'

export default function App() {
  const [docs, setDocs] = useState<DocInfo[]>([])
  const [root, setRoot] = useState('')
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<{ doc: DocInfo; analysis: Analysis } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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
    try {
      const r = await api.analyze(doc.path)
      setSelected({ doc, analysis: r.analysis })
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
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
        <PdfViewer docId={selected.doc.docId} analysis={selected.analysis} />
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

      {/* 右：引用总览（FR-7 只读部分，校对面板 M2） */}
      {selected && (
        <aside className="ref-pane">
          <h3>引用總覽</h3>
          <div className="ref-stats">
            {hotspots.filter((h) => h.targets.length).length} / {hotspots.length} 已鏈接
          </div>
          <div className="ref-scroll">
            {hotspots.map((h) => (
              <div
                key={h.id}
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
              </div>
            ))}
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
