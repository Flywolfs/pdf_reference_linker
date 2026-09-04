# -*- coding: utf-8 -*-
"""金标回归评测（引擎升级闭环的度量端，配合 scripts/export_gold.py）。

对 gold_set.jsonl 中每条人工确认记录，用**当前引擎**（直接重跑管线，不走缓存）
重新解析所在文档，将金标锚点与新热点按 页码+编号+中心距 匹配，对比 finalTarget：

  pass     引擎检出该锚点且 top1 目标 == finalTarget
  wrong    检出但目标不对（匹配打分问题）
  missed   锚点未检出（检测/区域问题，miss_add 的核心指标）

升级工作流：改参数/规则 → uv run python scripts/eval_gold.py → 无回退且
link_fix/miss_add 通过率上升 → 重新生成黄金快照 → 提交。与 tests/test_gold.py
互为补充：黄金快照锁全量输出防回归，本脚本度量金标达标率看改进。
用法：uv run python scripts/eval_gold.py [--kind miss_add]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.cache import DATA_DIR  # noqa: E402
from server.pipeline import analyze_pdf  # noqa: E402
from server.scanner import scan  # noqa: E402

GOLD = DATA_DIR / "gold" / "gold_set.jsonl"
CORPUS = "/home/zhangchi/Documents/insurance"
TOL_VERDICT = 3.0    # verdict 类：bbox 取自引擎缓存，理应精确复现
TOL_MISS = 8.0       # miss_add 类：人工框选/span 定位，允许小偏差（同 add_miss 去重阈值）


def _center(b: list) -> tuple:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _match(page: int, number, bbox: list, hotspots: list, tol: float) -> dict | None:
    """页码+编号+中心距匹配金标锚点 → 新热点（无则 None）。"""
    cx, cy = _center(bbox)
    for h in hotspots:
        if h["page"] != page or h["text"] != str(number):
            continue
        hx, hy = _center(h["bbox"])
        if abs(hx - cx) <= tol and abs(hy - cy) <= tol:
            return h
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["link_ok", "link_fix", "miss_add"], default=None,
                    help="只评测某一类记录")
    args = ap.parse_args()

    if not GOLD.exists():
        print("金标集不存在，先运行 scripts/export_gold.py")
        return
    recs = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    if args.kind:
        recs = [r for r in recs if r["kind"] == args.kind]

    by_doc: dict[str, list] = defaultdict(list)
    for r in recs:
        by_doc[r["docId"]].append(r)

    docs = {d["docId"]: d for d in scan(CORPUS)}
    stats: dict[str, dict] = defaultdict(lambda: {"pass": 0, "wrong": 0, "missed": 0})
    failures: list[str] = []
    for doc_id, rs in sorted(by_doc.items()):
        info = docs.get(doc_id)
        if not info:
            failures.append(f"!! {doc_id} 不在语料中，跳过 {len(rs)} 条")
            continue
        a = analyze_pdf(info["path"], doc_id).model_dump()
        hs = a["hotspots"]
        for r in rs:
            tol = TOL_MISS if r["kind"] == "miss_add" else TOL_VERDICT
            h = _match(r["page"], r["number"], r["anchorBbox"], hs, tol)
            if h is None:
                stats[r["kind"]]["missed"] += 1
                failures.append(f"[missed] {r['kind']} {r['id']} {doc_id} "
                                f"P{r['page'] + 1} '{r['number']}'：引擎未检出该锚点"
                                f"（归因方向：字号比/基线升高/符号字符集/注释区锚定）")
            elif (h["targets"] or [None])[0] != r["finalTarget"]:
                stats[r["kind"]]["wrong"] += 1
                failures.append(f"[wrong]  {r['kind']} {r['id']} {doc_id} "
                                f"P{r['page'] + 1} '{r['number']}'："
                                f"引擎→{(h['targets'] or [None])[0]}，金标→{r['finalTarget']}"
                                f"（归因方向：匹配打分/候选歧义）")
            else:
                stats[r["kind"]]["pass"] += 1

    print(f"金标回归评测：{len(recs)} 条记录 / {len(by_doc)} 份文档（当前引擎直接重跑，不走缓存）")
    for kind in ("link_ok", "link_fix", "miss_add"):
        s = stats.get(kind)
        if not s:
            continue
        total = s["pass"] + s["wrong"] + s["missed"]
        print(f"  {kind:<9} {s['pass']:>4}/{total:<4} 通过   wrong={s['wrong']}  missed={s['missed']}")
    if failures:
        print("\n失败清单：")
        for f in failures:
            print(f"  {f}")
    else:
        print("\n全部通过。")


if __name__ == "__main__":
    main()
