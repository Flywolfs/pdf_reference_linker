# -*- coding: utf-8 -*-
"""人工标注闭环回归：verdict/miss 分 key、旧格式迁移、补标注入生命周期。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import annotations as ann  # noqa: E402


def _tmp_doc(monkeypatch, tmp_path, name="t1"):
    """把 ANNO_DIR 指到临时目录，返回 doc_id。"""
    anno_dir = tmp_path / "annotations"
    monkeypatch.setattr(ann, "ANNO_DIR", anno_dir)
    return name


def test_verdict_does_not_overwrite_miss(monkeypatch, tmp_path):
    """对补标注入热点（id=m-xxx）做 verdict，不得覆盖原 miss 记录（旧版 bug）。"""
    doc = _tmp_doc(monkeypatch, tmp_path)
    miss = {"kind": "miss", "page": 0, "bbox": [1, 1, 9, 9], "number": "2",
            "anchorKind": "numeric", "spanBbox": [2, 2, 6, 6], "targets": ["p10:2"],
            "targetDisplay": "P10 · 備註 2", "group": None, "method": "auto",
            "status": "ai_proposed"}
    ann.set_entry(doc, "m-abc12345", miss)

    ann.review(doc, "m-abc12345", accept=True)          # 接受补标
    ann.verdict(doc, "m-abc12345", correct=True)        # 主列表判链接正确

    entries = ann.load_annotations(doc)["entries"]
    m = entries["m-abc12345"]
    v = entries["v-m-abc12345"]
    assert m["kind"] == "miss" and m["status"] == "confirmed" and m["rebindTo"] == "p10:2"
    assert v["kind"] == "verdict" and v["correct"] is True and v["status"] == "confirmed"


def test_verdict_wrong_link_pending_ai_keyed_v(monkeypatch, tmp_path):
    doc = _tmp_doc(monkeypatch, tmp_path)
    ann.verdict(doc, "h0001", correct=False, rebind_to=None)
    entries = ann.load_annotations(doc)["entries"]
    assert "v-h0001" in entries and entries["v-h0001"]["status"] == "pending_ai"
    assert "h0001" not in entries                       # 旧 key 不再产生记录


def test_migrate_old_verdict_keys(monkeypatch, tmp_path):
    """旧格式（verdict 以热点 id 为 key）加载时自动迁到 'v-' 前缀。"""
    doc = _tmp_doc(monkeypatch, tmp_path)
    ann.ANNO_DIR.mkdir(parents=True, exist_ok=True)
    (ann.ANNO_DIR / f"{doc}.json").write_text(json.dumps({
        "version": 1,
        "entries": {
            "h0009": {"kind": "verdict", "correct": True, "status": "confirmed", "ts": 1},
            "h0010": {"kind": "verdict", "correct": False, "rebindTo": "p3:1",
                      "status": "confirmed", "ts": 2},
            "m-deadbeef": {"kind": "miss", "page": 1, "status": "confirmed", "ts": 3},
        },
    }, ensure_ascii=False))
    entries = ann.load_annotations(doc)["entries"]
    assert "v-h0009" in entries and "h0009" not in entries
    assert "v-h0010" in entries and "h0010" not in entries
    assert entries["m-deadbeef"]["kind"] == "miss"      # 非 verdict 记录不动
    # 迁移已回写磁盘（幂等）
    again = ann.load_annotations(doc)["entries"]
    assert "v-h0009" in again and "h0009" not in again


def test_apply_manual_survives_verdict(monkeypatch, tmp_path):
    """接受补标 → 判定链接 → 注入热点仍在（旧版 bug 的端到端断言）。"""
    doc = _tmp_doc(monkeypatch, tmp_path)
    ann.set_entry(doc, "m-feed0001", {
        "kind": "miss", "page": 2, "bbox": [1, 1, 9, 9], "number": "5",
        "anchorKind": "numeric", "spanBbox": [3, 3, 7, 7], "targets": [],
        "targetNoteId": "p4:5", "targetDisplay": "P4 · 備註 5", "group": None,
        "method": "llm", "status": "ai_proposed"})
    ann.review(doc, "m-feed0001", accept=True)
    ann.verdict(doc, "m-feed0001", correct=True)

    analysis = {"hotspots": [], "notes": []}
    ann.apply_manual(analysis, doc)
    assert len(analysis["hotspots"]) == 1
    hs = analysis["hotspots"][0]
    assert hs["id"] == "m-feed0001" and hs["targets"] == ["p4:5"] and hs["source"] == "manual"
