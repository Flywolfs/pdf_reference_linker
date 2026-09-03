# PDF 条款角标引用阅读器 — 开发设计文档

> 项目目录：`/home/zhangchi/Documents/pdf_reference_reader`
> 语料库：`/home/zhangchi/Documents/insurance/`（13 家香港保险公司，35 份 PDF）
> 版本：v1.0（2026-08-29）　状态：设计定稿，待开发
> 文档中所有"实测"结论均来自本仓库 `analysis/` 目录脚本的运行结果，可复现。

---

## 1. 背景与目标

### 1.1 问题

阅读保险 PDF（产品单张/小册子/条款/保费表）时，正文与表格中大量出现**右上角角标**（`1`、`2,3`、`*`、`⑴` 等），指向同页脚注、文末「備註」区或条款某节。人工阅读需要前后翻页对照，体验差、易迷失。

### 1.2 目标

构建一个**本地 PDF 阅读器**，加载 PDF 后自动完成：

1. **角标检测**：识别正文中所有引用型角标（含表格内角标）；
2. **注释解析**：定位角标指向的注释条目（脚注 / 文末備註区），建立 `角标 → 注释全文` 映射；
3. **悬浮提示**：鼠标悬停角标时弹出浮层，直接显示注释全文，可一键跳转原文位置。

### 1.3 非目标（当前版本）

- 不做云端服务、不做多人协作；
- 不做 PDF 编辑与批注持久化到原文件；
- 不追求解析全部文档排版（多栏杂志排、水印压字等极端场景列为降级路径）。

---

## 2. 语料实测画像（设计依据）

对 `insurance/` 下 35 份 PDF 用 `analysis/probe_pdf.py`、`analysis/probe_notes.py` 实测，得到以下形态学结论。**所有算法参数均以此为标定依据。**

### 2.1 引用端（角标）形态

| # | 形态 | 实测样例 | 特征数据 |
|---|------|---------|---------|
| A | 正文行内上标数字 | 「住院及手術費用…全數保障`1`」（FWD 倍衛您 p2） | 角标 span `sz=8.2`，正文 `sz=14.0`，基线升高 `dy=+4.7pt`（0.34×正文字号） |
| B | 表格单元格内角标 | 「扣稅優惠 `5`」（FWD p3） | 角标 span `' 5' sz=7.0`，正文 `'扣稅優惠' sz=12.0`，基线 `518 vs 522`（升高 4pt） |
| C | 表格粗体角标 | 保障表条目尾注（FWD p3） | `NotoSansCJKtc-Bold sz=7.0`（flags=21），可与正文混排 |
| D | 多角标逗号连写 | 「訂明診斷成像檢測`2,3`」（AIA p12-13） | 一个角标文本内含 `2,3` 两个引用编号 |
| E | 星号/字母 | 「`*` 指明親屬的定義…」（AIA p2/p4） | `sz=8.0` 独立 span |
| F | 带圈数字 | `①〜⑳`（部分单张） | 与正文同字号，靠字符本身识别 |

### 2.2 目标端（注释）形态

| # | 形态 | 实测样例 |
|---|------|---------|
| G | 文末独立「備註」区 | FWD 倍衛您 p16：标题「備註」+ 条目 `1. 全數保障是指…`、`5. 如您是香港納稅人…`；条目跨多行续排；存在编号行 `7.` 与正文首行**分属两个物理行**（需合并）的边界情况 |
| G' | 「註：」标题 + 集中编号条目区（与 G 本质相同，仅标题写法不同） | AIA 灵活计划 p15：独立标题行 `註：`（8pt）+ 条目 `1. 除另有說明外…` 至 `12. 共同保險為您須自費…`（多行续接）；**跨页被引用**——p12/p13 表格角标 `2`、`2,3`、`4` 及表头 `保障項目1,7`、`網絡保障8,10` 均指向此区 |
| H | 行内「註：」散布注释（无编号、**无角标触发**） | AIA p9「註：「AIA Vitality 健康程式」…」、p11「註：個案假設…」——就地说明，非角标目标，不参与匹配 |
| I | 表格小字号编号行 | 「重建手術保障`8`」「捐贈者保障`23`」——注释编号在表格条目后，目标在別處備註区 |
| J | 跨页续接条目 | 備註区条目从某页末尾延续到下页开头（暂定 M2 支持） |

