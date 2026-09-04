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

from .cache import DATA_DIR
from .config import ParseConfig
from .pipeline.anchors import classify
from .pipeline.extract import _norm
from .pipeline.match import match_hotspots
from .pipeline.schema import Hotspot, NoteEntry

# 人工数据存项目内 data/（劳动成果，不放 ~/.cache 以免被清理工具误删）
ANNO_DIR = DATA_DIR / "annotations"
TASKS_DIR = DATA_DIR / "ai_tasks"
RESULTS_DIR = DATA_DIR / "ai_results"


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


# 補標識別的符號全集：與 notes T4 symbol_item_pat 同集（寬於引擎檢測 STARS——
# 引擎檢測通道保持保守不動以免黃金快照漂移；人工框選有位置先驗，可放寬）
MISS_SYMS = set("※*†‡§▲#♣^")
ROMAN_RE = re.compile(r"x{0,2}(?:ix|iv|v?i{0,3})", re.IGNORECASE)


def _anchor_token(t: str) -> str | None:
    """單個錨點 token 規整：數字/帶圈/符號/字母/羅馬數字 → 規整文本，否則 None。

    尾部標點（'7.' / '^,'）先剝離——符號簇 span 常把分隔逗號帶在本 span 內。
    """
    t = t.strip().rstrip(".、)，, ")
    if not t:
        return None
    if classify(t) or all(ch in MISS_SYMS for ch in t) or ROMAN_RE.fullmatch(t):
        return t
    return None


def _span_members(t: str) -> list[str] | None:
    """逗號/頓號多編號 span（'2,3' / 'i,iii' / '※、^'）→ 成員列表，否則 None。"""
    parts = [p.strip() for p in re.split(r"[,，、]", t.strip()) if p.strip()]
    if len(parts) > 1:
        toks = [_anchor_token(p) for p in parts]
        if all(toks):
            return toks
    return None


