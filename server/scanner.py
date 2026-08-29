# -*- coding: utf-8 -*-
"""文档目录扫描与 docId 注册（DESIGN.md §7）。"""
import hashlib
import os
from pathlib import Path


def doc_id(path: str) -> str:
    return hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:8]


def scan(root: str) -> list[dict]:
    """递归扫描 root 下的 PDF，返回文档列表（按相对路径排序）。"""
    root_p = Path(root).expanduser()
    if not root_p.is_dir():
        raise FileNotFoundError(f"目录不存在: {root}")
    out = []
    for p in sorted(root_p.rglob("*.pdf")):
        try:
            st = p.stat()
        except OSError:
            continue
        full = str(p.resolve())
        out.append({
            "name": p.stem,
            "relPath": str(p.relative_to(root_p)),
            "folder": str(p.parent.relative_to(root_p)),
            "path": full,
            "sizeKB": round(st.st_size / 1024),
            "docId": doc_id(full),
        })
    return out
