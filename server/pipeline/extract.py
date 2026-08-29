# -*- coding: utf-8 -*-
"""Line/Span 结构图提取（DESIGN.md §4.3 extract 阶段）。坐标均为 PDF pt、左上原点。"""
import unicodedata
from dataclasses import dataclass

import pymupdf


@dataclass
class Span:
    text: str
    size: float
    origin: tuple                     # (x, y) 基线起点
    bbox: tuple                       # (x0, y0, x1, y1)
    font: str


@dataclass
class Line:
    page: int                         # 0-based
    bbox: tuple
    spans: list                       # [Span]，按 x0 升序
    y: float                          # 行首 span 基线 y，用于排序

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans).strip()


def _norm(text: str) -> str:
    """NFKC 归一：全角数字/标点 → 半角，繁体正字不受影响。"""
    return unicodedata.normalize("NFKC", text)


def extract_lines(doc: "pymupdf.Document") -> list[Line]:
    lines: list[Line] = []
    for pno, page in enumerate(doc):
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                spans = [
                    Span(_norm(sp["text"]), float(sp["size"]),
                         tuple(sp["origin"]), tuple(sp["bbox"]), sp["font"])
                    for sp in ln["spans"] if _norm(sp["text"]).strip()
                ]
                if not spans:
                    continue
                spans.sort(key=lambda s: s.bbox[0])
                lines.append(Line(pno, tuple(ln["bbox"]), spans, spans[0].origin[1]))
    lines.sort(key=lambda l: (l.page, l.y, l.bbox[0]))
    return lines


def has_text_layer(doc: "pymupdf.Document", min_chars_per_page: float = 20.0) -> bool:
    """无文本层检测（DESIGN.md §12 扫描版降级）。"""
    if not len(doc):
        return False
    total = sum(len(page.get_text().strip()) for page in doc)
    return total >= min_chars_per_page * len(doc)


def page_heights(doc: "pymupdf.Document") -> list[float]:
    return [page.rect.height for page in doc]
