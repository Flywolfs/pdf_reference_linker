# -*- coding: utf-8 -*-
"""人工标注闭环（FR-7 校对扩展）：verdict/miss 标注 → AI 任务导出/回写 → 复审。

条目状态机（annotations/{docId}.json）：
  verdict（对已有热点的判定）
    correct=true                          → confirmed
    correct=false + rebindTo              → confirmed（同时写 override，阅读器即时生效）
    correct=false 且无候选可换            → pending_ai（进入 AI 任务文件）
  miss（用户框选的漏检角标）
    自动识别+匹配到候选                   → ai_proposed（用户复审）
    未能识别/无候选                       → pending_ai
  复审：ai_proposed → accept → confirmed（生效）；reject → rejected
  AI 回写（import）：pending_ai → ai_proposed（带 targetNoteId/method/reason）
"""
import json
import re
import time
import uuid

from .cache import CACHE_DIR
from .config import ParseConfig
from .pipeline.anchors import classify
from .pipeline.extract import _norm
from .pipeline.match import match_hotspots
from .pipeline.schema import Hotspot, NoteEntry

ANNO_DIR = CACHE_DIR / "annotations"
TASKS_DIR = CACHE_DIR / "ai_tasks"
RESULTS_DIR = CACHE_DIR / "ai_results"


def anno_path(doc_id: str):
    return ANNO_DIR / f"{doc_id}.json"