### 2.3 PDF 原生设施

| 结论 | 证据 | 影响 |
|------|------|------|
| 条款类 PDF（Bowtie）已有完整 TOC + 内部链接 | 148 条书签；单页最多 32 个 `LINK_GOTO` | 检测到原生链接时**直接采用**，自研算法仅作补充 |
| 单张/小册子类（FWD、AIA）**无任何内部链接** | `links: total=0` | 自研角标-注释匹配是核心价值所在 |
| 保费表页文本密度极高 | AIA 保费表 p3：`8.0pt` span 达 **440 个** | **禁止使用全页字号统计**判定上标，必须做同行邻接对比 |

### 2.4 已知误报陷阱（必须排除）

| 陷阱 | 实测样例 | 排除手段 |
|------|---------|---------|
| 法规条文编号 | 「《稅務條例》(第112章)」中 `112` 为 `8.0pt`，与邻文同字号、基线无偏移（`dy=0`） | 字号比 + 基线偏移**双条件**联合判定 |
| 页码/footer | 页脚孤立数字行 | 角标必须有**同基线组的正文邻接 span**（紧贴性条件） |
| 表格数字列 | 保费表整列数字 | 紧贴性条件（与左侧正文水平间距 ≤ 0.6×正文字号） |
| 年龄/金额数字 | 「18」「8,000港元」 | 内容模式限制 + 双条件，数字本体与正文同字号不会被命中 |

---

## 3. 需求规格

### 3.1 功能需求（FR）

| ID | 需求 | 优先级 |
|----|------|--------|
| FR-1 | 打开本地 PDF 文件夹（默认 `insurance/`，可配置），列出全部文档并支持搜索 | P0 |
| FR-2 | Web 端渲染 PDF（连续滚动 + 单页双模式），支持缩放、页码跳转 | P0 |
| FR-3 | 自动解析并渲染角标热点：角标位置高亮（细下划线/淡底色），hover 弹出注释浮层 | P0 |
| FR-4 | 浮层显示：注释全文、来源定位（`P16 · 備註 5`）、「跳转原文」按钮 | P0 |
| FR-5 | 跳转后目标注释条目高亮 2s（脉冲动画） | P1 |
| FR-6 | 采用 PDF 原生内部链接（若存在），并在浮层标注「原生链接」 | P1 |
| FR-7 | 侧栏「引用总览」：全部角标-注释匹配对列表，点击互跳，支持人工校对（改绑/忽略），修正结果持久化 | P1 |
| FR-8 | 解析进度展示（SSE）；解析结果磁盘缓存，二次打开秒开 | P0 |
| FR-9 | 导出增强 PDF：注入 GOTO 链接 + 高亮注释，可在任意阅读器点击跳转 | P2 |
| FR-10 | 无文本层 PDF 检测与用户提示（扫描版降级） | P1 |

### 3.2 非功能需求（NFR）

| ID | 指标 |
|----|------|
| NFR-1 | ≤50 页 PDF 全量解析（角标检测+注释解析+匹配）≤ 2s |
| NFR-2 | hover 浮层出现延迟 ≤ 120ms（数据已预载，纯前端渲染） |
| NFR-3 | 纯本地运行，无外网依赖；繁体中文正确显示（系统字体栈） |
| NFR-4 | 角标检测在 3 份人工标注样本上查准率 ≥ 90%、查全率 ≥ 85%（含表格角标） |
| NFR-5 | 阈值参数集中可配（`config.py`），无需改代码即可调参 |

---

## 4. 总体架构

### 4.1 架构选型决策

