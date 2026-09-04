# 人工标注闭环与 AI 任务约定

阅读器的标注闭环（FR-7 扩展）让"人工判断 + AI 检索"分工协作：人只做对/错
判断与漏检框选，耗时耗力的"找到正确引用目标"交给 AI（Qoder 会话或任何
具备文档理解能力的 LLM）。

## 闭环流程

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 用户在「審核模式」下逐条判定：✓ 正確 / ✗ 錯誤（可换候选）      │
│    confirmed 的修正即时写入 overrides，阅读器立刻显示正确结果      │
│ 2. 无法即时判断的 → pending_ai；漏检的 → 補標框选                  │
├─────────────────────────────────────────────────────────────┤
│ 3. [導出AI任務] → 项目内 data/ai_tasks/{docId}.json │
├─────────────────────────────────────────────────────────────┤
│ 4. AI 处理任务文件（两种方式，schema 相同）：                      │
│    a. Qoder 会话：让助手读取任务文件，结合 PDF 内容逐项分析        │
│    b. 外部 LLM API：把任务文件 JSON 交给模型，要求按结果 schema 输出│
├─────────────────────────────────────────────────────────────┤
│ 5. [導入結果] 粘贴结果 JSON → 对应条目变为 ai_proposed             │
│ 6. 用户复审：接受 → confirmed（生效）；拒绝 → rejected             │
└─────────────────────────────────────────────────────────────┘
```

## 任务文件 schema（`data/ai_tasks/{docId}.json`）

```jsonc
{
  "docId": "0512e71b",
  "pdfPath": "/home/zhangchi/Documents/insurance/FWD/....pdf",
  "generatedAt": 1790000000,
  "notesIndex": [                       // 文档全部注释条目（候选池）
    {"noteId": "p15:1", "page": 15, "number": "1", "text": "（前 300 字）"}
  ],
  "tasks": [
    {
      "id": "h0014",                    // 回写时原样返回
      "kind": "wrong_link",             // 错链：当前指向错误
      "page": 2, "number": "3",         // 角标位置与编号
      "contextBefore": "…全數保障",      // 角标左侧正文
      "currentTargets": ["p15:3"],      // 当前（错误的）指向
      "hint": "用户判定当前链接错误，请从 notesIndex 中找出正确条目"
    },
    {
      "id": "m-ab12cd34",
      "kind": "missed_anchor",          // 漏检：用户框选的角标
      "page": 2, "number": "5", "bbox": [444.0, 505.0, 449.0, 525.0],
      "hint": "用户框选的漏检角标，请从 notesIndex 中找出对应条目"
    }
  ]
}
```

## 结果回写 schema

```jsonc
{
  "results": [
    {
      "id": "h0014",                    // 对应任务 id
      "targetNoteId": "p19:3",          // 找到的正确注释条目
      "method": "llm",                  // 可选：llm / fuzzy / rule
      "reason": "角标上下文为住院保障，对应 p19 不保事项第 3 条"  // 可选
    }
  ]
}
```

仅 `id` 与 `targetNoteId` 必填。导入后条目进入 `ai_proposed`，由用户复审。

## 给 LLM 的建议提示词

> 以下是保险 PDF 的角标引用标注任务。`notesIndex` 是该文档全部注释条目，
> `tasks` 中每项是一个角标（`number` 为编号，`contextBefore` 为左侧正文）。
> 请根据编号与上下文语义，从 notesIndex 中选出正确条目，按 results schema
> 输出 JSON。注意：同一编号可能出现在多个注释区（如「備註」与「不保事項」），
> 请依据上下文语义判断。

## 给 Qoder 会话的处理方式

直接对助手说：
> 处理 `data/ai_tasks/{docId}.json` 里的标注任务，
> 结合 PDF 原文分析，完成后生成结果文件 `ai_results/{docId}.json`

助手会读取 PDF（pdfPath）、核对每项任务的正确目标、写出结果 JSON，
然后您在界面 [導入結果] 粘贴该文件内容（或让助手直接调
`POST /api/annotate/import`）。

## 数据存放

标注类人工数据存**项目内 `data/`**（劳动成果，避免 `~/.cache` 被清理工具误删；可环境变量 `PDF_REF_DATA` 覆盖）；解析缓存（可再生）仍在 `~/.cache/pdf_ref_reader/`：

| 内容 | 路径 |
|------|------|
| 标注条目（verdict+miss 合一） | `<项目根>/data/annotations/{docId}.json` |
| AI 任务 | `<项目根>/data/ai_tasks/{docId}.json` |
| 生效修正（overrides） | `<项目根>/data/overrides/{docId}.json` |

## 条目状态机

```
verdict:  ✓ → confirmed（生效）
          ✗+候选 → confirmed + override（生效）
          ✗无候选 → pending_ai → (AI) → ai_proposed → 复审 → confirmed/rejected
