#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 2 — 章節拆分。

優先序（由可靠到不可靠，逐層 fallback）：
    1. EPUB / PDF 有書籤：用 toc.json 的 level 1–2 節點切
    2. PDF 無書籤：正規式掃描章節標題行 + 啟發式過濾
    3. 都失敗：依字數均分（會大聲警告）

輸出：work/02_chapters/chNN_章節名.md，開頭寫 YAML front-matter。

驗收點：印出章節清單表格。字數異常（< 500 或 > 全書 25%）標紅，代表拆錯了。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    CHAPTERS, PAGES_JSONL, TOC_JSON, _c, die, ensure_dirs, fail, info, ok,
    read_json, read_jsonl, safe_filename, step, warn,
)

# 規劃書 §4.2 的章節標題正規式
CH_PATTERNS = [
    r'^\s*第\s*[0-9一二三四五六七八九十百]+\s*[章節課篇回講]',
    r'^\s*Chapter\s+\d+',
    r'^\s*CHAPTER\s+\d+',
    r'^\s*\d{1,2}\s*[\.、]\s*\S{2,30}$',
    r'^\s*(前言|序言|自序|推薦序|導論|導讀|緒論|結語|結論|後記|跋|附錄|參考文獻|致謝)\s*$',
]
CH_RE = [re.compile(p) for p in CH_PATTERNS]

MIN_WORDS = 500          # 低於此字數視為拆錯
MAX_SHARE = 0.25         # 超過全書 25% 視為拆錯
HEADING_MAX_CHARS = 40   # 啟發式：候選標題行字數上限


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 2：章節拆分")
    ap.add_argument("--min-chapters", type=int, default=3, help="低於這個章數視為拆章失敗")
    ap.add_argument("--force-regex", action="store_true", help="忽略書籤，強制用正規式掃描")
    ap.add_argument("--force-split", type=int, default=0, help="最後手段：強制均分成 N 章")
    args = ap.parse_args()

    ensure_dirs()
    if not PAGES_JSONL.exists():
        die(f"找不到 {PAGES_JSONL}，請先跑 01_extract.py")

    pages = read_jsonl(PAGES_JSONL)
    toc = read_json(TOC_JSON).get("entries", []) if TOC_JSON.exists() else []

    step(f"Stage 2 章節拆分（{len(pages)} 頁）")

    chapters: list[dict] = []
    method = ""

    if args.force_split:
        chapters = split_by_size(pages, args.force_split)
        method = f"強制均分 {args.force_split} 章"
    else:
        if toc and not args.force_regex:
            chapters = split_by_toc(pages, toc)
            method = "書籤／目錄"
            if len(chapters) < args.min_chapters:
                warn(f"用書籤只切出 {len(chapters)} 章，退回正規式掃描")
                chapters = []
        if not chapters:
            chapters = split_by_regex(pages)
            method = "正規式掃描"
        if len(chapters) < args.min_chapters:
            warn(f"正規式只切出 {len(chapters)} 章，退回依字數均分")
            chapters = split_by_size(pages, 8)
            method = "依字數均分（不可靠！）"

    if not chapters:
        die("拆章完全失敗。請檢查 work/01_raw/pages.jsonl 是否有內容，"
            "或用 --force-split N 強制均分。")

    ok(f"拆章方法：{method}，共 {len(chapters)} 章")

    # 清空舊檔再寫
    for old in CHAPTERS.glob("ch*.md"):
        old.unlink()

    written = write_chapters(chapters)
    print_table(written, pages)
    return 0


# ==========================================================================
# 策略 1：書籤／目錄
# ==========================================================================
def split_by_toc(pages: list[dict], toc: list[dict]) -> list[dict]:
    """取 level 1–2 的節點，用頁碼區間切。"""
    nodes = [e for e in toc if e.get("level", 1) <= 2 and e.get("page", 0) > 0]
    if not nodes:
        return []

    # 同一頁多個節點只留第一個；頁碼必須遞增
    seen_pages: set[int] = set()
    clean: list[dict] = []
    for n in sorted(nodes, key=lambda x: (x["page"], x.get("level", 1))):
        if n["page"] in seen_pages:
            continue
        seen_pages.add(n["page"])
        clean.append(n)

    # level 1 若已足夠（>=3），只用 level 1，避免小節被當成章
    l1 = [n for n in clean if n.get("level", 1) == 1]
    nodes = l1 if len(l1) >= 3 else clean

    last_page = max(p["page"] for p in pages)
    out = []
    for i, n in enumerate(nodes):
        start = n["page"]
        end = (nodes[i + 1]["page"] - 1) if i + 1 < len(nodes) else last_page
        if end < start:
            end = start
        out.append({"title": n["title"], "start": start, "end": end,
                    "text": page_range_text(pages, start, end)})
    return [c for c in out if c["text"].strip()]