**决策：本地 Web 应用 = FastAPI（Python 后端）+ PDF.js（前端渲染）+ 浏览器访问。**

| 候选 | 结论 | 理由 |
|------|------|------|
| FastAPI + PDF.js（选定） | ✅ | PyMuPDF 的 span 级结构提取（字号/基线/字体/flags）是目前最完整的开源实现；PDF.js 提供 `convertToViewportRectangle` 完成精确坐标换算；零安装分发，浏览器即用 |
| 纯前端（PDF.js getTextContent） | ❌ | PDF.js 文本层不保证返回稳定的逐 span 字号/基线结构，上标判定数据不足 |
| Tauri/Electron 桌面壳 | ❌（现阶段） | 增加 30%+ 工程量，无新能力；后期可用 Tauri 包装现有方案 |
| 注释注入原 PDF（Text/Popup annotation） | ❌（主路径） | 各阅读器对 Popup 呈现不一致；保留为 FR-9 增强导出（用 GOTO link + 高亮，不依赖 Popup） |

### 4.2 系统组成

```
┌──────────────────────────  浏览器（localhost:5173）──────────────────────────┐
│  React + pdfjs-dist                                                         │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────────────┐     │
│  │ 文档列表侧栏 │  │ PDF 画布          │  │ RefOverlay（每页一层）        │     │
│  │ (FR-1/FR-7) │  │ 连续滚动/单页      │  │  hotspot 命中区 + tooltip   │     │
│  └─────────────┘  └──────────────────┘  └────────────────────────────┘     │
└───────────────▲─────────────────────────────────────────▲───────────────────┘
                │ GET /api/pdf/{id} (Range)               │ GET /api/analysis/{id}
┌───────────────┴─────────────────────────────────────────┴───────────────────┐
│  FastAPI (uvicorn, localhost:8000)                                           │
│  ┌──────────┐  ┌──────────────────────────────────────────────────────┐     │
│  │ scanner  │  │ pipeline：extract → anchors → notes → match → schema  │     │
│  └──────────┘  └──────────────────────────────────────────────────────┘     │
│  cache：~/.cache/pdf_ref_reader/{sha1(path)}.json   overrides：校对结果      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 处理管线（一次解析，多处消费）

```
PDF 文件
  │ PyMuPDF page.get_text("dict")          [extract]
  ▼
Line/Span 结构图（字号、origin 基线、bbox、字体、flags）
  │ §5.1 角标检测（双条件+紧贴性）           [anchors]
  ├──────────────► hotspots[]（引用端）
  │ §5.2 注释区锚定 + §5.3 条目解析状态机    [notes]
  ├──────────────► notes[]（目标端）
  │ §5.4 匹配 + 置信度                      [match]
  ▼
AnalysisDoc JSON（数据契约见 §6）──► 磁盘缓存 ──► API
```

---

## 5. 核心算法设计

### 5.0 记号与约定

- 坐标系：PyMuPDF `rect`/`origin`，**左上原点，y 向下**，单位 pt。
- `line`：`dict.blocks[].lines[]`；`span`：`line.spans[]`，含 `text/size/origin/bbox/font/flags`。
- **基线组**：同一 `line` 内 origin.y 相差 ≤ 1pt 的 span 序列（PDF.js 跨设备渲染时换算到视口再判定，见 §5.5）。

### 5.1 角标检测（anchors）

对每个 `line` 的每个 `span s`：

```
ctx ← s 左侧最近、能通过候选排除的正文 span；若无则取右侧（限定在同一 line 内）
候选必要条件（全部满足）：
  C1 字号比      size_ratio = s.size / ctx.size ≤ 0.80        # 实测 8.2/14=0.59、7/12=0.58
  C2 基线升高    rise = ctx.origin.y − s.origin.y ≥ 0.22×ctx.size   # 实测 0.33~0.34，阈值留余量
  C3 内容模式    ^\d{1,3}([,，]\d{1,3})*$ ｜ ①-⑳ ｜ [*†‡§] ｜ ^[a-z]$
  C4 紧贴性      gap = s.bbox.x0 − ctx.bbox.x1 ≤ 0.6×ctx.size  且  ≥ −0.2×ctx.size
  C5 非孤立      ctx 存在（页码/独立单元格数字因无 ctx 被排除）
