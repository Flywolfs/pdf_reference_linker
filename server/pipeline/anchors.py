# -*- coding: utf-8 -*-
"""角标检测（DESIGN.md §5.1）。

双条件（字号比 C1 + 基线升高 C2）为主通道，紧贴性 C4 + 邻接正文 C5 排除
表格数字列/页码；C7 通道兜底同字号逗号多编号（AIA 表头 '1,7'，每段 <=2 位
以排除 '8,000' 千位分隔符）；C8 通道（1.13）兜底同字号符号角标——'*' 与正文
同字号同基线但異字族（AIA showdoc 表格「全數賠償*」實測：MHeiHKS vs
AIAEverest）。C8 僅開放符號集（數字同字號形態誤報太多，見 §2.4 陷阱表），
檢出標記 loose，管線在匹配後剔除無目標候選者（目標存在性收口）。
"""
import re
from dataclasses import dataclass

from ..config import ParseConfig
from .extract import Line, Span

NUM_RE = re.compile(r"^\d{1,3}(?:\s*[,，]\s*\d{1,3})*$")
# C7：逗号多编号且每段 <=2 位（千位分隔符至少有一段 3 位，被此式排除）；
# 1.15 容忍逗号后空格（showdoc '10, 11' 實測）
COMMA_MULTI_RE = re.compile(r"^\d{1,2}(?:\s*[,，]\s*\d{1,2})+$")
CIRCLED = set("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")
STARS = set("*†‡§※+#")
LETTER_RE = re.compile(r"^[a-z]$", re.IGNORECASE)


@dataclass
class AnchorHit:
    page: int
    bbox: tuple
    numbers: list                     # '2,3' → ['2','3']
    kind: str
    context: str                      # 左侧正文名称（尾部）
    confidence: float
    loose: bool = False               # 宽松通道（C8）检出：匹配后无候选须剔除


def _font_family(font: str) -> str:
    """字体名 → 家族名（'AIAEverest-Regular' → 'AIAEverest'）。"""
    return font.split("-")[0].split("+")[0]


def classify(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    if all(ch in CIRCLED for ch in t):
        return "circled"
    if all(ch in STARS for ch in t):
        return "asterisk"
    if NUM_RE.fullmatch(t):
        return "numeric"
    if LETTER_RE.fullmatch(t):
        return "letter"
    return None


def _detect_line(line: Line, config: ParseConfig) -> list[AnchorHit]:
    hits: list[AnchorHit] = []
    last_body: Span | None = None
    for sp in line.spans:
        kind = classify(sp.text)
        comma_multi = kind is None and bool(COMMA_MULTI_RE.fullmatch(sp.text.strip()))
        if kind is None and not comma_multi:
            last_body = sp          # 普通正文：更新邻接正文指针
            continue
        if last_body is None:       # C5 行首孤立数字（页码等）：无正文邻接
            last_body = sp
            continue
        ctx = last_body
        gap = sp.bbox[0] - ctx.bbox[2]
        rise = ctx.origin[1] - sp.origin[1]          # 正值 = 角标基线升高
        size_ratio = sp.size / ctx.size if ctx.size > 0.5 else 1.0
        tight = config.gap_neg_ratio * ctx.size <= gap <= config.gap_ratio * ctx.size
        hit = None
        loose = False
        if (tight and kind is not None
                and size_ratio <= config.size_ratio
                and rise >= config.rise_ratio * ctx.size):
            strong = size_ratio <= config.strong_ratio and rise >= config.strong_rise_ratio * ctx.size
            hit = (0.98 if strong else 0.85, kind)
        elif comma_multi and tight and abs(rise) <= 0.35 * ctx.size:
            # C7：同字号逗号多编号，无法用字号/基线区分，降置信度
            hit = (config.comma_multi_conf, "numeric")
        elif (tight and kind == "asterisk"
              and config.size_ratio < size_ratio <= config.same_size_max_ratio
              and abs(rise) <= 0.35 * ctx.size
              and _font_family(sp.font) != _font_family(ctx.font)):
            # C8（1.13）：同字号符号角标——'*' 與正文同字號同基線，緊貼詞尾且
            # 異字族（符號用西文字體、正文用中文字體，showdoc 實測）。僅符號集
            # 開放（數字同字號陷阱見 §2.4）；loose 標記 → 匹配後無候選即剔除。
            hit = (config.same_size_conf, kind)
            loose = True
        if hit is None:
            last_body = sp          # 判定失败的数字是正文（如年龄、金额、'第112章'）
            continue
        conf, final_kind = hit
        ctx_text = "".join(s.text for s in line.spans if s is not sp).strip()
        hits.append(AnchorHit(line.page, sp.bbox, _split_numbers(sp.text),
                              final_kind, ctx_text[-24:], conf, loose))
    return hits


def _split_numbers(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,，]", text.strip()) if p.strip()]
    return parts or [text.strip()]


def detect_anchors(lines: list[Line], config: ParseConfig) -> list[AnchorHit]:
    out: list[AnchorHit] = []
    # 1.15 孤立符號行：字體/字號差異令 '+  專屬禮賓支援服務' 被拆成兩個 line
    # （'+' 獨佔一行），C5 同行鄰接失效。符號類孤立行按視覺帶（y 帶重疊）跨行
    # 找左側正文鄰接，走 C1/C2 判定，conf 0.75 + loose（目標存在性收口同 C8）。
    by_page: dict[int, list[Line]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)
    for pls in by_page.values():
        body_spans = [sp for ln in pls for sp in ln.spans
                      if classify(sp.text) is None
                      and not COMMA_MULTI_RE.fullmatch(sp.text.strip())]
        for line in pls:
            hits = _detect_line(line, config)
            out.extend(hits)
            if not hits and line.spans and all(
                    classify(sp.text) is not None for sp in line.spans):
                for sp in line.spans:
                    if classify(sp.text) != "asterisk":
                        continue          # 數字孤立行（頁碼等）不做跨行判定
                    hit = _detect_orphan_symbol(line, sp, body_spans, config)
                    if hit:
                        out.append(hit)
    return out


def _detect_orphan_symbol(line: Line, sp: Span, body_spans: list[Span],
                          config: ParseConfig) -> AnchorHit | None:
    """孤立符號 span 的跨行鄰接判定：同視覺帶最近正文 + C1/C2/C4。"""
    sy = (sp.bbox[1] + sp.bbox[3]) / 2
    best, best_gap = None, None
    for ctx in body_spans:
        cy = (ctx.bbox[1] + ctx.bbox[3]) / 2
        if abs(cy - sy) > 0.6 * max(ctx.bbox[3] - ctx.bbox[1],
                                    sp.bbox[3] - sp.bbox[1], 4.0):
            continue
        gap = sp.bbox[0] - ctx.bbox[2]
        if gap < config.gap_neg_ratio * ctx.size:
            continue
        if best is None or gap < best_gap:
            best, best_gap = ctx, gap
    if best is None:
        return None
    ctx = best
    rise = ctx.origin[1] - sp.origin[1]
    size_ratio = sp.size / ctx.size if ctx.size > 0.5 else 1.0
    if not (config.gap_neg_ratio * ctx.size <= best_gap <= config.gap_ratio * ctx.size
            and size_ratio <= config.size_ratio
            and rise >= config.rise_ratio * ctx.size):
        return None
    return AnchorHit(line.page, sp.bbox, _split_numbers(sp.text), "asterisk",
                     ctx.text[-24:], config.same_size_conf, loose=True)
