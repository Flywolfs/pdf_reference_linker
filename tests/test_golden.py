# -*- coding: utf-8 -*-
"""黄金快照回归（DESIGN.md §11）：锁定 35 份语料的管线全部输出。

- bbox 坐标容差 0.5pt（浮点噪声），其余字段严格相等
- stats.elapsedMs / meta.mtime 为非确定字段，不参与对比
- 输出有意变更时：uv run python scripts/gen_golden.py 重新生成，审查 diff 后提交
"""
import json
from pathlib import Path

import pytest

from server.pipeline import analyze_pdf
from server.scanner import doc_id, scan

CORPUS = "/home/zhangchi/Documents/insurance"
GOLDEN = Path(__file__).parent / "golden"
BBOX_TOL = 0.5
# 非确定/运行环境字段不参与对比：elapsedMs 每次都变；mtime 是文件属性；
# stats 仅保留确定性计数（与 scripts/gen_golden.py 的 STATS_FIELDS 保持一致）
STATS_FIELDS = ("anchors", "notes", "resolved")

_docs = scan(CORPUS) if Path(CORPUS).is_dir() else []


def _collect_diffs(prefix: str, g, a, out: list[str]) -> None:
    """字段级递归对比；仅 .bbox 路径下的数值允许 BBOX_TOL 容差。"""
    if isinstance(g, dict) and isinstance(a, dict):
        for k in sorted(set(g) | set(a)):
            _collect_diffs(f"{prefix}.{k}", g.get(k), a.get(k), out)
    elif isinstance(g, list) and isinstance(a, list):
        if len(g) != len(a):
            out.append(f"{prefix}: 长度 {len(g)} → {len(a)}")
            return
        if prefix.endswith(".bbox"):
            for i, (x, y) in enumerate(zip(g, a)):
                if not (isinstance(x, (int, float)) and isinstance(y, (int, float))
                        and abs(x - y) <= BBOX_TOL):
                    out.append(f"{prefix}[{i}]: {x!r} → {y!r}")
        else:
            for i, (x, y) in enumerate(zip(g, a)):
                _collect_diffs(f"{prefix}[{i}]", x, y, out)
    elif g != a:
        out.append(f"{prefix}: {g!r} → {a!r}")


def _diff_against_golden(path: str, golden: dict) -> list[str]:
    actual = analyze_pdf(path, doc_id(path)).model_dump()
    for d in (actual, golden):
        d["meta"].pop("mtime", None)
        d["stats"] = {k: d["stats"].get(k) for k in STATS_FIELDS}
    out: list[str] = []
    _collect_diffs("$", golden, actual, out)
    return out


@pytest.mark.skipif(not _docs, reason=f"语料库不存在: {CORPUS}")
@pytest.mark.parametrize("info", _docs, ids=lambda i: i["relPath"])
def test_golden_snapshot(info):
    golden_p = GOLDEN / f"{info['docId']}.json"
    assert golden_p.exists(), f"缺少快照，请运行 scripts/gen_golden.py: {info['relPath']}"
    golden = json.loads(golden_p.read_text())
    diffs = _diff_against_golden(info["path"], golden)
    assert not diffs, (
        f"{info['relPath']} 输出与黄金快照不符（共 {len(diffs)} 处，前 20 条）:\n"
        + "\n".join(diffs[:20])
        + "\n若为有意变更，请运行 scripts/gen_golden.py 并人工审查 diff。"
    )