附加通道（并集）：
  C6 带圈数字    text ∈ ①-⑳ 且 位于正文行内（同字号，仅靠字符识别）
多编号拆分：`2,3` → 拆为两个 hotspot（共享 bbox，各自 target 查找）
输出：hotspots[] = {page, bbox, text, kind, contextBefore, confidence}
confidence 初始分：C1C2 双强(≤0.7 且 ≥0.3×size) 0.98；边界命中 0.85；仅 C6 0.75
```

**设计依据**：§2.4 陷阱案例 `112`（同字号 dy=0）被 C1/C2 联合排除；保费表 440 个 8pt span 因逐行局部对比 + C4/C5 不受全页统计干扰。

### 5.2 注释区锚定（notes – 定位）

三通道并集，命中任一即标记注释区：

| 通道 | 触发条件 | 实测对应 |
|------|---------|---------|
| T1 标题锚定 | 行文本匹配 `^(備註|附註|註釋|注釋|备注|備注|註|注|Notes?)\s*[:：]?$`（允许粗体/大字号），取该行下方同栏区域。**实测两种标题形态均命中**：FWD 的「備註」（大字标题）与 AIA 的「註：」（小字号独立标题行，后接编号条目） |
| T2 整页模式 | 一页内 ≥3 个 `^\d{1,3}[.、)]` 开头的小字号条目行，且小字号 span 占比 > 60% | 无标题的備註页兜底 |
| T4 页底悬挂脚注区 | 页底（y > 0.55×页高）≥2 个小字号罗马数字（`i~xxx`）或符号（`※*†‡§▲#♣^`）编号行（悬挂或同行），双栏按编号列 x0 聚类分栏 | AIA 单张页底「資料來源 i~viii」与增值服務 `※†*` 说明区；仅 T4 区域启用罗马/符号编号解析通道 |
| T3 行内註解 | 行首匹配 `^(註|注|備註|备注)\s*[:：]`（不独占行，无编号）。**注意**：此类注释（如 AIA p9/p11）实测无角标触发，属就地说明；解析存档但**不进入匹配候选**，仅当某 hotspot 无编号匹配时可作为上下文补充展示 |

区域边界：从锚点行到 (a) 页面底部 5% 边距，或 (b) 下一个非注释大字号标题，取先到者。

### 5.3 注释条目解析（notes – 状态机）

对注释区内按 (y, x) 排序的行序列：

```
状态：IDLE → IN_ITEM(no)
NEW_ITEM?   行首 span 匹配 ^(\d{1,3})[.、)]?\s 或整行恰为 ^\d{1,3}[.、)]$
              且首行 y 处基线组内后续正文与编号字号一致
CONT_LINE?  不匹配 NEW_ITEM 且 x0 与当前条目正文 x0 差 ≤ 2pt 且字号一致 → 续行追加
编号行孤立合并：整行仅为 "7." 时（实测 FWD p16），向后看一行，若其 x0 ≈ 条目正文缩进位
              （编号 x1 + 0.3~1.2×字符宽）→ 合并为条目首行
TERMINATE:  新条目 / 大字号标题 / 区域结束
跨页续接（M2）：下页顶部行若 x0 对齐且无 NEW_ITEM → 追加至上一文档级条目
输出：notes[] = {noteId:"p{n}:{num}", anchor: footer|standalone|inline, page, bbox,
                 number, text(多行合并，去换行连字), textPages}
```

### 5.4 引用-注释匹配（match）

