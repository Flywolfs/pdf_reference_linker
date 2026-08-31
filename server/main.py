# -*- coding: utf-8 -*-
"""FastAPI 入口（DESIGN.md §7 API 设计）。启动：uv run uvicorn server.main:app --port 8000"""
import os
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import annotations, cache, scanner
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
    return annotations.apply_manual(
        cache.apply_overrides(cached, cache.load_overrides(doc_id)), doc_id)


# ---------- 人工标注闭环（FR-7 扩展） ----------

@app.get("/api/annotations/{doc_id}")
def get_annotations(doc_id: str):
    _resolve(doc_id)
    return annotations.load_annotations(doc_id)


class VerdictBody(BaseModel):
    docId: str
    hotspotId: str
    correct: bool
    rebindTo: str | None = None


@app.post("/api/annotate/verdict")
def annotate_verdict(body: VerdictBody):
    path = _resolve(body.docId)
    entry = annotations.verdict(body.docId, body.hotspotId, body.correct, body.rebindTo)
    if entry["status"] == "confirmed" and not entry["correct"]:
        # 错链换候选 → 写 override（生成友好 display），阅读器即时生效
        analysis = cache.load_analysis(body.docId, _mtime(path))
        disp = None
        if analysis:
            from .pipeline.match import ANCHOR_LABEL
            n = next((n for n in analysis["notes"] if n["noteId"] == body.rebindTo), None)
            if n:
                disp = f"P{n['page'] + 1} · {ANCHOR_LABEL.get(n['anchor'], n['anchor'])} {n['number']}"
        cache.save_override(body.docId, body.hotspotId,
                            {"action": "rebind", "targetNoteId": body.rebindTo,
                             "targetDisplay": disp})
    if entry["status"] == "confirmed" and entry["correct"]:
        # 改判正确 → 清除旧覆盖
        cache.delete_override(body.docId, body.hotspotId)
    return {"ok": True, "entry": entry}


class MissBody(BaseModel):
    docId: str
    page: int
    bbox: list[float]           # PDF pt、左上原点


@app.post("/api/annotate/miss")
def annotate_miss(body: MissBody):
    path = _resolve(body.docId)
    analysis = cache.load_analysis(body.docId, _mtime(path))
    if not analysis:
        analysis = analyze_pdf(path, body.docId, DEFAULT_CONFIG).model_dump()
        cache.save_analysis(body.docId, analysis)
    proposal = annotations.identify_miss(path, body.page, body.bbox, analysis, DEFAULT_CONFIG)
    entry_id, entry = annotations.add_miss(body.docId, body.page, body.bbox, proposal)
    return {"entryId": entry_id, "entry": entry}


class ReviewBody(BaseModel):
    docId: str
    entryId: str
    accept: bool
    rebindTo: str | None = None


@app.post("/api/annotate/review")
def annotate_review(body: ReviewBody):
    _resolve(body.docId)
    entry = annotations.review(body.docId, body.entryId, body.accept, body.rebindTo)
    if entry is None:
        raise HTTPException(404, f"标注条目不存在: {body.entryId}")
    return {"ok": True, "entry": entry}


class DocBody(BaseModel):
    docId: str


@app.post("/api/annotate/export")
def annotate_export(body: DocBody):
    path = _resolve(body.docId)
    analysis = cache.load_analysis(body.docId, _mtime(path))
    if not analysis:
        analysis = analyze_pdf(path, body.docId, DEFAULT_CONFIG).model_dump()
        cache.save_analysis(body.docId, analysis)
    file, n = annotations.export_tasks(body.docId, path, analysis)
    return {"ok": True, "file": file, "taskCount": n}


class ImportBody(BaseModel):
    docId: str
    results: dict               # {"results": [{id, targetNoteId, method?, reason?}]}


@app.post("/api/annotate/import")
def annotate_import(body: ImportBody):
    _resolve(body.docId)
    n = annotations.import_results(body.docId, body.results)
    return {"ok": True, "imported": n}


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