def _center(b: list | tuple) -> tuple:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def identify_miss(pdf_path: str, page: int, bbox: list[float],
                  analysis: dict, config: ParseConfig) -> list[dict]:
    """框選區域 → 識別角標（含相鄰符號簇）→ 復用匹配管線給出候選。

    相鄰簇（'^,※,▲' 四 span、'i,iii' 單 span，showdoc P3 實測）拆為多成員，
    一次框選產生條目組（共享 group，前端聚合渲染/複審）；每成員獨立匹配，
    有候選 → ai_proposed，無 → pending_ai。符號集用 T4 同集（見 MISS_SYMS）。
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    pg = doc[page]
    clip = pymupdf.Rect(*bbox)
    cands: list[dict] = []
    for blk in pg.get_text("dict", clip=clip)["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            for sp in ln["spans"]:
                t = _norm(sp["text"]).strip()
                if not t or not t.strip(",，、"):
                    continue                      # 孤立逗號 span
                members = _span_members(t)
                if members is None:
                    tok = _anchor_token(t)
                    if tok:
                        members = [tok]
                    else:
                        # 黏連詞尾數字（'全數保障1'）；排除純數字（年份/金額）與長文本（URL）
                        m = re.search(r"(\d{1,3})[.、)]?$", t)
                        if m and not t.isdigit() and len(t) <= 8:
                            members = [m.group(1)]
                        else:
                            continue
                for num in members:
                    cands.append({"number": num, "kind": classify(num) or "asterisk",
                                  "size": float(sp["size"]), "bbox": tuple(sp["bbox"])})
    if not cands:
        return []
    # 框內混入正文詞尾數字時，僅保留與最小字號相近者（上標簇同字號，正文更大）
    smin = min(c["size"] for c in cands)
    cands = [c for c in cands if c["size"] <= smin * 1.4 + 1.0]
    # 相鄰聚簇（同行且 x 間隙小）：簇內成員共享組，前端一個框 + 多成員浮層
    cands.sort(key=lambda c: ((c["bbox"][1] + c["bbox"][3]) / 2, c["bbox"][0]))
    for i, c in enumerate(cands):
        prev = cands[i - 1] if i else None
        same_line = prev and abs(_center(c["bbox"])[1] - _center(prev["bbox"])[1]) <= 0.6 * max(
            c["bbox"][3] - c["bbox"][1], prev["bbox"][3] - prev["bbox"][1])
        gap = c["bbox"][0] - prev["bbox"][2] if prev else 1e9
        c["group_break"] = not (same_line and gap <= max(6.0, 0.6 * min(c["size"], prev["size"])))
    # 匹配：全部成員一次過 match_hotspots
    hs = [Hotspot(id=f"m{i}", page=page, bbox=[round(v, 2) for v in c["bbox"]],
                  text=c["number"], kind=c["kind"], confidence=0.85)
          for i, c in enumerate(cands)]
    notes = [NoteEntry(**n) for n in analysis["notes"]]
    titled = {n.noteId for n in notes if n.anchor == "footer"}
    match_hotspots(hs, notes, config, titled)
    return [{"number": c["number"], "kind": c["kind"],
             "spanBbox": h.bbox, "targets": h.targets, "targetDisplay": h.targetDisplay}
            for c, h in zip(cands, hs)]


def add_miss(doc_id: str, page: int, bbox: list[float],
             proposals: list[dict]) -> list[dict]:
    """新增補標條目組：一次框選識別出的全部成員各一條，len>1 時共享 group。

    去重（同頁，中心距按 max(dx,dy)）：雙方有編號 → 編號相同且 ≤12pt 纔覆蓋
    （相鄰符號角標中心距僅 5~8pt，不可只按距離合併，否則重框 '^,※' 會誤刪
    '※'）；雙方無編號 → ≤8pt；混合 → ≤4pt。返回 [{entryId, entry, replaced}]。
    """
    data = load_annotations(doc_id)
    existing = dict(data["entries"])          # 快照：同組成員互不誤傷
    group = f"mg-{uuid.uuid4().hex[:6]}" if len(proposals) > 1 else None
    out = []
    for p in proposals:
        entry = {"kind": "miss", "page": page, "bbox": bbox,
                 "number": p["number"], "anchorKind": p.get("kind", "numeric"),
                 "spanBbox": p["spanBbox"],
                 "targets": p["targets"], "targetDisplay": p.get("targetDisplay"),
                 "group": group, "method": "auto",
                 "status": "ai_proposed" if p["targets"] else "pending_ai"}
        cx, cy = _center(p["spanBbox"])
        target_id = None
        for eid, e in existing.items():
            if e.get("kind") != "miss" or e.get("page") != page:
                continue
            b = e.get("spanBbox") or e.get("bbox")
            if not b:
                continue
            ox, oy = _center(b)
            d = max(abs(ox - cx), abs(oy - cy))
            on, nn = e.get("number"), p["number"]
            if on is not None and nn is not None:
                if on == nn and d <= 12:
                    target_id = eid
                    break
            elif on is None and nn is None:
                if d <= 8:
                    target_id = eid
                    break
            elif d <= 4:
                target_id = eid
                break
        replaced = target_id is not None
        if not replaced:
            target_id = "m-" + uuid.uuid4().hex[:8]
        entry = {**entry, "ts": int(time.time())}
        data["entries"][target_id] = entry
        out.append({"entryId": target_id, "entry": entry, "replaced": replaced})
    if out:
        save_annotations(doc_id, data)
    return out


def delete_entry(doc_id: str, entry_id: str) -> bool:
    """刪除标注条目（取消補標：误框/重报后不想要了，记录彻底移除）。"""
    data = load_annotations(doc_id)
    if entry_id not in data.get("entries", {}):
        return False
    del data["entries"][entry_id]
    save_annotations(doc_id, data)
    return True


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
            "text": e["number"], "kind": e.get("anchorKind") or "numeric",
            "contextBefore": "（人工補標）",
            "targets": [target] if target else [],
            "targetDisplay": e.get("targetDisplay"),
            "confidence": 0.90, "source": "manual", "nativeLink": None,
            "group": e.get("group"),
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
