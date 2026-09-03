# -*- coding: utf-8 -*-
"""注释区锚定与条目解析（DESIGN.md §5.2/5.3）。

T1 标题锚定：「備註/註：/Notes」独立标题行 → 下方区域（FWD p16 / AIA p15 两种标题均覆盖）
T2 整页模式：无标题兜底，页内 >=3 个 N. 小字号编号行
T3 行内註解：`註：xxx` 无编号就地说明，存档但不参与匹配（实测无角标触发）
T4 页底悬挂脚注区：罗马数字/符号编号（AIA 单张「資料來源 i~viii」、增值服務 ※/†/*），
   无标题、位于页底、小字号；双栏页按编号列 x0 聚类分栏。
条目解析状态机：`N. 内容` 起始；不匹配新编号 → 上一条目续行；整行仅 `N.`/`i`/`※` →
与下一行合并（FWD p16 悬挂 '7.' / AIA P2 悬挂 'i' 同型）。
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
    kind: str = "t1"                  # t1 | t2 | t4（决定条目编号通道，T4 才启用罗马/符号）


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


def _match_item(text: str, config: ParseConfig, t4: bool = False) -> "re.Match | None":
    """行首编号判定。T4 区域额外启用罗马数字/符号编号通道（§5.2）。"""
    pats = (config.item_pat, config.roman_item_pat, config.symbol_item_pat) if t4 \
        else (config.item_pat,)
    for pat in pats:
        m = re.match(pat, text)
        if m:
            return m
    return None


def _try_t2(page: int, pls: list, h: float, config: ParseConfig) -> NoteRegion | None:
    """T2：整页编号行模式（无标题兜底，保守：仅限无大标题、编号行占据大半页的页面）。"""
    item_lines = [l for l in pls if re.match(config.item_pat, l.text)]
    if not item_lines:
        return None
    page_max = max(s.size for l in pls for s in l.spans)
    if page_max > config.t2_max_head_size:
        return None                    # 表格页/正文页（带大标题），排除
    small = [l for l in item_lines
             if max(s.size for s in l.spans) <= page_max * config.t2_small_ratio]
    if len(small) < config.t2_min_items or not small:
        return None
    y_span = (max(l.bbox[3] for l in small) - min(l.bbox[1] for l in small))
    if y_span >= h * config.t2_min_span_ratio and small[0].bbox[1] < h * 0.5:
        return NoteRegion(page, "standalone", False, small, kind="t2")
    return None


def _find_footer_regions(page: int, pls: list, h: float,
                         config: ParseConfig) -> list[NoteRegion]:
    """T4：页底悬挂编号脚注区（罗马数字 i/ii/… 与符号 ※/*/…，无标题）。

    AIA 单张实测形态：页底「資料來源」i~viii、「增值服務」※†*——编号为独立
    小字号行（悬挂）或编号+内容同行。触发条件（全部满足）：
    页内编号行 >= t4_min_items、全部位于页底、字号相对小。
    双栏页按编号列 x0 聚类分栏，每栏一个 footer 区域（栏内行按 y 排序）。
    """
    items = []
    for ln in pls:
        m = _match_item(ln.text, config, t4=True)
        if m and (m.group(1) or "").strip():
            items.append(ln)
    if len(items) < config.t4_min_items:
        return []
    page_max = max(s.size for l in pls for s in l.spans)
    if any(ln.bbox[1] < h * config.t4_bottom for ln in items):
        return []                      # 编号行必须全部位于页底
    if any(max(s.size for s in ln.spans) > page_max * config.t4_size_ratio
           for ln in items):
        return []                      # 编号行必须小字号
    w = max((l.bbox[2] for l in pls), default=0.0)
    col_gap = max(60.0, w / 4)         # 编号列聚类间距（双栏页两列间距 ≈ 页宽/2）
    xs = sorted(ln.bbox[0] for ln in items)
    groups = [[xs[0]]]
    for x in xs[1:]:
        (groups[-1].append(x) if x - groups[-1][-1] <= col_gap else groups.append([x]))
    if len(groups) > 3:
        return []                      # 簇过多视为异常排版，放弃
    out = []
    for g in groups:
        c = sum(g) / len(g)
        near = 60.0                    # 行首与编号列的水平距离（栏内缩进 <15pt）
        col_items = sorted((ln for ln in items if abs(ln.bbox[0] - c) <= near),
                           key=lambda l: l.bbox[1])
        if len(col_items) < config.t4_min_items:
            continue
        first_y = col_items[0].bbox[1]
        col_lines = sorted(
            (l for l in pls if abs(l.bbox[0] - c) <= near and l.bbox[1] >= first_y - 2),
            key=lambda l: (l.bbox[1], l.bbox[0]))
        out.append(NoteRegion(page, "footer", False, col_lines, kind="t4"))
    return out


def _page_columns(pls: list) -> list[int]:
    """按行 x 区间重叠的连通分量分栏（DESIGN.md §5.2「同栏区域」/§12 双栏风险）。

    返回与 pls 等长的栏 id 列表。x 投影区间合并：排序后扫描，行 x0 超出已积累
    max_x1 一个容差即新栏。容差取页宽 4%（A4≈24pt）：悬挂缩进的编号列与正文
    列间距实测仅 ~10pt（宏利 P28 註 1-11），须并为一栏；真双栏间距 >80pt
    （showdoc P10 备註在右栏），仍可分栏。
    """
    idx = sorted(range(len(pls)), key=lambda i: pls[i].bbox[0])
    ids = [0] * len(pls)
    col = -1
    max_x1 = None
    tol = max(20.0, max((l.bbox[2] for l in pls), default=0.0) * 0.04)
    for i in idx:
        x0, x1 = pls[i].bbox[0], pls[i].bbox[2]
        if max_x1 is None or x0 > max_x1 + tol:
            col += 1
            max_x1 = x1
        else:
            max_x1 = max(max_x1, x1)
        ids[i] = col
    return ids


def _extend_cross_columns(pls: list, cols: list, title_idx: int,
                          body: list, config: ParseConfig) -> None:
    """T1 跨栏续排并入（DESIGN.md §5.2 区域边界 b + §12 双栏风险）。

    标题栏之外的栏按栏首 x0 顺序、栏内按 y 顺序并入标题下方行（双栏注释区
    阅读流，P14 註:1-16 → 右栏 17-18 实测）；遇字号明显大于注文主字号的行
    （后续章节标题，如「基礎計劃保障表」10pt vs 註文 8pt）立即终止。
    """
    ty1 = pls[title_idx].bbox[3] - 1
    sizes = sorted(s.size for l in body for s in l.spans)
    ref = sizes[len(sizes) // 2] if sizes else 0.0
    tcol = cols[title_idx]
    others = sorted(
        {c for j, c in enumerate(cols) if c != tcol and pls[j].bbox[1] > ty1},
        key=lambda c: min(pls[j].bbox[0] for j in range(len(pls)) if cols[j] == c))
    for c in others:
        for j, l in enumerate(pls):
            if cols[j] != c or l.bbox[1] <= ty1:
                continue
            if max(s.size for s in l.spans) > ref * config.t1_term_ratio:
                return
            body.append(l)


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
                # 栏划分仅限标题下方区域：页眉/表格等跨栏行在标题上方时不参与
                # 连通，避免把真双栏桥接合并（showdoc P14 实测）
                below = [l for l in pls if l.bbox[1] > ln.bbox[3] - 1]
                cols = _page_columns([ln] + below)
                body = [l for k, l in enumerate(below, start=1) if cols[k] == cols[0]]
                if body:
                    _extend_cross_columns([ln] + below, cols, 0, body, config)
                    regions.append(NoteRegion(page, zone, True, body, kind="t1"))
                    head_idx = i
                break
        if head_idx is not None:
            continue
        t2 = _try_t2(page, pls, h, config)
        if t2:
            regions.append(t2)
            continue
        # T4：页底罗马数字/符号悬挂脚注（AIA 資料來源 i~viii、※†* 说明区）
        regions.extend(_find_footer_regions(page, pls, h, config))
    return regions


def parse_region(region: NoteRegion, config: ParseConfig) -> list[ParsedNote]:
    notes: list[ParsedNote] = []
    cur: ParsedNote | None = None
    pending_number: str | None = None     # 整行仅编号的悬挂编号
    t4 = region.kind == "t4"
    for ln in region.lines:
        if ln.text and all("\ue000" <= ch <= "\uf8ff" for ch in ln.text):
            continue                      # 私有区符号行（Wingdings 箭头等）不可作编号/内容
        m = _match_item(ln.text, config, t4=t4)
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
