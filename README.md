# PDF 條款角標引用閱讀器（pdf-reference-reader）

面向香港保险 PDF（产品单张 / 小册子 / 条款 / 保费表）的本地阅读器：自动检测正文中
的引用角标（`1`、`2,3`、`*`、`①`、字体自定义符号等），解析其指向的注释条目
（文末「備註」区、页底脚注），hover 直接显示注释全文并支持一键跳转；配套人工校对、
AI 辅助标注与金标准回归评测闭环。

- 语料库：`/home/zhangchi/Documents/insurance/`（13 家保险公司，35 份 PDF）
- 解析引擎版本：**v1.12**（就近向下匹配规则）
- 详细设计文档：[docs/DESIGN.md](docs/DESIGN.md)（算法依据全部来自实测，可复现）
- 标注数据沉淀规范：[docs/ANNOTATION.md](docs/ANNOTATION.md)

---

## 1. 功能特性

| 类别 | 能力 |
|------|------|
| 角标检测 | 行内上标数字、表格单元格角标（含粗体）、逗号多编号 `2,3` 拆分、带圈数字 `①-⑳`、星号/字母符号、PUA 私用区自定义字体符号（U+E000–F8FF）、可配置扩展符号集 |
| 注释解析 | T1 标题锚定（備註/註：）、T2 整页编号条目模式、T4 页底悬挂脚注区（罗马数字 `i~xxx` / 符号编号，双栏聚类）、编号行孤立合并、行内「註：」存档不参与匹配 |
| 引用匹配 | 自研打分匹配 + PDF 原生 GOTO 链接直接采纳（交叉验证）；v1.12 就近向下原则 |
| 阅读体验 | PDF.js 连续滚动渲染、hover 浮层显示注释全文、跳转高亮脉冲、引用总览侧栏互跳 |
| 人工校对 | 逐条 ✓/✗ 审核、换绑目标、补标漏检（框选识别）、审核面板 accept/reject、取消引用/恢复（墓碑机制）、**确认即锁定**（已确认链接不随后续引擎升级漂移） |
| AI 辅助 | 导出 AI 任务包（含页面截图线索与页码提示）→ 外部 LLM 处理 → 导入结果自动建条目 |
| 数据沉淀 | 金标准导出（gold + reference 双文件）、gold_set.jsonl 聚合、金标回归评测、解析漂移对比 |
| 工程化 | 解析结果磁盘缓存（版本号自动失效，二次打开秒开）、黄金快照回归（35 份全量输出冻结）、阈值参数集中可配 |

---

## 2. 架构体系

### 2.1 总体架构

```
┌────────────────────  浏览器（Vite dev: 5173）────────────────────┐
│  React 18 + TypeScript + pdfjs-dist 4.x                          │
│  ┌────────────┐  ┌──────────────────┐  ┌─────────────────────┐  │
│  │ 文档列表侧栏 │  │ PDF 画布（连续滚动）│  │ 引用总览/审核面板     │  │
│  └────────────┘  └──────────────────┘  └─────────────────────┘  │
└────────▲───────────────────────────────────▲────────────────────┘
         │ GET /api/pdf/{id} (Range 流式)     │ GET /api/analysis/{id} 等
┌────────┴───────────────────────────────────┴────────────────────┐
│  FastAPI（uvicorn，127.0.0.1:8000）                               │
│  ┌─────────┐  ┌────────────────────────────────────────────┐    │
│  │ scanner │  │ pipeline：extract → anchors → notes → match │    │
│  └─────────┘  └────────────────────────────────────────────┘    │
│  annotations：人工标注/AI 任务/金标导出                            │
└─────────────────────────────────────────────────────────────────┘
  缓存 ~/.cache/pdf_ref_reader/        数据 data/（.gitignore，留本地）
```

### 2.2 目录结构

