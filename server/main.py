# -*- coding: utf-8 -*-
"""FastAPI 入口（DESIGN.md §7 API 设计）。启动：uv run uvicorn server.main:app --port 8000"""
import os
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import cache, scanner
from .config import DEFAULT_CONFIG
from .pipeline import analyze_pdf

app = FastAPI(title="PDF Reference Reader", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges"],
)

DEFAULT_ROOT = os.environ.get("PDF_ROOT", "/home/zhangchi/Documents/insurance")


# ---------- helpers ----------

def _resolve(doc_id: str) -> str:
    path = cache.get_path(doc_id)
    if not path or not os.path.exists(path):
        raise HTTPException(404, f"文档未注册或文件不存在: {doc_id}")
    return path


def _mtime(path: str) -> float:
    return os.path.getmtime(path)


# ---------- API ----------

@app.get("/api/documents")
def documents(root: str = DEFAULT_ROOT):
    try:
        return {"root": os.path.abspath(root), "documents": scanner.scan(root)}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


class AnalyzeBody(BaseModel):
    path: str


@app.post("/api/analyze")
def analyze(body: AnalyzeBody):
    path = os.path.abspath(body.path)
    if not os.path.exists(path) or not path.lower().endswith(".pdf"):
        raise HTTPException(404, f"PDF 不存在: {path}")
    doc_id = scanner.doc_id(path)
    cache.register(doc_id, path)
    mtime = _mtime(path)
    cached = cache.load_analysis(doc_id, mtime)
    if cached:
        return {"docId": doc_id, "cached": True, "analysis": cached}
    try:
        analysis = analyze_pdf(path, doc_id, DEFAULT_CONFIG)
    except Exception as e:  # noqa: BLE001 —— 管线异常带阶段信息返回
        raise HTTPException(500, detail=f"pipeline error: {e}") from e
    data = analysis.model_dump()
    cache.save_analysis(doc_id, data)
    return {"docId": doc_id, "cached": False, "analysis": data}


@app.get("/api/analysis/{doc_id}")
def get_analysis(doc_id: str):
    path = _resolve(doc_id)
    cached = cache.load_analysis(doc_id, _mtime(path))
    if not cached:
        cached = analyze_pdf(path, doc_id, DEFAULT_CONFIG).model_dump()
        cache.save_analysis(doc_id, cached)
    return cache.apply_overrides(cached, cache.load_overrides(doc_id))


class FeedbackBody(BaseModel):
    docId: str
    hotspotId: str
    action: str                 # rebind | ignore
    targetNoteId: str | None = None
    targetDisplay: str | None = None


@app.post("/api/feedback")
def feedback(body: FeedbackBody):
    if body.action not in ("rebind", "ignore"):
        raise HTTPException(422, "action 须为 rebind|ignore")
    if body.action == "rebind" and not body.targetNoteId:
        raise HTTPException(422, "rebind 需要 targetNoteId")
    _resolve(body.docId)  # 确认文档存在
    cache.save_override(body.docId, body.hotspotId, body.model_dump(exclude={"docId"}))
    return {"ok": True}


@app.get("/api/pdf/{doc_id}")
def pdf(doc_id: str, request: Request):
    """PDF 二进制流，支持 Range（pdf.js 按需加载必需）。"""
    path = _resolve(doc_id)
    size = os.path.getsize(path)
    rng = request.headers.get("range")
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        start = int(m.group(1) or 0)
        end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        if start > end or start >= size:
            return Response(status_code=416,
                            headers={"Content-Range": f"bytes */{size}"})
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)
        return Response(data, status_code=206, media_type="application/pdf",
                        headers={"Content-Range": f"bytes {start}-{end}/{size}",
                                 "Accept-Ranges": "bytes"})
    return FileResponse(path, media_type="application/pdf",
                        headers={"Accept-Ranges": "bytes"})


@app.get("/api/config")
def get_config():
    return {k: getattr(DEFAULT_CONFIG, k) for k in (
        "size_ratio", "rise_ratio", "gap_ratio", "footer_zone")}


@app.get("/api/health")
def health():
    return {"ok": True}
