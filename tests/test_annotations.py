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


def test_cancel_and_restore_hotspot(monkeypatch, tmp_path):
    """取消引用：墓碑過濾列表與 PDF 熱點；恢復後重現；歷史判定保留。"""
    doc = _tmp_doc(monkeypatch, tmp_path)
    hs = {"id": "h0007", "page": 1, "bbox": [1, 1, 9, 9], "targets": ["p2:1"]}
    analysis = {"hotspots": [hs, {"id": "h0008", "page": 2, "bbox": [1, 1, 9, 9], "targets": []}],
                "notes": []}

    ann.cancel_hotspot(doc, "h0007", {"page": 1, "number": "3"})
    out = ann.apply_manual({"hotspots": [dict(hs), {"id": "h0008", "page": 2}], "notes": []}, doc)
    assert [h["id"] for h in out["hotspots"]] == ["h0008"]      # h0007 被過濾

    ann.verdict(doc, "h0007", correct=True)                     # 取消後判定仍可寫（恢復後生效）
    ann.restore_hotspot(doc, "h0007")
    out2 = ann.apply_manual({"hotspots": [dict(hs)], "notes": []}, doc)
    assert [h["id"] for h in out2["hotspots"]] == ["h0007"]     # 恢復重現
    entries = ann.load_annotations(doc)["entries"]
    assert "x-h0007" not in entries and "v-h0007" in entries    # 墓碑已刪、判定保留


def test_cancel_confirmed_miss_injection(monkeypatch, tmp_path):
    """取消一個 confirmed 補標的注入熱點：過濾須在注入之後（實測 bug 回歸）。"""
    doc = _tmp_doc(monkeypatch, tmp_path)
    ann.set_entry(doc, "m-cafe1234", {
        "kind": "miss", "page": 1, "bbox": [1, 1, 9, 9], "number": "8",
        "anchorKind": "asterisk", "spanBbox": [2, 2, 6, 6], "targets": ["p3:8"],
        "targetDisplay": "P3 · 腳註 8", "group": None, "method": "auto",
        "status": "ai_proposed"})
    ann.review(doc, "m-cafe1234", accept=True)

    out = ann.apply_manual({"hotspots": [], "notes": []}, doc)
    assert [h["id"] for h in out["hotspots"]] == ["m-cafe1234"]     # 注入正常

    ann.cancel_hotspot(doc, "m-cafe1234", {"page": 1, "number": "8"})
    out2 = ann.apply_manual({"hotspots": [], "notes": []}, doc)
    assert out2["hotspots"] == []                                   # 注入後仍被墓碑過濾

    ann.restore_hotspot(doc, "m-cafe1234")
    out3 = ann.apply_manual({"hotspots": [], "notes": []}, doc)
    assert [h["id"] for h in out3["hotspots"]] == ["m-cafe1234"]    # 恢復重現