```
对每个 hotspot 的编号 N：
  1) 收集候选 notes：number == N 的全部条目
  2) 打分（每 +1 累加）：
     +3 同页脚注（note.page == hotspot.page 且 anchor==footer）
     +3 文档级備註区唯一命中（全文档该编号仅一处）
     +2 阅读顺序合法（hotspot 线性位置 < note 线性位置）
     +1 目标区含 T1 标题锚定
     −2 编号越界（N > 该区域最大编号）
  3) top1 分数 − top2 分数 ≥ 2 → certain；否则 probable；无候选 → unresolved
  4) hotspot 带 PDF 原生 GOTO 链接时直接采纳（source=native, certain），
     同时仍跑自研匹配，若两者目标页一致则交叉验证通过并提升 confidence
输出：hotspot.targets[]、targetDisplay="P16 · 備註 5"、confidence、source=native|derived
```

`unresolved` 的 hotspot 照常渲染（视觉降级为灰），浮层显示「未找到编号 N」并提供全文搜索入口。

### 5.5 坐标换算（后端 → 前端）

- 后端统一输出 **PDF pt 坐标**（PyMuPDF 左上原点）。
- 前端 PDF.js：`page.getViewport({scale, rotation})` 后 `viewport.convertToViewportRectangle([x0,y0,x1,y1])`。
- 命中区（hit area）规则：角标 bbox 外扩 `pad = max(3px, 0.18×fontPx)`，且最终命中区 ≥ 14×14px（小字号角标 + 高分屏下的可用性保障）。

---

## 6. 数据契约（AnalysisDoc JSON Schema）

```jsonc
{
  "version": "1.0",
  "docId": "a1b2c3d4",                    // sha1(绝对路径) 前 8 位
  "meta": { "path": "...", "pages": 35, "title": "倍衛您醫療計劃", "hasTextLayer": true },
  "config": { "sizeRatio": 0.80, "riseRatio": 0.22, "gapRatio": 0.6 },  // 解析时参数快照
  "notes": [{
    "noteId": "p16:5", "anchor": "standalone",       // footer | standalone | inline
    "page": 16, "bbox": [43.2, 343.0, 552.0, 369.5],
    "number": "5", "text": "如您是香港納稅人…", "textPages": [16]
  }],
  "hotspots": [{
    "id": "h0007", "page": 3, "bbox": [233.1, 514.2, 240.0, 522.6],
    "text": "5", "kind": "numeric",                  // numeric | circled | asterisk | letter | numeric_list
    "contextBefore": "扣稅優惠",
    "targets": ["p16:5"],
    "targetDisplay": "P16 · 備註 5",
    "confidence": 0.98,                              // certain ≥0.95 > probable ≥0.7 > unresolved
    "source": "derived",                             // native | derived
    "nativeLink": null                               // {page, to} 当 source=native
  }]
}
```

磁盘缓存键：`~/.cache/pdf_ref_reader/{docId}.json`；`mtime` 变化自动失效。
校对覆盖：`~/.cache/pdf_ref_reader/overrides/{docId}.json`，格式 `{hotspotId: {action: rebind|ignore, targetNoteId?}}`，读取时叠加于分析结果之上。

---

## 7. API 设计（FastAPI，自动 OpenAPI）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/documents?root={dir}` | 扫描目录返回文档列表（名称/页数/是否已缓存） |
| POST | `/api/analyze` | body `{path}`；同步解析并返回 `docId`（NFR-1 保证 ≤2s；若后续需要可改 SSE） |
| GET | `/api/analysis/{docId}` | 返回 AnalysisDoc JSON（缓存命中直接读盘） |
| GET | `/api/pdf/{docId}` | PDF 二进制流，支持 `Range`（PDF.js 按需加载必需） |
| POST | `/api/feedback` | body `{docId, hotspotId, action, targetNoteId?}`；写 overrides |
| POST | `/api/export` | body `{docId}`；FR-9，返回增强 PDF 下载流 |
| GET | `/api/config` / PUT | 查看/修改解析阈值（写回后清缓存） |

