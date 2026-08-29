# -*- coding: utf-8 -*-
"""磁盘缓存 + 校对覆盖（DESIGN.md §6）：mtime 失效、overrides 叠加。"""
import json
import os
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "pdf_ref_reader"
INDEX_FILE = CACHE_DIR / "index.json"
OVERRIDE_DIR = CACHE_DIR / "overrides"


def _ensure() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)


def cache_path(doc_id: str) -> Path:
    return CACHE_DIR / f"{doc_id}.json"


def load_analysis(doc_id: str, mtime: float) -> dict | None:
    """缓存命中（mtime 一致）则返回 dict，否则 None。"""
    p = cache_path(doc_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if data.get("meta", {}).get("mtime") == mtime:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_analysis(doc_id: str, data: dict) -> None:
    _ensure()
    cache_path(doc_id).write_text(json.dumps(data, ensure_ascii=False))


def get_path(doc_id: str) -> str | None:
    """docId → 源 PDF 路径（注册表）。"""
    _ensure()
    if INDEX_FILE.exists():
        try:
            idx = json.loads(INDEX_FILE.read_text())
            return idx.get(doc_id, {}).get("path")
        except json.JSONDecodeError:
            pass
    return None


def register(doc_id: str, path: str) -> None:
    _ensure()
    idx = {}
    if INDEX_FILE.exists():
        try:
            idx = json.loads(INDEX_FILE.read_text())
        except json.JSONDecodeError:
            idx = {}
    idx[doc_id] = {"path": path, "mtime": os.path.getmtime(path)}
    INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False))


# ---- FR-7 校对覆盖 ----

def load_overrides(doc_id: str) -> dict:
    p = OVERRIDE_DIR / f"{doc_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_override(doc_id: str, hotspot_id: str, patch: dict) -> None:
    _ensure()
    all_ov = load_overrides(doc_id)
    all_ov[hotspot_id] = patch
    (OVERRIDE_DIR / f"{doc_id}.json").write_text(json.dumps(all_ov, ensure_ascii=False))


def apply_overrides(analysis: dict, overrides: dict) -> dict:
    """rebind → 改绑 targets/targetDisplay；ignore → confidence=0 且 targets 清空。"""
    for hs in analysis.get("hotspots", []):
        ov = overrides.get(hs["id"])
        if not ov:
            continue
        if ov.get("action") == "ignore":
            hs["targets"] = []
            hs["targetDisplay"] = None
            hs["confidence"] = 0.0
        elif ov.get("action") == "rebind" and ov.get("targetNoteId"):
            hs["targets"] = [ov["targetNoteId"]]
            hs["targetDisplay"] = ov.get("targetDisplay") or ov["targetNoteId"]
            hs["confidence"] = 0.90
    return analysis