def load_annotations(doc_id: str) -> dict:
    p = anno_path(doc_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {"version": 1, "entries": {}}


def save_annotations(doc_id: str, data: dict) -> None:
    ANNO_DIR.mkdir(parents=True, exist_ok=True)
    anno_path(doc_id).write_text(json.dumps(data, ensure_ascii=False, indent=1))


def set_entry(doc_id: str, entry_id: str, entry: dict) -> dict:
    data = load_annotations(doc_id)
    entry = {**entry, "ts": int(time.time())}
    data["entries"][entry_id] = entry
    save_annotations(doc_id, data)
    return entry


def verdict(doc_id: str, hotspot_id: str, correct: bool, rebind_to: str | None = None) -> dict:
    if correct:
        return set_entry(doc_id, hotspot_id,
                         {"kind": "verdict", "correct": True, "status": "confirmed"})
    if rebind_to:
        return set_entry(doc_id, hotspot_id,
                         {"kind": "verdict", "correct": False, "rebindTo": rebind_to,
                          "status": "confirmed"})
    return set_entry(doc_id, hotspot_id,
                     {"kind": "verdict", "correct": False, "status": "pending_ai"})


def identify_miss(pdf_path: str, page: int, bbox: list[float],
                  analysis: dict, config: ParseConfig) -> dict | None:
    """框选区域 → 识别角标编号 → 复用匹配管线给出候选。

    识别：区域内 span 先过 classify（独立角标），再尝试黏连词尾数字
    （如 '全數保障1' 的小字号尾数）；取字号最小者（最像角标）。
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    pg = doc[page]
    clip = pymupdf.Rect(*bbox)
    spans = []
    for blk in pg.get_text("dict", clip=clip)["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            for sp in ln["spans"]:
                if _norm(sp["text"]).strip():
                    spans.append(sp)
    cands = []
    for sp in spans:
        t = _norm(sp["text"]).strip()
        kind = classify(t)
        if kind:
            cands.append((t, kind, float(sp["size"]), tuple(sp["bbox"])))
            continue
        m = re.search(r"(\d{1,3})$", t)
        if m:
            cands.append((m.group(1), "numeric", float(sp["size"]), tuple(sp["bbox"])))
    if not cands:
        return None
    cands.sort(key=lambda c: c[2])            # 字号最小 = 最像角标
    num, kind, _, sbbox = cands[0]
    # 复用匹配管线：构造单热点 → match_hotspots
    hs = [Hotspot(id="miss", page=page,
                  bbox=[round(v, 2) for v in sbbox],
                  text=num, kind=kind, confidence=0.85)]
    notes = [NoteEntry(**n) for n in analysis["notes"]]
    titled = {n["noteId"] for n in notes if n.anchor == "footer"}
    match_hotspots(hs, notes, config, titled)
    return {"number": num, "spanBbox": hs[0].bbox,
            "targets": hs[0].targets, "targetDisplay": hs[0].targetDisplay}


def add_miss(doc_id: str, page: int, bbox: list[float], proposal: dict | None) -> tuple[str, dict]:
    entry_id = "m-" + uuid.uuid4().hex[:8]
    if proposal:
        entry = {"kind": "miss", "page": page, "bbox": bbox,
                 "number": proposal["number"], "spanBbox": proposal["spanBbox"],
                 "targets": proposal["targets"], "targetDisplay": proposal.get("targetDisplay"),
                 "method": "auto",
                 "status": "ai_proposed" if proposal["targets"] else "pending_ai"}
    else:
        entry = {"kind": "miss", "page": page, "bbox": bbox, "number": None,
                 "method": "auto", "status": "pending_ai"}
    set_entry(doc_id, entry_id, entry)
    return entry_id, entry


def review(doc_id: str, entry_id: str, accept: bool, rebind_to: str | None = None) -> dict | None:
    """复审 ai_proposed：accept → confirmed；reject → rejected。"""
    data = load_annotations(doc_id)
    e = data["entries"].get(entry_id)
    if not e:
        return None
    if accept:
        target = rebind_to or e.get("targetNoteId") or (e.get("targets") or [None])[0]
        e.update({"status": "confirmed"})
        if target:
            e["rebindTo"] = target
    else:
        e["status"] = "rejected"
    set_entry(doc_id, entry_id, e)
    return e


def apply_manual(analysis: dict, doc_id: str) -> dict:
    """把 confirmed 的 miss 条目作为手工热点注入分析输出（阅读器可见）。"""
    entries = load_annotations(doc_id).get("entries", {})
    for eid, e in entries.items():
        if e.get("kind") != "miss" or e.get("status") != "confirmed":
            continue
        if not e.get("number") or not e.get("spanBbox"):
            continue
        target = e.get("rebindTo") or (e.get("targets") or [None])[0]
        analysis["hotspots"].append({
            "id": eid, "page": e["page"], "bbox": e["spanBbox"],
            "text": e["number"], "kind": "numeric", "contextBefore": "（人工補標）",
            "targets": [target] if target else [],
            "targetDisplay": e.get("targetDisplay"),
            "confidence": 0.90, "source": "manual", "nativeLink": None, "group": None,
        })
    return analysis


def export_tasks(doc_id: str, pdf_path: str, analysis: dict) -> tuple[str, int]:
    """把 pending_ai 条目导出为 AI 任务文件（供 Qoder 会话或外部 LLM 处理）。"""
    entries = load_annotations(doc_id).get("entries", {})
    hs_index = {h["id"]: h for h in analysis["hotspots"]}
    notes_idx = [{"noteId": n["noteId"], "page": n["page"], "number": n["number"],
                  "text": n["text"][:300]} for n in analysis["notes"]]
    tasks = []
    for eid, e in entries.items():
        if e.get("status") != "pending_ai":
            continue
        if e["kind"] == "verdict":
            h = hs_index.get(eid, {})
            tasks.append({
                "id": eid, "kind": "wrong_link", "page": h.get("page"),
                "number": h.get("text"), "contextBefore": h.get("contextBefore"),
                "currentTargets": h.get("targets", []),
                "hint": "用户判定当前链接错误，请从 notesIndex 中找出正确条目",
            })
        else:
            tasks.append({
                "id": eid, "kind": "missed_anchor", "page": e.get("page"),
                "number": e.get("number"), "bbox": e.get("bbox"),
                "hint": "用户框选的漏检角标，请从 notesIndex 中找出对应条目",
            })
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    out = TASKS_DIR / f"{doc_id}.json"
    out.write_text(json.dumps({
        "docId": doc_id, "pdfPath": pdf_path, "generatedAt": int(time.time()),
        "notesIndex": notes_idx, "tasks": tasks,
    }, ensure_ascii=False, indent=1))
    return str(out), len(tasks)


def import_results(doc_id: str, results: dict) -> int:
    """回写 AI 分析结果：{"results": [{id, targetNoteId, method?, reason?}]}。

    仅作用于 pending_ai 条目 → ai_proposed，等待用户复审。
    """
    data = load_annotations(doc_id)
    n = 0
    for r in results.get("results", []):
        e = data["entries"].get(r.get("id"))
        if not e or e.get("status") != "pending_ai":
            continue
        if not r.get("targetNoteId"):
            continue
        e.update({"status": "ai_proposed", "targetNoteId": r["targetNoteId"],
                  "method": r.get("method", "llm"), "reason": r.get("reason", "")})
        data["entries"][r["id"]] = e
        n += 1
    if n:
        save_annotations(doc_id, data)
    return n