错误约定：404 未注册文档；422 无文本层（`hasTextLayer=false`，前端引导提示）；500 管线异常带 `detail.stage` 字段。

---

## 8. 前端交互设计

### 8.1 布局

```
┌──────────┬──────────────────────────────────────┬─────────────┐
│ 文档列表  │  PDF 画布（连续滚动，可切单页）           │ 引用总览侧栏 │
│ 搜索/过滤 │  ┌────────────────────────────────┐   │ (FR-7,可折叠)│
│          │  │ page canvas + textLayer(off)    │   │ 匹配对列表   │
│          │  │ + RefOverlay(绝对定位层)          │   │ 置信度标记   │
│          │  └────────────────────────────────┘   │ 校对操作     │
└──────────┴──────────────────────────────────────┴─────────────┘
```

- `textLayer` 关闭（不需要原生文本选择；开启会与 overlay 事件冲突且占内存）。缩放/搜索走自研：`Ctrl+F` 搜索基于后端缓存的全文索引（M2）。

### 8.2 Hotspot 与 Tooltip（核心交互）

| 行为 | 规格 |
|------|------|
| 视觉 | 角标 bbox 外扩渲染 2px 圆角淡黄底（`rgba(255,196,0,.25)`），certain 纯色、probable 加虚线边、unresolved 灰色 |
| hover 进入 | 120ms 防抖后显示 tooltip（NFR-2） |
| tooltip 定位 | 首选角标下方 8px；下方视口空间 < 140px 则上翻；水平方向 clamp 在画布内；跨页滚动时随页平移（跟随当前视口重算） |
| tooltip 内容 | 头部：`P16 · 備註 5` + 置信度徽标（probable 显示"可能"）+ source=native 显示"原生链接"；正文：注释全文（`white-space: pre-wrap`，最高 40vh 内滚动）；底部：`跳转原文` 按钮 + `复制` |
| hover 离开 | 立即隐藏；tooltip 上 hover 可驻留（便于长文滚动） |
| 点击 hotspot | 滚动到注释条目并高亮 2s（脉冲） |
| 跳转目标 | notes bbox 落点 + 条目高亮框渲染在 RefOverlay |
| 键盘 | `Tab` 在 hotspot 间循环，`Enter` 显示/固定 tooltip，`Esc` 关闭 |

### 8.3 校对面板（FR-7）

列表项 = `[p3] 扣稅優惠⁵ → P16·備註5 (✓/?)`。`?` 项展开可：改绑到候选下拉（同编号全部 notes）/ 忽略。写入 overrides 后即时生效。

---

## 9. 项目结构

```
pdf_reference_reader/
├── docs/DESIGN.md                 # 本文档
├── analysis/                      # 调研脚本（已就绪，兼作回归工具）
│   ├── probe_pdf.py               #   角标/链接/字号分布探测
│   └── probe_notes.py             #   注释区形态与基线偏移探测
├── server/
│   ├── main.py                    # FastAPI 入口 + 路由
│   ├── config.py                  # 全部阈值参数（NFR-5）
│   ├── scanner.py                 # 目录扫描、docId 注册
│   ├── cache.py                   # 分析缓存 + overrides 读写
│   └── pipeline/
│       ├── schema.py              # §6 数据契约（pydantic 模型）
│       ├── extract.py             # line/span 结构图提取
│       ├── anchors.py             # §5.1 角标检测
│       ├── notes.py               # §5.2/5.3 注释区与条目
│       ├── match.py               # §5.4 匹配
│       └── export.py              # FR-9 增强 PDF 导出
├── web/                           # Vite + React 18 + TS + pdfjs-dist
│   └── src/
│       ├── viewer/                # PDFCanvas / PageView / RefOverlay / Tooltip
│       ├── sidebar/               # DocList / RefOverview
│       └── api.ts                 # 后端客户端
├── tests/
│   ├── golden/                    # 样本 PDF 的期望 JSON 快照
│   ├── samples.py                 # 人工标注集（3 份：FWD 单张、AIA 小册、Bowtie 条款）
│   └── test_pipeline.py           # pytest：陷阱用例(第112章) + 快照回归
├── pyproject.toml                 # uv 管理（已初始化，pymupdf 已装）
└── README.md
```