# ==========================================================================
# 策略 2：正規式掃描
# ==========================================================================
def split_by_regex(pages: list[dict]) -> list[dict]:
    """掃描章節標題行 + 啟發式過濾（規劃書 §4.2）。

    啟發式：候選行必須位於頁面上半部、字數 < 40。
    """
    hits: list[dict] = []
    for p in pages:
        lines = [ln for ln in (p.get("text") or "").splitlines()]
        if not lines:
            continue
        half = max(1, len(lines) // 2)
        for li, raw in enumerate(lines[:half]):        # 只看頁面上半部
            ln = raw.strip()
            if not ln or len(ln) > HEADING_MAX_CHARS:  # 字數 < 40
                continue
            if any(r.match(ln) for r in CH_RE):
                hits.append({"page": p["page"], "line": li, "title": ln})
                break  # 一頁最多一個章首

    if not hits:
        return []

    # 同一頁只留一個；相鄰 < 2 頁的視為誤判（目錄頁會連續命中）
    dedup: list[dict] = []
    for h in hits:
        if dedup and h["page"] - dedup[-1]["page"] < 2:
            continue
        dedup.append(h)

    # 目錄頁過濾：若前 10% 頁面裡命中特別密集，那段多半是目錄，丟掉
    cutoff = max(1, int(len(pages) * 0.1))
    early = [h for h in dedup if h["page"] <= cutoff]
    if len(early) >= 4:
        info(f"前 {cutoff} 頁命中 {len(early)} 次，判定為目錄頁，已略過")
        dedup = [h for h in dedup if h["page"] > cutoff]

    last_page = max(p["page"] for p in pages)
    out = []
    for i, h in enumerate(dedup):
        start = h["page"]
        end = (dedup[i + 1]["page"] - 1) if i + 1 < len(dedup) else last_page
        out.append({"title": h["title"], "start": start, "end": max(end, start),
                    "text": page_range_text(pages, start, max(end, start))})
    return [c for c in out if c["text"].strip()]


# ==========================================================================
# 策略 3：依字數均分（最後手段）
# ==========================================================================
def split_by_size(pages: list[dict], n: int) -> list[dict]:
    warn("使用「依字數均分」拆章——這幾乎一定不符合原書結構，"
         "Stage 3 深讀品質會受影響。請人工確認並考慮用 --force-regex 或手改章節檔。")
    total = sum(len(p["text"]) for p in pages)
    target = total / max(n, 1)

    out, cur, acc, start = [], [], 0, pages[0]["page"] if pages else 1
    for p in pages:
        cur.append(p)
        acc += len(p["text"])
        if acc >= target and len(out) < n - 1:
            out.append({"title": f"第 {len(out) + 1} 部分", "start": start, "end": p["page"],
                        "text": "\n\n".join(x["text"] for x in cur)})
            cur, acc, start = [], 0, p["page"] + 1
    if cur:
        out.append({"title": f"第 {len(out) + 1} 部分", "start": start, "end": cur[-1]["page"],
                    "text": "\n\n".join(x["text"] for x in cur)})
    return out


# ==========================================================================
def page_range_text(pages: list[dict], start: int, end: int) -> str:
    return "\n\n".join(p["text"] for p in pages if start <= p["page"] <= end)


def word_count(text: str) -> int:
    """中文字數 + 英文詞數。"""
    cn = sum(1 for ch in text if "一" <= ch <= "鿿")
    en = len(re.findall(r"[A-Za-z]+", text))
    return cn + en


def write_chapters(chapters: list[dict]) -> list[dict]:
    written = []
    for i, ch in enumerate(chapters, start=1):
        ch_id = f"ch{i:02d}"
        title = re.sub(r"\s+", " ", ch["title"]).strip() or f"第 {i} 章"
        wc = word_count(ch["text"])
        fname = f"{ch_id}_{safe_filename(title)}.md"
        path = CHAPTERS / fname

        front = (
            "---\n"
            f"ch_id: {ch_id}\n"
            f'title: "{title.replace(chr(34), chr(39))}"\n'
            f"pages: [{ch['start']}, {ch['end']}]\n"
            f"word_count: {wc}\n"
            "---\n\n"
        )
        path.write_text(front + ch["text"].strip() + "\n", encoding="utf-8")
        written.append({"ch_id": ch_id, "title": title, "start": ch["start"],
                        "end": ch["end"], "word_count": wc, "path": path})
    return written


def print_table(written: list[dict], pages: list[dict]) -> None:
    """驗收點：印出章節清單表格，字數異常標紅。"""
    total = sum(c["word_count"] for c in written)
    print()
    print(_c("1", "  章節清單（驗收點 — 請確認拆章是否正確）"))
    print("  " + "─" * 74)
    print(f"  {'章號':<6} {'起訖頁':<12} {'字數':>8}  {'占比':>6}  標題")
    print("  " + "─" * 74)

    bad = 0
    for c in written:
        share = c["word_count"] / total if total else 0
        rng = f"{c['start']}–{c['end']}"
        line = f"  {c['ch_id']:<6} {rng:<12} {c['word_count']:>8,}  {share*100:>5.1f}%  {c['title'][:34]}"
        abnormal = c["word_count"] < MIN_WORDS or share > MAX_SHARE
        if abnormal:
            bad += 1
            reason = "字數過少" if c["word_count"] < MIN_WORDS else "占比過高"
            print(_c("31", line + f"   ← {reason}"))
        else:
            print(line)

    print("  " + "─" * 74)
    print(f"  {'合計':<6} {f'{len(pages)} 頁':<12} {total:>8,}")
    print()

    if bad:
        fail(f"{bad} 章字數異常（紅字），代表拆錯了。")
        info("處理方式：")
        info("  a) 重跑並強制正規式：python scripts/02_split_chapters.py --force-regex")
        info("  b) 強制均分 N 章    ：python scripts/02_split_chapters.py --force-split 8")
        info("  c) 直接手改 work/02_chapters/*.md（合併／拆開檔案，記得改 front-matter）")
    else:
        ok("字數分布正常，沒有明顯拆錯的章節")

    print()
    info("→ 停：請確認上面的章節清單。確認後才往下走 Stage 3。")
    info("   下一步：python scripts/03_digest.py --next")


if __name__ == "__main__":
    sys.exit(main())
