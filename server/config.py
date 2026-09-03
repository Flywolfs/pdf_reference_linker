# -*- coding: utf-8 -*-
"""解析阈值参数（DESIGN.md NFR-5：集中可配，无需改代码即可调参）。"""
from dataclasses import dataclass


@dataclass
class ParseConfig:
    # ---- 角标检测（§5.1）----
    size_ratio: float = 0.80         # C1 角标字号 / 正文上限（实测 0.58~0.72）
    strong_ratio: float = 0.70       # 强命中字号比（conf 0.98）
    rise_ratio: float = 0.22         # C2 基线升高 / 正文字号（实测 0.33）
    strong_rise_ratio: float = 0.30  # 强命中基线升高比（实测 0.34）
    gap_ratio: float = 0.6           # C4 与正文水平间距上限 / 正文字号
    gap_neg_ratio: float = -0.2      # C4 允许的少量 bbox 重叠
    comma_multi_conf: float = 0.70   # C7 同字号逗号多编号（AIA 表头 '1,7'）置信度
    # ---- 注释区（§5.2）----
    footer_zone: float = 0.5         # T1 标题 y/页高 > 此值 → footer，否则 standalone
    t2_min_items: int = 3            # T2 整页模式最少编号行
    t2_small_ratio: float = 0.75     # T2 条目行字号 / 页内最大字号上限
    t2_max_head_size: float = 15.0   # T2 页内最大字号上限（排除带大标题的表格页，实测注释页 ≤14pt、表格页 29pt）
    t2_min_span_ratio: float = 0.45  # T2 编号行 y 跨度 / 页高下限
    # ---- 页底悬挂脚注区（T4：罗马数字/符号编号，AIA 单张「資料來源 i~viii」等）----
    t4_min_items: int = 2            # T4 页内悬挂/同行编号行下限
    t4_bottom: float = 0.55          # T4 编号行 y0 必须低于页高此比例（页底）
    t4_size_ratio: float = 0.8       # T4 编号行字号 / 页内最大字号上限
    t1_term_ratio: float = 1.15      # T1 跨栏并入时终止行字号 / 注文主字号（基礎計劃保障表 10pt vs 註文 8pt 实测）
    # ---- 匹配（§5.4）----
    certain_gap: int = 2             # top1-top2 分差 >= 此值 → certain
    certain_conf: float = 0.98
    probable_conf: float = 0.75
    unresolved_conf: float = 0.50
    # ---- 正则（繁简并集；extract 已做 NFKC 归一）----
    note_head_pat: str = r"^\s*(?:備註|附註|註釋|注釋|备注|備注|註|注|Notes?)\s*[:：]?\s*$"
    inline_note_pat: str = r"^\s*(?:註|注|備註|备注)\s*[:：]\s*\S"
    item_pat: str = r"^\s*(\d{1,3})\s*[.、)](?:\s+|$)(.*)$"  # 编号点后必须是空白/行尾，排除小数费率（保费表 '0.545'）
    # T4 通道编号（无点悬挂形态，编号后须空白或行尾）：
    roman_item_pat: str = r"^\s*(x{0,2}(?:ix|iv|v?i{0,3}))[.、)]?(?:\s+|$)(.*)$"   # i~xxx 小写罗马数字
    symbol_item_pat: str = r"^\s*([※*†‡§▲#♣^]{1,2})[.、)]?(?:\s+|$)(.*)$"          # ※/*/…/双字符 **


DEFAULT_CONFIG = ParseConfig()