```
pdf_reference_reader/
├── server/                        # FastAPI 后端
│   ├── main.py                    # 入口 + 全部路由（约 22 个端点）
│   ├── config.py                  # 解析阈值参数（NFR-5：集中可配）
│   ├── scanner.py                 # 语料目录扫描、docId（sha1 前 8 位）
│   ├── cache.py                   # 解析缓存 + 数据目录
│   ├── annotations.py             # 人工标注闭环（verdict/补标/审核/墓碑/金标导出）
│   └── pipeline/
│       ├── schema.py              # 数据契约（pydantic，ANALYSIS_VERSION）
│       ├── extract.py             # line/span 结构图（字号/基线/flags）
│       ├── anchors.py             # 角标检测
│       ├── notes.py               # 注释区锚定 + 条目解析状态机
│       └── match.py               # 引用-注释匹配（v1.12 就近向下）
├── web/                           # Vite + React 18 + TS 前端
│   └── src/
│       ├── App.tsx                # 主界面（文档列表/画布/审核区三栏）
│       ├── api.ts                 # 后端客户端
│       ├── pdfjs.ts               # pdfjs-dist worker 配置
│       └── viewer/                # PdfViewer / PageView（热点叠加层）
├── tests/
│   ├── golden/                    # 35 份语料的引擎输出黄金快照
│   ├── test_pipeline.py           # 管线测试（陷阱用例 + 真实样本）
│   ├── test_annotations.py        # 标注闭环测试
│   └── test_golden.py             # 黄金快照字段级回归
├── scripts/
│   ├── gen_golden.py              # 生成/重生成黄金快照
│   ├── export_gold.py             # 聚合导出 gold_set.jsonl
│   ├── eval_gold.py               # 金标回归评测（P/R 度量）
│   └── compare_gold.py            # 解析漂移对比（金标 vs 当前输出）
├── analysis/                      # 调研脚本（probe_pdf / probe_notes，兼作回归工具）
├── data/                          # 运行时数据（不入库）：annotations/ gold/ ai_tasks/ config/ overrides/
└── docs/                          # DESIGN.md（设计）、ANNOTATION.md（数据沉淀）
```

### 2.3 技术栈

| 层 | 选型 | 关键理由 |
|----|------|---------|
| 后端 | Python 3.12 + FastAPI + uvicorn + PyMuPDF 1.28 | PyMuPDF 的 span 级结构（字号/基线/字体 flags）是上标判定的数据基础 |
| 前端 | Vite 6 + React 18 + TypeScript + pdfjs-dist 4.10 | `convertToViewportRectangle` 完成精确坐标换算；零安装分发 |
| 包管理 | uv（Python）/ npm（前端） | 本地工具链已就绪，无新增系统依赖 |

---

## 3. 核心方法逻辑

### 3.1 解析管线（一次解析，多处消费）

```
PDF ─ PyMuPDF get_text("dict") ─► Line/Span 结构图
        │ §3.1.1 角标检测（anchors）    ─► hotspots[]
        │ §3.1.2/3.1.3 注释解析（notes） ─► notes[]
        │ §3.1.4 匹配（match）          ─► targets[]/confidence
        ▼
   AnalysisDoc JSON（v1.12）──► 磁盘缓存 ──► API
```

#### 3.1.1 角标检测（anchors）

对每个 line 的每个 span 做双条件 + 紧贴性联合判定，避免全页字号统计在保费表页（单页 440 个 8pt span）失效：

- **C1 字号比**：角标字号 / 左侧正文 ≤ 0.80（实测 0.58~0.72）
- **C2 基线升高**：正文 origin.y − 角标 origin.y ≥ 0.22 × 正文字号（上标特征）
- **C3 内容模式**：`^\d{1,3}([,，]\d{1,3})*$`、`①-⑳`、`[*†‡§]` 等（含 PUA 范围 U+E000–F8FF 与用户扩展符号）
- **C4 紧贴性**：与正文水平间距 ≤ 0.6 × 正文字号
- **C5 非孤立**：必须有正文邻接（排除页码、独立数字列）
- **C7 同字号逗号多编号**：AIA 表头 `1,7` 形态（基线无偏移但逗号连写），单独置信度通道

已知陷阱排除：《稅務條例》(第112章) 中 `112` 同字号且基线无偏移，被 C1+C2 联合排除；
多编号 `2,3` 拆为共享 bbox 的两个 hotspot 各自匹配。

#### 3.1.2 注释区锚定（notes – 定位）

三通道并集：

