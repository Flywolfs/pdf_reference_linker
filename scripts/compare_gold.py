# -*- coding: utf-8 -*-
"""金標回歸對比（UI 導出快照 vs 當前 composite）——引擎改動後的防改錯檢查。

用法：uv run python scripts/compare_gold.py <docId>

讀 data/gold/<docId>.gold.json（用戶在 UI 點「導出金標」生成的快照，
一個 hotspot 一條記錄：kind = link_ok / link_fix / miss_add），
與當前解析緩存 + 人工數據合成的 composite 逐條對比 targetNoteId：

  OK       目標一致
  DRIFT    目標漂移（引擎/規則改動導致與金標不符——須逐一歸因：改錯則修，
           屬預期改進則由用戶在 UI 重確認後重新導出金標）
  GONE     金標熱點在當前 composite 中不存在（被取消/刪除/未注入）

cancelled 段同時核對：金標導出時已取消的引用現仍應處於取消狀態。
另可用 data/gold/<docId>.reference.json（verdict/miss 全量明細）追溯單個 id
屬「引擎判錯」（link_fix）還是「引擎漏檢」（miss_add）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import annotations  # noqa: E402
from server.cache import apply_overrides, cache_path, load_overrides  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    doc_id = sys.argv[1]
    gold_p = annotations.GOLD_DIR / f"{doc_id}.gold.json"
    if not gold_p.exists():
        print(f"金標快照不存在：{gold_p}（先在 UI 點「導出金標」）")
        return
    gold = json.loads(gold_p.read_text(encoding="utf-8"))

    cache_f = cache_path(doc_id)
    if not cache_f.exists():
        print("解析緩存不存在，先在 UI 打開文檔觸發解析")
        return
    analysis = json.loads(cache_f.read_text())
    comp = apply_overrides(
        annotations.apply_manual(analysis, doc_id), load_overrides(doc_id))
    hs = {h["id"]: h for h in comp["hotspots"]}

    ok, drifts, gone = 0, [], []
    for g in gold.get("entries", []):
        h = hs.get(g["hotspotId"])
        if h is None:
            gone.append(g)
            continue
        cur = (h.get("targets") or [None])[0]
        if cur == g["targetNoteId"]:
            ok += 1
        else:
            drifts.append((g, cur))

    # 墓碑核對：金標導出時已取消的引用不得復活
    revived = []
    ent = annotations.load_annotations(doc_id).get("entries", {})
    cancelled_now = {eid[2:] for eid, e in ent.items()
                     if e.get("kind") == "cancelled" and eid.startswith("x-")}
    for c in gold.get("cancelled", []):
        if c["hotspotId"] not in cancelled_now and c["hotspotId"] in hs:
            revived.append(c)

    ver = gold.get("analysisVersion", "?")
    print(f"金標對比 {doc_id}（金標版本 {ver}，導出 {gold.get('generatedAt')}）："
          f"{len(gold.get('entries', []))} 條")
    print(f"  OK      {ok}")
    print(f"  DRIFT   {len(drifts)}")
    print(f"  GONE    {len(gone)}")
    if revived:
        print(f"  REVIVED {len(revived)}（已取消引用復活）")
    if drifts:
        print("\n目標漂移清單：")
        for g, cur in drifts:
            print(f"  [{g['kind']}] {g['hotspotId']} P{g['page'] + 1} '{g['number']}'"
                  f"：金標→{g['targetNoteId']}，當前→{cur}")
    if gone:
        print("\n消失熱點清單：")
        for g in gone:
            print(f"  [{g['kind']}] {g['hotspotId']} P{g['page'] + 1} '{g['number']}'")
    if revived:
        print("\n復活清單：")
        for c in revived:
            print(f"  {c['hotspotId']} P{c['page'] + 1} '{c['number']}'")
    if not (drifts or gone or revived):
        print("\n全部一致，無回歸。")


if __name__ == "__main__":
    main()
