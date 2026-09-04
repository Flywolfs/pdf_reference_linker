# -*- coding: utf-8 -*-
"""导出人工确认金标集（引擎升级评测用，ANNOTATION.md 数据沉淀）。

聚合 data/annotations/*.json 中 status=confirmed 的条目，join 解析缓存得到
引擎原始输出（不含 overrides/手工注入），逐行写 data/gold/gold_set.jsonl：

  link_ok   引擎链接正确（人工 ✓）        finalTarget = 引擎当时 top1
  link_fix  引擎链接错误（人工 ✗+换绑）    engineTargets vs finalTarget(rebindTo)
  miss_add  引擎漏检（人工补标）           engineTargets 为空，finalTarget=确认目标

每条含 docId/pdf/page/number/anchorBbox/contextBefore/engineTargets/finalTarget，
可直接用作引擎升级后的回归评测集（对比新引擎输出与 finalTarget）。
注意：link_ok 的 engineTargets 取当前缓存，若管线升级后重新解析，以新缓存为准。
用法：uv run python scripts/export_gold.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.annotations import ANNO_DIR, load_annotations  # noqa: E402
from server.cache import CACHE_DIR, DATA_DIR  # noqa: E402

OUT = DATA_DIR / "gold" / "gold_set.jsonl"


def _engine_hotspots(doc_id: str) -> dict:
    """解析缓存中的引擎原始热点（缓存不存在 → 空表，verdict 条目缺引擎信息）。"""
    f = CACHE_DIR / f"{doc_id}.json"
    if not f.exists():
        return {}
    c = json.loads(f.read_text())
    a = c.get("analysis", c)
    return {h["id"]: h for h in a.get("hotspots", [])}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with OUT.open("w", encoding="utf-8") as w:
        for p in sorted(ANNO_DIR.glob("*.json")):
            doc_id = p.stem
            ann = load_annotations(doc_id)
            hs = _engine_hotspots(doc_id)
            for eid, e in ann.get("entries", {}).items():
                if e.get("status") != "confirmed":
                    continue
                if e.get("kind") == "verdict":
                    h = hs.get(eid, {})
                    rec = {
                        "id": eid, "docId": doc_id,
                        "kind": "link_ok" if e.get("correct") else "link_fix",
                        "page": h.get("page"), "number": h.get("text"),
                        "contextBefore": h.get("contextBefore"),
                        "anchorBbox": h.get("bbox"),
                        "engineTargets": h.get("targets", []),
                        "finalTarget": (h.get("targets") or [None])[0] if e.get("correct")
                                       else e.get("rebindTo"),
                        "ts": e.get("ts"),
                    }
                else:
                    rec = {
                        "id": eid, "docId": doc_id, "kind": "miss_add",
                        "page": e.get("page"), "number": e.get("number"),
                        "contextBefore": None,
                        "anchorBbox": e.get("spanBbox") or e.get("bbox"),
                        "engineTargets": [],
                        "finalTarget": e.get("rebindTo") or (e.get("targets") or [None])[0],
                        "method": e.get("method"), "ts": e.get("ts"),
                    }
                w.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    print(f"導出 {n} 條人工確認記錄 → {OUT}")


if __name__ == "__main__":
    main()
