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
```

## 快照回归的关系

标注数据在缓存层（overrides / 手工热点注入）应用，**不改变管线输出**，
因此不会触发黄金快照（`tests/test_golden.py`）的 diff——两层机制互不干扰。