| 通道 | 触发条件 | 典型场景 |
|------|---------|---------|
| T1 标题锚定 | 行文本 `^(備註|附註|註釋|备注|註|注|Notes?)\s*[:：]?$` | 文末独立「備註」区、「註：」+ 编号条目区 |
| T2 整页模式 | ≥3 个 `^\d{1,3}[.、)]` 小字号条目行（字号比/跨度阈值过滤表格页） | 无标题的備註页 |
| T4 页底悬挂 | 页底 y > 0.55×页高，≥2 个罗马数字/符号编号行，且距内容底端 ≤100pt（防表格列表项误判） | 页底「資料來源 i~viii」、`※†*★♠` 说明区 |

T3 行内「註：」散布注释解析存档但不参与匹配（实测无角标触发，属就地说明）。

#### 3.1.3 条目解析（notes – 状态机）

对注释区内按 (y, x) 排序的行序列跑 `IDLE → IN_ITEM(no)` 状态机：编号行
`^\d{1,3}[.、)]` 开新条目；x0 对齐且字号一致追加续行；整行仅 `7.` 的孤立编号行
向后合并首行正文；大字号标题或区域结束终止。

#### 3.1.4 引用-注释匹配（match，v1.12 就近向下原则）

对每个 hotspot 的编号 N 收集同编号候选条目，累加打分——**同一编号脚注常跨页重复
以便查阅，用户视角「向下最近」的解释才是该看的**：

| 加分 | 条件 |
|------|------|
| +5 / +4 | 同页锚点**下方**的 footer 脚注 / standalone 备注（首选） |
| +1 | 同页但锚点上方（罕见，违背向下原则） |
| +2 / +1 / 0 | 后续页，越近越高（页距 ≥3 归零） |
| −4 | 更早页（仅无任何向下候选时兜底） |
| +3 | 文档级備註区唯一命中 |
| +1 | 目标区含 T1 标题锚定 |
| −2 | 编号越界（N > 区域最大编号） |

top1 − top2 ≥ 2 → `certain`（0.98），否则 `probable`（0.75），无候选 → `unresolved`。
hotspot 带 PDF 原生 GOTO 链接时直接采纳（`source=native`），自研匹配同时运行作交叉验证。

### 3.2 人工标注与数据闭环

UI 审核区（右侧栏）围绕每个热点构建闭环，全部持久化到 `data/annotations/{docId}.json`：

- **verdict（✓/✗）**：判定引擎链接是否正确；✗ 时换绑到正确目标
- **确认即锁定（pin）**：点 ✓ 时把当前显示目标写入 override，引擎重解析/规则调整后
  已确认链接不再漂移（✓ 不删除 override）
- **补标漏检**：框选 PDF 区域 → `identify_miss` 按 anchor token/span 成员匹配回引擎
  热点；同 ID 重复框选复用条目
- **墓碑机制**：取消引用生成 `x-{id}` 墓碑；重新框选复用同 ID 且 ts 更新 → 墓碑自动
  失效（引用恢复）；引擎热点的墓碑始终有效
- **三层目标优先级**：pin override > verdict 换绑（v-{eid}）> miss 条目换绑 > 引擎 top1；
  verdict 换绑时同步 miss 条目（sync_miss_target）保证两处显示一致
- **review 面板**：补标条目 accept/reject；reject 即取消（墓碑）

### 3.3 AI 辅助标注闭环

`POST /api/annotate/export` 导出 AI 任务包到 `data/ai_tasks/{docId}.json`（含热点
候选、截图线索、用户页码提示），外部 LLM 处理后 `POST /api/annotate/import` 导入
结果自动建补标条目；历史归档在 `data/ai_tasks/history/`（时间戳保序）。

### 3.4 金标准体系（三层）

| 层 | 内容 | 用途 |
|----|------|------|
| **gold**（`data/gold/{docId}.gold.json`） | 一个 ID 一条：`link_ok`（引擎检出+判对）/ `link_fix`（判错换绑）/ `miss_add`（漏检补标） | 计算 accuracy，防重复计分 |
| **reference**（`data/gold/{docId}.reference.json`） | verdict + miss 全量明细（含重叠 ID、engineTargets、correct、rebindTo、ts） | 诊断某 ID 是「系统判错」还是「根本漏检」 |
| **黄金快照**（`tests/golden/{docId}.json`，入库） | 35 份语料引擎全部输出冻结 | 字段级 diff 防解析回归；只判断「变化是否符合规则」，规则对不对靠金标兜底 |

