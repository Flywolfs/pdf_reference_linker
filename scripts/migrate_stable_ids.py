# -*- coding: utf-8 -*-
"""一次性迁移：seq 序号热点 id（h0001…）→ 内容寻址 id（1.14 hotspot_stable_id）。

背景：引擎热点 id 原为检出序列号，1.13 C8/T5 新增热点后整体偏移，存量人工
标注（verdict v-hXXX、墓碑 x-hXXX、override 键）跨版本全部错位（實測事故：
a9d21f52 的 44 條 verdict 錯位）。本腳本以 tests/golden/{docId}.json（1.12
快照，含全部引擎熱點的 id→(page,text,bbox) 表）為橋，把舊 id 重寫為新 id。

映射規則：舊 id → golden 查 (page,text,bbox) → 新解析結果中按內容匹配
（頁碼+編號+中心距 ≤3pt）→ 新 id。 golden 中不存在（m- 補標注,id 自帶 uuid）
或已遷移（內容匹配失敗）的條目保持原樣並報告。

用法：uv run python scripts/migrate_stable_ids.py   （冪等，可重複運行）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import annotations  # noqa: E402
from server.cache import OVERRIDE_DIR  # noqa: E402
from server.pipeline import analyze_pdf  # noqa: E402
from server.scanner import scan  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def main() -> None:
    docs = {d["docId"]: d for d in scan("/home/zhangchi/Documents/insurance")}
    for anno_f in sorted(annotations.ANNO_DIR.glob("*.json")):
        doc_id = anno_f.stem
        golden_f = GOLDEN / f"{doc_id}.json"
        if not golden_f.exists():
            print(f"!! {doc_id}: 無 golden 快照，跳過（無舊 id 表）")
            continue
        old_hs = {h["id"]: h for h in json.loads(golden_f.read_text())["hotspots"]}
        if not any(eid[2:].startswith("h") for eid in
                   json.loads(anno_f.read_text())["entries"]):
            print(f"   {doc_id}: 無引擎熱點引用，跳過")
            continue

        info = docs.get(doc_id)
        a = analyze_pdf(info["path"], doc_id).model_dump()

        # 新熱點內容索引：跨版本 bbox 由同一 span 檢出，中心距應 <1pt；
        # 放寬 3pt 容忍引擎幾何微調
        def new_id(old_hid: str) -> str | None:
            h = old_hs.get(old_hid)
            if not h:
                return None
            c = _center(h["bbox"])
            for x in a["hotspots"]:
                if x["page"] == h["page"] and x["text"] == h["text"]:
                    xc = _center(x["bbox"])
                    if max(abs(xc[0] - c[0]), abs(xc[1] - c[1])) <= 3.0:
                        return x["id"]
            return None

        data = json.loads(anno_f.read_text())
        mapping: dict[str, str] = {}
        missing = []
        for eid in list(data["entries"]):
            base = eid[2:] if eid.startswith(("v-", "x-")) else eid
            if not base.startswith("h"):
                continue                       # m- 補標 / 其他：id 自帶 uuid
            nid = new_id(base)
            if nid is None:
                missing.append(base)
                continue
            mapping[base] = nid
            if nid == base:
                continue
            e = data["entries"].pop(eid)
            data["entries"][eid[:2] + nid] = e
        # override 鍵同步
        ov_f = OVERRIDE_DIR / f"{doc_id}.json"
        if ov_f.exists():
            ov = json.loads(ov_f.read_text())
            new_ov = {}
            for k, v in ov.items():
                new_ov[mapping.get(k, k)] = v
            ov_f.write_text(json.dumps(new_ov, ensure_ascii=False, indent=1))
        annotations.save_annotations(doc_id, data)
        print(f"   {doc_id}: 遷移 {len(mapping)} 個 id 引用"
              + (f"；未匹配 {len(missing)}: {missing[:5]}" if missing else ""))
    print("完成。")


if __name__ == "__main__":
    main()
