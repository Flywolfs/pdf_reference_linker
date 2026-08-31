# -*- coding: utf-8 -*-
"""数据契约：DESIGN.md §6 AnalysisDoc JSON Schema。"""
from typing import Optional

from pydantic import BaseModel, Field

ANALYSIS_VERSION = "1.1"          # schema 变更时 bump，缓存自动失效


class DocMeta(BaseModel):
    path: str
    pages: int
    title: str
    hasTextLayer: bool
    mtime: float = 0.0


class ConfigSnapshot(BaseModel):
    sizeRatio: float
    riseRatio: float
    gapRatio: float


class NoteEntry(BaseModel):
    noteId: str                       # p{page}:{number}
    anchor: str                       # footer | standalone | inline
    page: int                         # 0-based
    bbox: list[float]                 # PDF pt，左上原点
    number: str                       # inline 注释为 ""
    text: str
    textPages: list[int] = Field(default_factory=list)


class NativeLink(BaseModel):
    page: int
    y: float


class Hotspot(BaseModel):
    id: str
    page: int
    bbox: list[float]
    text: str                         # 单个编号
    kind: str                         # numeric | circled | asterisk | letter
    contextBefore: str = ""
    targets: list[str] = Field(default_factory=list)
    targetDisplay: Optional[str] = None
    confidence: float
    source: str = "derived"           # native | derived
    nativeLink: Optional[NativeLink] = None
    group: Optional[str] = None       # 同一多编号角标（如 '2,3'）共享的组 id


class AnalysisDoc(BaseModel):
    version: str = ANALYSIS_VERSION
    docId: str
    meta: DocMeta
    config: ConfigSnapshot
    notes: list[NoteEntry] = Field(default_factory=list)
    hotspots: list[Hotspot] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)   # 解析统计，调参用
