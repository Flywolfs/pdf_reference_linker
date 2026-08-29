# -*- coding: utf-8 -*-
"""角标检测（DESIGN.md §5.1）。

双条件（字号比 C1 + 基线升高 C2）为主通道，紧贴性 C4 + 邻接正文 C5 排除
表格数字列/页码；C7 通道兜底同字号逗号多编号（AIA 表头 '1,7'，每段 <=2 位
以排除 '8,000' 千位分隔符）。
"""
import re
from dataclasses import dataclass

from ..config import ParseConfig
from .extract import Line, Span

NUM_RE = re.compile(r"^\d{1,3}(?:[,，]\d{1,3})*$")
# C7：逗号多编号且每段 <=2 位（千位分隔符至少有一段 3 位，被此式排除）
COMMA_MULTI_RE = re.compile(r"^\d{1,2}(?:[,，]\d{1,2})+$")
CIRCLED = set("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")
STARS = set("*†‡§※")
LETTER_RE = re.compile(r"^[a-z]$", re.IGNORECASE)


@dataclass
class AnchorHit:
    page: int
    bbox: tuple
    numbers: list                     # '2,3' → ['2','3']
    kind: str
    context: str                      # 左侧正文名称（尾部）
    confidence: float


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
        if (tight and kind is not None
                and size_ratio <= config.size_ratio
                and rise >= config.rise_ratio * ctx.size):
            strong = size_ratio <= config.strong_ratio and rise >= config.strong_rise_ratio * ctx.size
            hit = (0.98 if strong else 0.85, kind)
        elif comma_multi and tight and abs(rise) <= 0.35 * ctx.size:
            # C7：同字号逗号多编号，无法用字号/基线区分，降置信度
            hit = (config.comma_multi_conf, "numeric")
        if hit is None:
            last_body = sp          # 判定失败的数字是正文（如年龄、金额、'第112章'）
            continue
        conf, final_kind = hit
        ctx_text = "".join(s.text for s in line.spans if s is not sp).strip()
        hits.append(AnchorHit(line.page, sp.bbox, _split_numbers(sp.text),
                              final_kind, ctx_text[-24:], conf))
    return hits


def _split_numbers(text: str) -> list[str]:
    parts = [p for p in re.split(r"[,，]", text.strip()) if p]
    return parts or [text.strip()]


def detect_anchors(lines: list[Line], config: ParseConfig) -> list[AnchorHit]:
    out: list[AnchorHit] = []
    for line in lines:
        out.extend(_detect_line(line, config))
    return out