UI「導出金標」按钮一键生成 gold + reference 双文件；`scripts/compare_gold.py` 对比
金标与当前系统输出，输出 OK/DRIFT/GONE/REVIVED 清单。

### 3.5 数据存储

| 路径 | 内容 |
|------|------|
| `~/.cache/pdf_ref_reader/{docId}.json` | 解析缓存（带 ANALYSIS_VERSION，版本不符自动重算） |
| `data/annotations/{docId}.json` | 人工标注记录（verdict/miss/墓碑/override） |
| `data/ai_tasks/{docId}.json`（+ `history/`） | AI 任务与历史归档 |
| `data/gold/` | 金标 / reference / gold_set.jsonl |
| `data/config/symbols.json` | 用户扩展角标符号集 |
| `data/overrides/` | 手动改绑记录 |

`data/` 整体在 `.gitignore` 中（人工标注劳动成果留本地，如需 git 备份可删除该行）。

---

## 4. 部署与运行

### 4.1 环境要求

- Python ≥ 3.12 + [uv](https://docs.astral.sh/uv/)
- Node ≥ 20（本地 24）+ npm
- 语料库：默认 `/home/zhangchi/Documents/insurance/`（可用环境变量 `PDF_ROOT` 覆盖）

### 4.2 安装

```bash
# 后端依赖（uv 自动创建 .venv）
uv sync

# 前端依赖
cd web && npm install
```

### 4.3 启动

```bash
# 后端（终端 1）
uv run uvicorn server.main:app --host 127.0.0.1 --port 8000

# 前端（终端 2）
cd web && npm run dev        # http://localhost:5173
```

生产构建：`cd web && npm run build`（产物 `web/dist/`，可由任意静态服务器托管，
API 地址见 `web/src/api.ts`）。

健康检查：`curl http://127.0.0.1:8000/api/health`。

### 4.4 主要 API

| 分组 | 端点 |
|------|------|
| 文档 | `GET /api/documents`、`POST /api/analyze`、`GET /api/analysis/{doc_id}`、`GET /api/pdf/{doc_id}`（Range 流式） |
| 标注 | `GET /api/annotations/{doc_id}`、`POST /api/annotate/verdict`、`POST /api/annotate/miss`、`DELETE /api/annotate/miss/{doc_id}/{entry_id}`、`POST /api/annotate/review`、`POST /api/annotate/cancel`、`POST /api/annotate/restore` |
| AI 任务 | `POST /api/annotate/export`（导出任务包）、`POST /api/annotate/import`（导入结果）、`POST /api/feedback` |
| 金标 | `POST /api/gold/export`（gold + reference 双文件）、`GET /api/gold/last-export/{doc_id}`、`POST /api/annotate/export` + `GET /api/annotate/last-export/{doc_id}` |
| 配置 | `GET /api/config`、`GET/POST /api/config/symbols`（扩展符号增删） |

完整交互文档：后端启动后访问 `http://127.0.0.1:8000/docs`（FastAPI 自动 OpenAPI）。

### 4.5 参数调优

所有解析阈值集中在 [server/config.py](server/config.py)（字号比、基线升高比、T2/T4
阈值、正则模式等），改代码无需改逻辑即可调参；`ANALYSIS_VERSION`（schema.py）bump
后全部缓存自动失效重算。

---

## 5. 测试方法

```bash
uv run pytest                        # 全部测试（51 项）
```

| 测试层 | 内容 | 命令 |
|--------|------|------|
| 管线测试 | 陷阱用例（`(第112章)` 不产热点、保费表页零误报、页码排除）+ FWD/AIA 真实样本断言 | `uv run pytest tests/test_pipeline.py` |
| 标注闭环 | verdict/补标/墓碑/金标导出单元测试 | `uv run pytest tests/test_annotations.py` |
| 黄金快照回归 | 35 份语料引擎全输出 vs `tests/golden/` 字段级 diff（bbox 容差 0.5pt；elapsedMs/mtime 不参与） | `uv run pytest tests/test_golden.py` |

黄金快照工作流：管线改动 → 快照测试失败并给出字段级 diff → 归因分析（有意变更 vs
意外破坏）→ 确认有意后 `uv run python scripts/gen_golden.py` 重生成 → 审查 diff →
提交锁定。

### 5.1 金标回归评测（引擎升级度量）

```bash
uv run python scripts/export_gold.py      # 聚合 data/annotations → data/gold/gold_set.jsonl
uv run python scripts/eval_gold.py        # 当前引擎重跑逐条对比 finalTarget
                                          #   pass / wrong（打分问题）/ missed（检测问题）
uv run python scripts/eval_gold.py --kind miss_add   # 只看漏检类
```

升级工作流：改参数/规则 → `eval_gold.py` 无回退且通过率上升 → `gen_golden.py` → 提交。

### 5.2 解析漂移对比（改完必做）

用户在 UI 确认的金标是唯一正确答案，每次引擎修改后：

```bash
uv run python scripts/compare_gold.py a9d21f52   # 金标 vs 当前缓存+composite
                                                 # 输出 OK / DRIFT / GONE / REVIVED 清单
```

### 5.3 端到端手工验证

启动前后端后浏览器验证：hover 浮层文本、跳转高亮、审核区操作、补标框选、金标导出。

---

## 6. 里程碑

### 6.1 设计里程碑（DESIGN.md §10）

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| **M1 核心闭环** | pipeline 四阶段 + schema + 缓存；PDF 渲染 + 热点叠加 + hover tooltip + 跳转 | ✅ 完成 |
| **M2 覆盖与稳健** | 三通道注释锚定（+T4 扩展为四通道）、编号行合并、多编号拆分、原生链接采纳、引用总览 + overrides 校对、35 份全量解析、无文本层检测 | ✅ 完成 |
| **M3 增强** | 跨页条目续接（J 形态）、`Ctrl+F` 全文搜索、FR-9 导出增强 PDF（GOTO link + 高亮）、参数面板 | ❌ 未开始 |

### 6.2 设计外扩展（已完成）

| 能力 | 说明 |
|------|------|
| 人工标注审核闭环 | verdict ✓/✗+换绑、补标漏检框选、review accept/reject、取消/恢复墓碑、**确认即锁定 pin**（v1.12） |
| AI 辅助标注闭环 | AI 任务导出/导入、历史归档、用户页码提示 |
| 金标准体系 | UI 一键导出 gold（一 ID 一条）+ reference（诊断明细）、gold_set.jsonl 聚合、eval_gold 评测、compare_gold 漂移对比 |
| 黄金快照回归 | 35 份全量输出冻结 + pytest 字段级 diff |
| 引擎专项修复 | T4 单符号脚注区放宽（底部边距 ≤100pt）、PUA 私用区字符识别、同字号逗号多编号、扩展符号配置面板 |
| 匹配规则演进 | v1.12 就近向下原则（同编号跨页重复时链到锚点下方最近解释，废除向上链接） |

### 6.3 Backlog（DESIGN.md §13）

- 条款正文「詳見第 X 節」式文字引用识别（非角标）
- 双语对照浮层、多文档横向对比视图、Tauri 桌面壳
- OCR 通道（扫描版 PDF，tesseract 繁中）

---

## 7. 开发流程（Git flow）

自 2026-09 起采用标准 Git flow：

| 分支 | 来源 | 用途 | 去向 |
|------|------|------|------|
| `main` | — | **只放生产代码**，每次发布打 tag | — |
| `develop` | main | 日常开发主线 | 发布时合回 main |
| `feature/*` | develop | 单个功能开发 | 合回 develop |
| `release/*` | develop | 发布前准备，**只做 bugfix** | 同时合回 main（打 tag）和 develop |
| `hotfix/*` | main | 生产紧急修复 | 同时合回 main（打 tag）和 develop |

当前基准：`main` = `develop` = v1.12（11091db）。tag 只打在 main 上。

---

## 8. 相关文档

- [docs/DESIGN.md](docs/DESIGN.md) — 完整设计：语料实测画像、算法标定依据、数据契约、API、风险降级
- [docs/ANNOTATION.md](docs/ANNOTATION.md) — 标注数据沉淀规范
