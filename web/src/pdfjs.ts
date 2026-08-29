import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

export type PDFDocumentProxy = pdfjsLib.PDFDocumentProxy
export type PDFPageProxy = pdfjsLib.PDFPageProxy
export const getDocument = pdfjsLib.getDocument

/** 渲染一页到 canvas（含 devicePixelRatio 清晰度处理） */
export async function renderPage(
  page: PDFPageProxy,
  canvas: HTMLCanvasElement,
  scale: number,
): Promise<{ cssW: number; cssH: number }> {
  const dpr = window.devicePixelRatio || 1
  const vp = page.getViewport({ scale: scale * dpr })
  const cssVp = page.getViewport({ scale })
  canvas.width = Math.floor(vp.width)
  canvas.height = Math.floor(vp.height)
  canvas.style.width = `${Math.floor(cssVp.width)}px`
  canvas.style.height = `${Math.floor(cssVp.height)}px`
  const ctx = canvas.getContext('2d')!
  await page.render({ canvasContext: ctx, viewport: vp }).promise
  return { cssW: cssVp.width, cssH: cssVp.height }
}

/** PDF pt bbox → CSS px rect（顶点序归一），rect = [x0,y0,x1,y1] 左上原点。
 *
 * 后端（PyMuPDF）bbox 已是左上原点坐标；pdf.js viewport 变换假设输入为
 * PDF 原生左下原点，需先翻 y（y_pdf = 页高 − y_top）再变换，否则垂直镜像。
 */
export function toCssRect(
  page: PDFPageProxy,
  scale: number,
  bbox: number[],
): [number, number, number, number] {
  const vp = page.getViewport({ scale })
  const h = page.getViewport({ scale: 1 }).height
  const [x0, ty0, x1, ty1] = bbox
  const r = vp.convertToViewportRectangle([x0, h - ty1, x1, h - ty0])
  const n = pdfjsLib.Util.normalizeRect(r)
  return [n[0], n[1], n[2], n[3]]
}

/** 左上原点 pt 点 → CSS px 坐标（y 翻转理由同上） */
export function toCssPoint(page: PDFPageProxy, scale: number, x: number, yTop: number): [number, number] {
  const vp = page.getViewport({ scale })
  const h = page.getViewport({ scale: 1 }).height
  const p = vp.convertToViewportPoint(x, h - yTop)
  return [p[0], p[1]]
}
