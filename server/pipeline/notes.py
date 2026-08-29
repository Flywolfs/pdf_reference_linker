# -*- coding: utf-8 -*-
"""注释区锚定与条目解析（DESIGN.md §5.2/5.3）。

T1 标题锚定：「備註/註：/Notes」独立标题行 → 下方区域（FWD p16 / AIA p15 两种标题均覆盖）
T2 整页模式：无标题兜底，页内 >=3 个 N. 小字号编号行
T3 行内註解：`註：xxx` 无编号就地说明，存档但不参与匹配（实测无角标触发）
条目解析状态机：`N. 内容` 起始；不匹配新编号 → 上一条目续行；整行仅 `7.` →
与下一行合并（FWD p16 边界情况）。
"""
import re
from dataclasses import dataclass, field

from ..config import ParseConfig
from .extract import Line


@dataclass
class NoteRegion:
    page: int
    anchor: str                       # footer | standalone
    titled: bool                      # T1 标题锚定
    lines: list = field(default_factory=list)


@dataclass
class ParsedNote:
    page: int
    anchor: str
    number: str
    lines: list                       # 组成行
    text: str = ""

    @property
    def bbox(self) -> tuple:
        x0 = min(l.bbox[0] for l in self.lines)
        y0 = min(l.bbox[1] for l in self.lines)
        x1 = max(l.bbox[2] for l in self.lines)
        y1 = max(l.bbox[3] for l in self.lines)
        return (x0, y0, x1, y1)


def find_regions(lines: list[Line], page_heights: list[float],
                 config: ParseConfig) -> list[NoteRegion]:
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        by_page.setdefault(ln.page, []).append(ln)

    regions: list[NoteRegion] = []
    for page, pls in by_page.items():
        h = page_heights[page] if page < len(page_heights) else 842.0
        head_idx = None
        for i, ln in enumerate(pls):                      # T1：标题行
            if re.fullmatch(config.note_head_pat, ln.text):
                zone = "footer" if ln.bbox[1] > h * config.footer_zone else "standalone"
                body = [l for l in pls if l.bbox[1] > ln.bbox[3] - 1]
                if body:
                    regions.append(NoteRegion(page, zone, True, body))
                    head_idx = i
                break
        if head_idx is not None:
            continue
        # T2：整页编号行模式（无标题兜底，保守：仅限无大标题、编号行占据大半页的页面）
        item_lines = [l for l in pls if re.match(config.item_pat, l.text)]
        if not item_lines:
            continue
        page_max = max(s.size for l in pls for s in l.spans)
        if page_max > config.t2_max_head_size:
            continue                    # 表格页/正文页（带大标题），排除
        small = [l for l in item_lines
                 if max(s.size for s in l.spans) <= page_max * config.t2_small_ratio]
        if len(small) < config.t2_min_items or not small:
            continue
        y_span = (max(l.bbox[3] for l in small) - min(l.bbox[1] for l in small))
        if y_span >= h * config.t2_min_span_ratio and small[0].bbox[1] < h * 0.5:
            regions.append(NoteRegion(page, "standalone", False, small))
    return regions


def parse_region(region: NoteRegion, config: ParseConfig) -> list[ParsedNote]:
    notes: list[ParsedNote] = []
    cur: ParsedNote | None = None
    pending_number: str | None = None     # 整行仅 'N.' 的悬挂编号
    for ln in region.lines:
        m = re.match(config.item_pat, ln.text)
        if m:
            rest = (m.group(2) or "").strip()
            if rest:                      # 编号与内容同行：新条目
                cur = ParsedNote(region.page, region.anchor, m.group(1), [ln])
                cur.text = rest
                notes.append(cur)
                pending_number = None
            else:                         # 整行仅 'N.'：悬挂，等下一行
                pending_number = m.group(1)
            continue
        if pending_number is not None:    # FWD p16 '7.' 与正文分行 → 合并
            cur = ParsedNote(region.page, region.anchor, pending_number, [ln])
            cur.text = ln.text
            notes.append(cur)
            pending_number = None
            continue
        if cur is not None:               # 续行（不匹配新编号即续接，见 §5.3）
            cur.lines.append(ln)
            cur.text = (cur.text + " " + ln.text).strip()
        # cur 为 None 的区域前导行（标题与首条目间杂项）→ 忽略
    return notes


def extract_inline_notes(lines: list[Line], config: ParseConfig) -> list[ParsedNote]:
    out = []
    for ln in lines:
        if re.match(config.inline_note_pat, ln.text):
            n = ParsedNote(ln.page, "inline", "", [ln])
            n.text = ln.text
            out.append(n)
    return out
