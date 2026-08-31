# -*- coding: utf-8 -*-
"""生成黄金快照（DESIGN.md §11 黄金快照回归）。

用法：uv run python scripts/gen_golden.py
首次生成后必须人工审查（git diff tests/golden/、抽查阅读器效果）再提交锁定。
之后任何管线改动导致输出变化，test_golden.py 会失败并给出字段级 diff；
确认为有意变更时重新运行本脚本，并再次审查 diff。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.pipeline import analyze_pdf  # noqa: E402
from server.scanner import scan  # noqa: E402

CORPUS = "/home/zhangchi/Documents/insurance"
GOLDEN_DIR = ROOT / "tests" / "golden"
# stats 中仅保留确定性计数字段；elapsedMs 每次运行都变，不进快照
STATS_FIELDS = ("anchors", "notes", "resolved")


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    docs = scan(CORPUS)
    print(f"语料 {len(docs)} 份 → {GOLDEN_DIR}")
    for info in docs:
        a = analyze_pdf(info["path"], info["docId"])
        data = a.model_dump()
        data["stats"] = {k: data["stats"].get(k) for k in STATS_FIELDS}
        data["meta"].pop("mtime", None)  # 文件时间非管线输出
        out = GOLDEN_DIR / f"{info['docId']}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"  {info['relPath']}: hotspots={len(data['hotspots'])} "
              f"notes={len(data['notes'])} resolved={data['stats'].get('resolved')}")
    print("完成。请 git diff 审查后提交锁定。")


if __name__ == "__main__":
    main()
