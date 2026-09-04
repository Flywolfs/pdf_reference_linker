// 后端 API 客户端与类型（对应 server/pipeline/schema.py 数据契约）

export interface DocInfo {
  name: string
  relPath: string
  folder: string
  path: string
  sizeKB: number
  docId: string
}

export interface Note {
  noteId: string
  anchor: 'footer' | 'standalone' | 'inline'
  page: number // 0-based
  bbox: [number, number, number, number]
  number: string
  text: string
  textPages: number[]
}

export interface Hotspot {
  id: string
  page: number
  bbox: [number, number, number, number]
  text: string
  kind: string
  contextBefore: string
  targets: string[]
  targetDisplay: string | null
  confidence: number
  source: 'native' | 'derived' | 'manual'
  group?: string | null // 同一多编号角标（如 '2,3'）共享的组 id
}

export interface AnnoEntry {
  kind: 'verdict' | 'miss'
  status: 'confirmed' | 'pending_ai' | 'ai_proposed' | 'rejected'
  correct?: boolean
  rebindTo?: string
  targetNoteId?: string
  page?: number
  bbox?: number[]
  number?: string | null
  spanBbox?: number[]
  targets?: string[]
  targetDisplay?: string | null
  method?: string
  reason?: string
  ts?: number
}

export interface Annotations {
  version: number
  entries: Record<string, AnnoEntry>
}

export interface Analysis {
  docId: string
  meta: { path: string; pages: number; title: string; hasTextLayer: boolean }
  notes: Note[]
  hotspots: Hotspot[]
  stats: Record<string, unknown>
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 200)}`)
  return res.json() as Promise<T>
}

export const api = {
  documents: (root?: string) =>
    fetch(`/api/documents${root ? `?root=${encodeURIComponent(root)}` : ''}`).then(json<{ root: string; documents: DocInfo[] }>),

  analyze: (path: string) =>
    fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }).then(json<{ docId: string; cached: boolean; analysis: Analysis }>),

  // 带 overrides + 人工补标热点的分析数据（标注/复审后刷新用）
  analysis: (docId: string) => fetch(`/api/analysis/${docId}`).then(json<Analysis>),

  pdfUrl: (docId: string) => `/api/pdf/${docId}`,

  // ---- 人工标注闭环 ----
  annotations: (docId: string) =>
    fetch(`/api/annotations/${docId}`).then(json<Annotations>),

  verdict: (docId: string, hotspotId: string, correct: boolean, rebindTo?: string) =>
    fetch('/api/annotate/verdict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ docId, hotspotId, correct, rebindTo }),
    }).then(json<{ ok: boolean; entry: AnnoEntry }>),

  miss: (docId: string, page: number, bbox: number[]) =>
    fetch('/api/annotate/miss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ docId, page, bbox }),
    }).then(json<{ entryId: string; entry: AnnoEntry; replaced: boolean }>),

  deleteMiss: (docId: string, entryId: string) =>
    fetch(`/api/annotate/miss/${docId}/${entryId}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),

  review: (docId: string, entryId: string, accept: boolean, rebindTo?: string) =>
    fetch('/api/annotate/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ docId, entryId, accept, rebindTo }),
    }).then(json<{ ok: boolean; entry: AnnoEntry }>),

  exportTasks: (docId: string) =>
    fetch('/api/annotate/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ docId }),
    }).then(json<{ ok: boolean; file: string; taskCount: number }>),

  importResults: (docId: string, results: unknown) =>
    fetch('/api/annotate/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ docId, results }),
    }).then(json<{ ok: boolean; imported: number }>),
}
