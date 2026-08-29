# -*- coding: utf-8 -*-
"""探测保险 PDF 中角标引用的真实形态：上标 span、注释区形态、链接注释。"""
import sys, re, json
import pymupdf

def probe(path, max_pages=4):
    doc = pymupdf.open(path)
    print(f"\n{'='*80}\nFILE: {path}  pages={len(doc)}")
    for pno in range(min(max_pages, len(doc))):
        page = doc[pno]
        d = page.get_text("dict")
        # 1) 找上标 span（字号显著小于同行正文，且是数字/带圈数字等）
        spans = []
        for blk in d["blocks"]:
            if blk.get("type") != 0:
                continue
            for line in blk["lines"]:
                for sp in line["spans"]:
                    spans.append(sp)
        if not spans:
            continue
        sizes = sorted(set(round(s["size"],1) for s in spans))
        body = sizes[len(sizes)//2] if sizes else 0
        sups = [s for s in spans
                if s["size"] < body * 0.75
                and re.fullmatch(r"[0-9①-⑳⑴-⑽a-zA-Z\*\uFF0A]+", s["text"].strip())
                and len(s["text"].strip()) <= 4]
        print(f"  -- p{pno+1} sizes={sizes} body≈{body} sup_candidates={len(sups)}")
        for s in sups[:8]:
            print(f"     sup: {s['text']!r} size={s['size']:.1f} font={s['font']} origin_y={s['origin'][1]:.1f} flags={s['flags']}")
        # 2) 找"注"/"備註"/"Notes"区域行
        text = page.get_text("text")
        note_lines = [l for l in text.splitlines()
                      if re.match(r"^\s*(備註|注|註|Notes?\b|附注|附註)", l.strip())]
        for l in note_lines[:5]:
            print(f"     note-line: {l.strip()[:90]}")
        # 3) 链接注释
        links = page.get_links()
        internal = [l for l in links if l.get("kind") in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED)]
        print(f"     links: total={len(links)} internal={len(internal)}")
    # 大纲/书签
    toc = doc.get_toc()
    if toc:
        print(f"  TOC entries={len(toc)} sample={toc[:5]}")

if __name__ == "__main__":
    files = sys.argv[1:]
    for f in files:
        try:
            probe(f)
        except Exception as e:
            print(f"  ERROR {f}: {e}")
