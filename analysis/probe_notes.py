# -*- coding: utf-8 -*-
"""探测注释目标区形态（備註/Notes 的编号结构）与上标基线偏移特征。"""
import sys, re
import pymupdf

NOTE_HEAD = re.compile(r"^\s*(備註|备注|註|注|Notes?\s*:?|附註|附注)\s*[：:1-9①-⑳]?")

def probe_notes(path):
    doc = pymupdf.open(path)
    print(f"\n{'='*80}\nFILE: {path}")
    full = []
    for pno, page in enumerate(doc):
        for ln in page.get_text().splitlines():
            if NOTE_HEAD.match(ln):
                print(f"  p{pno+1} NOTE: {ln.strip()[:100]}")
    # 检测带圈数字和 "1 " 编号注释行
    pat_num = re.compile(r"^\s*([①-⑳]|[0-9]{1,2}|[a-z])[\.\、\)]?\s+\S")
    hits = 0
    for pno in range(len(doc)):
        for blk in doc[pno].get_text("dict")["blocks"]:
            if blk.get("type") != 0: continue
            for line in blk["lines"]:
                t = "".join(s["text"] for s in line["spans"]).strip()
                if pat_num.match(t) and any(s["size"] < 9 for s in line["spans"]):
                    hits += 1
                    if hits <= 6:
                        print(f"  p{pno+1} small-num-line: {t[:90]}")
    print(f"  total small numbered lines: {hits}")

def probe_baseline(path, page_no=2):
    """上标 span 的基线相对同 line 相邻正文 span 的偏移。"""
    doc = pymupdf.open(path)
    page = doc[page_no - 1]
    print(f"\nBASELINE FILE: {path} p{page_no}")
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0: continue
        for line in blk["lines"]:
            spans = line["spans"]
            if len(spans) < 2: continue
            sizes = [s["size"] for s in spans]
            for i, s in enumerate(spans):
                if s["size"] < max(sizes) * 0.75 and re.fullmatch(r"[0-9①-⑳\*]+", s["text"].strip()):
                    neigh = spans[i-1] if i > 0 else spans[i+1]
                    dy = neigh["origin"][1] - s["origin"][1]
                    print(f"  sup {s['text']!r:6} sz={s['size']:.1f} vs {neigh['size']:.1f} dy={dy:+.1f} line={ ''.join(x['text'] for x in spans)[:60]!r}")

if __name__ == "__main__":
    for f in sys.argv[1:]:
        try:
            probe_notes(f)
            probe_baseline(f)
        except Exception as e:
            print(f"  ERROR {f}: {e}")
