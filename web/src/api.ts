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
  source: 'native' | 'derived'
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

  pdfUrl: (docId: string) => `/api/pdf/${docId}`,
}
