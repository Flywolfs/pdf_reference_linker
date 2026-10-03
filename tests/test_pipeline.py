# -*- coding: utf-8 -*-
"""管线测试（DESIGN.md §11）：陷阱用例 + 真实样本断言。

前提：insurance 语料库在本机默认路径。样本缺失时相关测试跳过。
"""
import pytest

from server.config import DEFAULT_CONFIG
from server.pipeline import analyze_pdf
from server.scanner import doc_id

INS = "/home/zhangchi/Documents/insurance"
FWD = f"{INS}/FWD/自愿医保/倍衛您醫療計劃-產品宣傳單張.pdf"
AIA = f"{INS}/AIA/自愿医保/AIA自愿医保灵活计划-产品小册子.pdf"


def _analysis(path):
    return analyze_pdf(path, doc_id(path), DEFAULT_CONFIG)


@pytest.fixture(scope="module")
def fwd():
    return _analysis(FWD)


@pytest.fixture(scope="module")
def aia():
    return _analysis(AIA)


# ---------- §11 陷阱单测：必须常绿 ----------

def test_trap_statute_number_not_anchor(aia):
    """《稅務條例》(第112章)：同字号 dy=0，不得产出 hotspot '112'。"""
    assert not [h for h in aia.hotspots if h.text == "112"]


def test_trap_no_native_hotspots_on_blank(aia):
    """解析完整性：热点编号必须为短编号（<=3 位数字/带圈/符号/字母）。"""
    import re
    for h in aia.hotspots:
        assert re.fullmatch(r"\d{1,3}|[①-⑳]+|[*†‡§※+#]+|[a-zA-Z]", h.text), h


# ---------- FWD 倍衛您：正文+表格角标 → 文末備註区 ----------

def test_fwd_body_anchor(fwd):
    """p2 正文角标 '1'（…全數保障1）存在且强置信。"""
    hs = [h for h in fwd.hotspots if h.page == 1 and h.text == "1"]
    assert hs, "p2 应检出正文角标 1"
    assert any(h.contextBefore and "保障" in h.contextBefore for h in hs)


def test_fwd_table_anchor_matched(fwd):
    """p3 表格角标 '5'（扣稅優惠5）→ p16 備註 5 排序首位。

    FWD 存在第二组合法编号区（p20 不保事項 1-9，无标题），编号 1-9 复用 →
    按设计 §12 策略降级为 probable（非误报，交校对面板）；排序仍应指向備註区。
    """
    hs = [h for h in fwd.hotspots if h.page == 2 and h.text == "5"
          and "稅" in (h.contextBefore or "")]
    assert hs, "p3 应检出表格角标 5"
    top = hs[0]
    assert top.targets, "角标 5 应匹配到目标"
    assert top.targets[0] == "p15:5", top.targets
    assert 0.7 <= top.confidence < 0.9, top.confidence


def test_fwd_notes_parsed(fwd):
    """p16 備註区解析出编号条目，'7.' 悬挂编号行被正确合并。

    实测该区共 9 条（条目 9 在页尾截断，跨页续接属 J 形态，M2 支持）。
    """
    notes = {n.number: n for n in fwd.notes if n.page == 15 and n.anchor != "inline"}
    assert set(notes) == {"1", "2", "3", "4", "5", "6", "7", "8", "9"}, set(notes)
    assert "指定危疾" in notes["7"].text, "悬挂编号 7. 应与正文行合并"


def test_fwd_multi_number_split(fwd):
    """多角标连写（如 '2,3'）拆分为独立 hotspot，且共享 group 供前端聚合。"""
    pairs = [(h.text, h.contextBefore) for h in fwd.hotspots]
    nums = [t for t, _ in pairs]
    assert any(t in nums for t in ("2", "3"))
    grouped = [h for h in fwd.hotspots if h.group]
    assert grouped, "多编号角标应有 group"
    by_group: dict[str, set[str]] = {}
    for h in grouped:
        by_group.setdefault(h.group, set()).add(h.text)
    assert any(len(v) > 1 for v in by_group.values()), "同组应含 >1 个编号"


# ---------- AIA 灵活计划：表格角标跨页 → p15 註：区 ----------

