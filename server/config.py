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
    t4_min_items: int = 2            # T4 页内编号行下限（符号类单条放寬，見 notes.py）
    t4_bottom: float = 0.55          # T4 编号行 y0 粗滤阈值（真腳註另須貼近內容底部，見 notes.py）
    t4_bottom_margin: float = 100.0  # T4 編號行須距頁內內容最底端不超過此 pt（真腳註實測 ≤88；表格列表項 ≥116）
    t4_size_ratio: float = 0.8       # T4/T5 编号行字号 / 页内最大字号上限
    t1_term_ratio: float = 1.15      # T1 跨栏并入时终止行字号 / 注文主字号（基礎計劃保障表 10pt vs 註文 8pt 实测）
    # ---- T5 孤立符号解释行（1.13：页中部「* 全數賠償是指…」形态，showdoc 實測）----
    t5_min_text: int = 8             # 符号后实质文本最短字符数（排除装饰/列表点）
    t5_max_per_page: int = 2         # 单页最多捕获条数（异常排版防线）
    # ---- C8 同字号符号角标（1.13：'*' 与正文同字号同基线、異字族緊貼行尾）----
    same_size_max_ratio: float = 1.1  # C8 字号比上限（下限复用 size_ratio；排除比正文明显大）
    same_size_conf: float = 0.75     # C8 命中置信度（probable 档；無目標候選時整體剔除）
    # ---- 匹配（§5.4）----
    certain_gap: int = 2             # top1-top2 分差 >= 此值 → certain
    certain_conf: float = 0.98
    probable_conf: float = 0.75
    unresolved_conf: float = 0.50
    # ---- 正则（繁简并集；extract 已做 NFKC 归一）----
    note_head_pat: str = r"^\s*(?:備註|附註|註釋|注釋|备注|備注|註|注|Notes?)\s*[:：]?\s*$"
    inline_note_pat: str = r"^\s*(?:註|注|備註|备注)\s*[:：]\s*\S"
    item_pat: str = r"^\s*(\d{1,3})\s*[.、)](?:\s+|$)(.*)$"  # 编号点后必须是空白/行尾，排除小数费率（保费表 '0.545'）
    # TAB 编号条目（1.15：「1\t 資料來源：…」来源块形态，showdoc P7 實測——编号后
    # 无点号、TAB 分隔。TAB 是强分隔符，正文行首「数字+TAB」几乎不存在，可放心：
    # 点号可选（'0.545' 点后非 TAB 仍被排除）
    tab_item_pat: str = r"^\s*(\d{1,3})[.、)]?\t\s*(\S.*)$"
    # 裸编号行（1.15：整行仅 '5'，無點號——showdoc P7 條目 5 懸掛編號實測；
    # FWD '7.' 有點號形態由 item_pat 覆蓋）。區域內作 pending 編號與下一行合併
    bare_num_pat: str = r"^\s*(\d{1,3})(\s*)$"
    # T2 整页模式跨度：同时要求 达到内容范围的 t2_min_span_ratio 和页高的绝对下限
    # （纯内容范围会在内容稀疏页失效：信函页 3 个编号段落即占满内容范围）
    t2_min_abs_span: float = 0.3
    # T4 通道编号（无点悬挂形态）。1.15：容許符號直接黏內容（'+此服務由…'、
    # '#指定澳門醫院名單…' showdoc 實測無空格形態）。PUA 私用区（U+E000–F8FF，
    # 字體自定義符號如 Wingdings 圖形）無法枚舉，以範圍分支納入：
    roman_item_pat: str = r"^\s*(x{0,2}(?:ix|iv|v?i{0,3}))[.、)]?(?:\s+|$)(.*)$"   # i~xxx 小写罗马数字
    symbol_item_pat: str = r"^\s*([※*†‡§▲#♣+^★♠♦~▪\ue000-\uf8ff]{1,2})[.、)]?\s*(.*)$"


DEFAULT_CONFIG = ParseConfig()
