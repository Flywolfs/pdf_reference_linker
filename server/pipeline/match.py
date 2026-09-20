# -*- coding: utf-8 -*-
"""引用-注释匹配与置信度（DESIGN.md §5.4）。"""
from ..config import ParseConfig

ANCHOR_LABEL = {"footer": "腳註", "standalone": "備註"}


def match_hotspots(hotspots: list, notes: list, config: ParseConfig,
                   titled_note_ids: set[str] | None = None) -> None:
    """就地填充 hotspot.targets / targetDisplay / confidence。hotspot/notes 为 schema 模型。

    titled_note_ids：T1 标题锚定区产出的 noteId 集合，仅这些区获得锚定加分（§5.4）。
    """
    titled_note_ids = titled_note_ids or set()
    candidates = [n for n in notes if n.anchor != "inline" and n.number]
    by_num: dict[str, list] = {}
    for n in candidates:
        by_num.setdefault(n.number, []).append(n)
    # 唯一编号集合
    unique_nums = {k for k, v in by_num.items() if len(v) == 1}
    # 区域最大编号（按 page+anchor 分组近似），用于越界惩罚
    zone_max: dict[tuple, int] = {}
    for n in candidates:
        key = (n.page, n.anchor)
        try:
            zone_max[key] = max(zone_max.get(key, 0), int(n.number))
        except ValueError:
            continue

    for hs in hotspots:
        cands = by_num.get(hs.text, [])
        if not cands:
            hs.confidence = config.unresolved_conf
            hs.targets, hs.targetDisplay = [], None
            continue
        scored = []
        for n in cands:
            s = 0
            # 就近向下（用戶閱讀習慣，§5.4 修訂）：同編號腳註常跨頁重複出現以便查閱，
            # 應鏈到錨點「向下最近」的解釋——同頁錨點下方首選，其次後續頁由近及遠，
            # 更早頁僅在無任何向下候選時兜底。
            if n.page == hs.page:
                below = n.bbox[1] >= hs.bbox[3] - 2.0    # 註釋區起點在錨點之下（同行容差）
                if n.anchor == "footer":
                    s += 5 if below else 1               # 同頁下方腳註首選；上方罕見
                else:
                    s += 4 if below else 1               # 同頁下方備註次之
            elif n.page > hs.page:
                s += 3 - min(n.page - hs.page, 3)        # 後續頁：越近越高（2/1/0）
            else:
                s -= 4                                   # 更早頁：強懲罰（兜底）
            if hs.text in unique_nums:
                s += 3                                   # 文档级唯一
            if n.noteId in titled_note_ids:
                s += 1                                   # T1 标题锚定区
            key = (n.page, n.anchor)
            try:
                if int(hs.text) > zone_max.get(key, int(hs.text)):
                    s -= 2                               # 编号越界
            except ValueError:
                pass
            scored.append((s, n))
        scored.sort(key=lambda t: (-t[0], (t[1].page, t[1].bbox[1])))
        top_s, top = scored[0]
        gap = top_s - (scored[1][0] if len(scored) > 1 else -99)
        hs.targets = [n.noteId for _, n in scored]
        hs.targetDisplay = f"P{top.page + 1} · {ANCHOR_LABEL.get(top.anchor, top.anchor)} {top.number}"
        if gap >= config.certain_gap:
            hs.confidence = config.certain_conf
        else:
            hs.confidence = min(0.95, config.probable_conf + max(0, gap) * 0.05)
