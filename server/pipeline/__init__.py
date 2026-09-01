# -*- coding: utf-8 -*-
"""解析管线总装（DESIGN.md §4.3）：extract → anchors → notes → match → AnalysisDoc。"""
import time

import pymupdf

from ..config import DEFAULT_CONFIG, ParseConfig
from .anchors import detect_anchors
from .extract import extract_lines, has_text_layer, page_heights
from .match import match_hotspots
from .notes import extract_inline_notes, find_regions, parse_region
from .schema import AnalysisDoc, ConfigSnapshot, DocMeta, Hotspot, NativeLink, NoteEntry


def analyze_pdf(path: str, doc_id: str, config: ParseConfig = DEFAULT_CONFIG) -> AnalysisDoc:
    t0 = time.time()
    doc = pymupdf.open(path)
    meta = DocMeta(
        path=path, pages=len(doc),
        title=doc.metadata.get("title") or path.rsplit("/", 1)[-1],
        hasTextLayer=has_text_layer(doc),
        mtime=doc.metadata.get("creationDate") and 0.0 or 0.0,
    )
    meta.mtime = _file_mtime(path)
    out = AnalysisDoc(docId=doc_id, meta=meta,
                      config=ConfigSnapshot(sizeRatio=config.size_ratio,
                                            riseRatio=config.rise_ratio,
                                            gapRatio=config.gap_ratio))
    if not meta.hasTextLayer:                     # §12：无文本层直接降级返回
        out.stats = {"elapsedMs": round((time.time() - t0) * 1000), "skipped": "no_text_layer"}
        return out

    lines = extract_lines(doc)
    heights = page_heights(doc)

    # ---- 引用端 ----
    anchors = detect_anchors(lines, config)
    seq = 0
    for a in anchors:
        # 多编号角标（如 '2,3'）：每编号独立热点（匹配/校对各異），
        # 但共享 group 供前端聚合为单一命中区 + 列表浮层
        group = f"g{seq:04d}" if len(a.numbers) > 1 else None
        for num in a.numbers:
            out.hotspots.append(Hotspot(
                id=f"h{seq:04d}", page=a.page,
                bbox=[round(v, 2) for v in a.bbox],
                text=num, kind=a.kind, contextBefore=a.context,
                confidence=a.confidence, group=group))
            seq += 1

    # ---- 目标端 ----
    titled_ids: set[str] = set()
    page_seq: dict[int, int] = {}          # 页内递增序号：同页同编号（備註1+註1）ID 不得冲突
    for region in find_regions(lines, heights, config):
        for note in parse_region(region, config):
            seq = page_seq.get(note.page, 0) + 1
            page_seq[note.page] = seq
            note_id = f"p{note.page}:{seq}"
            x0, y0, x1, y1 = note.bbox
            out.notes.append(NoteEntry(
                noteId=note_id, anchor=note.anchor,
                page=note.page, bbox=[round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                number=note.number, text=_clean(note.text),
                textPages=[note.page]))
            if region.titled:
                titled_ids.add(note_id)
    for inline in extract_inline_notes(lines, config):
        x0, y0, x1, y1 = inline.bbox
        out.notes.append(NoteEntry(
            noteId=f"p{inline.page}:inline{len(out.notes)}", anchor="inline",
            page=inline.page, bbox=[round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
            number="", text=_clean(inline.text), textPages=[inline.page]))

    # ---- 匹配 ----
    match_hotspots(out.hotspots, out.notes, config, titled_ids)
    _apply_native_links(doc, out.hotspots)

    out.stats = {
        "elapsedMs": round((time.time() - t0) * 1000),
        "anchors": len(out.hotspots), "notes": len(out.notes),
        "resolved": sum(1 for h in out.hotspots if h.targets),
    }
    return out


def _apply_native_links(doc, hotspots: list[Hotspot]) -> None:
    """FR-6：PDF 原生 GOTO 链接与角标 bbox 相交时直接采纳（§5.4 步骤 4）。"""
    import pymupdf as _pm
    links_by_page: dict[int, list] = {}
    for pno, page in enumerate(doc):
        got = [l for l in page.get_links() if l.get("kind") == _pm.LINK_GOTO]
        if got:
            links_by_page[pno] = got
    if not links_by_page:
        return
    for hs in hotspots:
        for lk in links_by_page.get(hs.page, []):
            r = lk["from"]
            hb = hs.bbox
            if r.x0 <= hb[2] and hb[0] <= r.x1 and r.y0 <= hb[3] and hb[1] <= r.y1:
                hs.source = "native"
                hs.nativeLink = NativeLink(page=lk["page"], y=float(lk.get("to", {}).get("y", 0)))
                hs.confidence = max(hs.confidence, 0.99)
                break


def _clean(text: str) -> str:
    return " ".join(text.split())


def _file_mtime(path: str) -> float:
    import os
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0