miss:     框选 → 自动识别+匹配 → ai_proposed（有候选）/ pending_ai（无候选）
          → 复审 → confirmed（注入手工热点，生效）/ rejected
          任意状态可 ✕ 取消 → 删除记录（误框/重报后不想要了）
```

同一角标重复框选（识别中心距 ≤8pt）自动覆盖旧条目，不产生重复补标。

## 补标条目在阅读器中的可见性

- 待审补标（ai_proposed / pending_ai）：阅读器中以**紫色虚线框**显示在补标位置
  （spanBbox 优先，退化用框选 bbox）；点击右栏「補標條目」跳转并高亮。
- 确认后（confirmed）：注入为常规手工热点（source=manual），以正常角标样式
  显示、可悬浮/跳转，虚线框消失。
- 拒绝（rejected）与取消（删除）：不显示。

## 金标导出（引擎升级数据沉淀）

人工确认的记录即引擎升级的评测金标：verdict（对/错+换绑）与 miss（漏检+补标）
全量持久化于 `data/annotations/{docId}.json`（含页码/编号/位置/目标/时间戳）；
✗+换绑同时写 `data/overrides/{docId}.json` 运行时生效。

运行 `uv run python scripts/export_gold.py` 聚合全部确认记录 →
`data/gold/gold_set.jsonl`，三种 kind：

| kind | 含义 | 关键字段 |
|------|------|----------|
| `link_ok` | 引擎链接正确（人工 ✓） | engineTargets == finalTarget |
| `link_fix` | 引擎链接错误（人工 ✗+换绑） | engineTargets（引擎原判） vs finalTarget（rebindTo） |
| `miss_add` | 引擎漏检（人工补标） | engineTargets 为空，anchorBbox 为人工框定位置 |

引擎升级后可对比新输出与 finalTarget 计算准确率/召回提升。

## 引擎升级闭环（金标如何驱动升级）

引擎为规则/参数驱动（非模型训练），升级路径是「评测 → 归因 → 调整 → 防回退」：

1. **度量**：`uv run python scripts/eval_gold.py` 用当前引擎直接重跑金标所在文档
   （不走缓存），按 页码+编号+中心距 把金标锚点匹配到新热点，对比 finalTarget，
   输出 pass/wrong/missed 三态。missed = 检测/区域问题（角标没找到）；
   wrong = 匹配打分问题（找到了但连错）。
2. **归因调整**：missed 案例查检测阈值（config.py 的 size_ratio/rise_ratio/符号
   字符集/注释区锚定通道）；wrong 案例查匹配打分（match.py 的同页脚注/唯一编号/
   阅读顺序权重）。
3. **防回退**：调整后须 (a) eval_gold 通过率不降 (b) tests/test_gold.py 黄金快照
   有意变更后重新生成——两者分别度量"金标达标"与"全量输出稳定"。

样例：修复 T1 同栏终止后，showdoc P19 备註 3 恢复正确 bbox，即是 gold 思路
（人工发现坏框 → 归因 → 改 notes.py → 全语料 diff 审查）的一次人工执行；
今后同类改动可直接以 eval_gold.py 度量。

## 快照回归的关系

标注数据在缓存层（overrides / 手工热点注入）应用，**不改变管线输出**，
因此不会触发黄金快照（`tests/test_golden.py`）的 diff——两层机制互不干扰。