技术栈锁定：Python 3.12 + pymupdf 1.28 + fastapi + uvicorn；Node 24 + Vite 6 + React 18 + pdfjs-dist 4.x。均已有本地工具链（uv / node），无新增系统依赖。

---

## 10. 开发里程碑

| 里程碑 | 内容 | 验收标准 |
|--------|------|---------|
| **M1 核心闭环**（~1 周） | pipeline 四阶段 + schema + 缓存；`/api/analyze`、`/api/analysis`、`/api/pdf`；前端 PDF 渲染 + RefOverlay + tooltip | FWD 倍衛您、AIA 灵活计划两份样本：正文与表格角标 hover 显示正确注释全文，跳转可用 |
| **M2 覆盖与稳健**（~1 周） | 三通道注释锚定 + 编号行合并 + 多编号拆分 + 原生链接采纳；引用总览侧栏 + overrides 校对；35 份全量跑分；无文本层检测提示 | §2 全部 10 种形态（A-J）至少各 1 例正确；标注样本查准 ≥90%、查全 ≥85%（NFR-4）；35 份解析零崩溃 |
| **M3 增强**（~1 周） | 跨页条目续接；`Ctrl+F` 全文搜索；导出增强 PDF（GOTO link + 高亮）；参数面板 | 导出 PDF 在浏览器与系统阅读器中均可点击跳转；保费表类零误报 |

---

## 11. 测试方案

1. **陷阱单测**（必须常绿）：`《稅務條例》(第112章)` 不产出 hotspot；保费表页 hotspot 数为 0；页码不产出 hotspot。
2. **快照回归**：`tests/golden/{docId}.json` 与当前输出 diff，字段级对比（bbox 容差 0.5pt）。
3. **标注评测**：3 份人工标注样本（覆盖形态 A-J），脚本输出 P/R 报告进 CI 心智（本地 pytest 门槛断言 NFR-4）。
4. **端到端**：启动 `uvicorn` + `vite dev`，浏览器脚本模拟 hover 断言 tooltip 文本（M1 手工，M3 可选 Playwright）。

常用命令：

```bash
uv run pytest                          # 全部测试
uv run python analysis/probe_pdf.py <pdf>    # 单文件形态探测
uv run uvicorn server.main:app --port 8000   # 后端
cd web && npm run dev                        # 前端
```

---

## 12. 风险与降级路径

| 风险 | 影响 | 缓解/降级 |
|------|------|----------|
| 扫描版 PDF 无文本层 | 全管线失效 | `page.get_text` 空且图片覆盖率 >90% → `hasTextLayer=false`，前端提示；M3 预留 OCR 通道（tesseract 繁中） |
| 字体度量异常（基线不可靠） | 角标漏检 | C2 阈值进 `config.py`；校对面板允许手动补点（M3） |
| 双栏/多栏排版 | 行序错乱 → 阅读顺序打分失真 | 行排序按 (栏判定, y, x)；单张类 PDF 实测均为单栏/表格，风险集中在条款类——但条款类多已带原生链接，走 native 通道 |
| 编号复用（正文与表格各有一套 1-10） | 错配 | 匹配置信度降为 probable，靠校对面板人工改绑；不做猜測性自动改绑 |
| 繁简混排、全半角数字 | 模式漏匹配 | 正则使用繁简并集 + `０-９` 全角归一化预处理 |

---

## 13. 未来扩展（Backlog）

- 条款正文内的「詳見第 X 節」式文字引用识别（非角标）；
- 双语对照浮层（条款类 PDF 中英双语段落对齐）；
- 多文档横向对比视图（同一保障项目跨 13 家对比）；
- Tauri 桌面壳 + 文件关联双击打开。