def test_aia_cross_page_match(aia):
    """p12 表格角标 2 → p15:2（跨页 certain），文本含索償证明语义。"""
    hs = [h for h in aia.hotspots if h.page == 11 and h.text == "2"]
    assert hs, "p12 应检出角标 2"
    assert any(t == "p14:2" for t in hs[0].targets), hs[0].targets


def test_aia_notes_region(aia):
    """p15 註：区解析出 >=12 条编号条目。"""
    notes = [n for n in aia.notes if n.page == 14 and n.anchor != "inline"]
    assert len(notes) >= 12, len(notes)


def test_aia_inline_note_no_match(aia):
    """p9/p11 行内註：为 inline，不作为匹配目标。"""
    inline = [n for n in aia.notes if n.anchor == "inline"]
    assert inline, "应识别出行内註解"
    assert all(not n.number for n in inline)


# ---------- AIA showdoc.jsp：C8 同字号符号角标 + T5 孤立符号解释行（1.13） ----------

@pytest.fixture(scope="module")
def showdoc():
    return _analysis(f"{INS}/AIA/自愿医保/showdoc.jsp.pdf")


def test_showdoc_same_size_star_detected(showdoc):
    """C8：表格「全數賠償*」同字号同基线符号角标应检出（1.13 前漏检）。"""
    hs = [h for h in showdoc.hotspots if h.page == 12 and h.text == "*"]
    assert len(hs) >= 8, f"P13 表格应检出 >=8 个 '*' 角标，实得 {len(hs)}"


def test_showdoc_orphan_symbol_note(showdoc):
    """T5：P15 页中部「* 全數賠償是指…」解释行应解析为注释条目（1.13 前三通道错过）。"""
    notes = [n for n in showdoc.notes if n.page == 14 and n.number == "*"]
    assert len(notes) == 1, [n.noteId for n in notes]
    assert "全數賠償" in notes[0].text


def test_showdoc_star_nearest_down(showdoc):
    """就近向下：P13/P14 的 '*' 应链 P15 解释（p14:11），而非兜底到 P8（p7:1）。"""
    hs = [h for h in showdoc.hotspots if h.page in (12, 13) and h.text == "*"]
    assert hs, "P13/P14 应检出 '*' 角标"
    bad = {(h.page, h.targets) for h in hs if not h.targets or h.targets[0] != "p14:11"}
    assert not bad, bad


# ---------- AIA showdoc.jsp：1.15 TAB 來源塊 + 逗號空格多編號 + 符號黏內容 ----------

def test_showdoc_tab_source_block(showdoc):
    """T2：P7「N<TAB> 資料來源」来源块应解析出 1-13 全部条目（含悬挂裸编号 5）。"""
    notes = {n.number: n for n in showdoc.notes if n.page == 6}
    assert set(notes) == {str(i) for i in range(1, 14)}, sorted(notes, key=str)
    assert "主題性住戶統計調查" in notes["5"].text, "悬挂编号 5 应与内容行合并"


def test_showdoc_comma_space_anchor(showdoc):
    """C7/NUM 容空格：'10, 11'（逗号后带空格）应拆为两个热点并链 P7 来源块。"""
    hs10 = [h for h in showdoc.hotspots if h.page == 4 and h.text == "10"]
    hs11 = [h for h in showdoc.hotspots if h.page == 4 and h.text == "11"]
    assert hs10 and hs11, "P5 '10, 11' 应检出两个热点"
    assert hs10[0].targets and hs10[0].targets[0] == "p6:10"
    assert hs11[0].targets and hs11[0].targets[0] == "p6:11"


def test_showdoc_plus_hash_symbols(showdoc):
    """'+' / '#' 角标（含解释行）应检出并链同页脚注。"""
    plus = [h for h in showdoc.hotspots if h.page == 7 and h.text == "+"]
    hash_hs = [h for h in showdoc.hotspots if h.page == 11 and h.text == "#"]
    assert plus and all(h.targets and h.targets[0] == "p7:1" for h in plus)
    assert hash_hs and all(h.targets and h.targets[0] == "p11:1" for h in hash_hs)


# ---------- 性能（NFR-1） ----------

def test_perf_under_2s(aia):
    assert aia.stats["elapsedMs"] < 2000, aia.stats
