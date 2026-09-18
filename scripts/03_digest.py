#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3 — 逐章深讀（由 Claude Code 驅動，不是寫死的程式）。

這支腳本本身不產生內容，它負責三件事：
    1. --next / --prompt chNN   發題：印出要餵給模型的完整提示詞（含章節全文）
    2. --validate chNN          收題：驗證寫回的 JSON 是否符合 schema 與品質底線
    3. --status                 進度：哪幾章做完了、哪幾章還沒

Claude Code 的標準跑法（一次一章，不要一次全塞進 context）：
    python scripts/03_digest.py --next          # 印出 ch01 的提示詞
    …模型讀題、產 JSON、寫入 work/03_digest/ch01.json…
    python scripts/03_digest.py --validate ch01 # 驗證，FAIL 就重寫
    python scripts/03_digest.py --next          # 換 ch02
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DIGEST, PROMPTS, chapter_files, check_keys, die, ensure_dirs, fail, info,
    nonempty_str, ok, parse_chapter_file, read_json, step, visual_len, warn,
)

PROMPT_FILE = PROMPTS / "digest.md"

# 品質底線用的敷衍句黑名單（規劃書 §5）
LAZY_EVIDENCE = ["書中提到", "書中指出", "作者提到", "文中提及", "如前所述", "詳見書中"]
LAZY_COUNTER = ["論述完整", "論證嚴謹", "沒有明顯問題", "無明顯缺陷", "十分完整",
                "相當完整", "並無不足", "沒有太大問題"]
PHILOSOPHICAL = ["是否真的", "人性", "意義是什麼", "本質為何", "值得嗎", "該不該"]


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 3：逐章深讀（Claude Code 驅動）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--next", action="store_true", help="印出下一個未完成章節的提示詞")
    g.add_argument("--prompt", metavar="CH_ID", help="印出指定章節的提示詞，如 ch03")
    g.add_argument("--validate", metavar="CH_ID", help="驗證指定章節，all = 全部")
    g.add_argument("--status", action="store_true", help="顯示各章進度")
    ap.add_argument("--max-chars", type=int, default=60000,
                    help="章節全文超過這個字元數就截斷（避免爆 context）")
    args = ap.parse_args()

    ensure_dirs()
    chs = chapter_files()
    if not chs:
        die("work/02_chapters/ 是空的，請先跑 02_split_chapters.py")

    if args.status:
        return show_status(chs)
    if args.next:
        return emit_next(chs, args.max_chars)
    if args.prompt:
        return emit_prompt(chs, args.prompt, args.max_chars)
    if args.validate:
        return run_validate(args.validate, chs)
    return 0


# ==========================================================================
def digest_path(ch_id: str) -> Path:
    return DIGEST / f"{ch_id}.json"


def find_chapter(chs: list[Path], ch_id: str) -> Path:
    for p in chs:
        if p.name.startswith(ch_id + "_") or p.stem == ch_id:
            return p
    die(f"找不到章節 {ch_id}。現有：{[p.name for p in chs]}")


def show_status(chs: list[Path]) -> int:
    step("Stage 3 進度")
    done = todo = broken = 0
    for p in chs:
        meta, _ = parse_chapter_file(p)
        ch_id = meta.get("ch_id") or p.name.split("_")[0]
        dp = digest_path(ch_id)
        if not dp.exists():
            print(f"  ○ {ch_id}  未處理     {meta.get('title', p.name)[:34]}")
            todo += 1
            continue
        errs = validate_digest(dp, ch_id)
        if errs:
            print(f"  ✗ {ch_id}  {len(errs)} 項不合格  {meta.get('title', '')[:30]}")
            broken += 1
        else:
            d = read_json(dp)
            print(f"  ● {ch_id}  已完成 ({len(d.get('key_points', []))} 論點) "
                  f"{meta.get('title', '')[:28]}")
            done += 1
    print()
    info(f"完成 {done} / 共 {len(chs)} 章"
         + (f"，{broken} 章不合格" if broken else "")
         + (f"，{todo} 章未處理" if todo else ""))
    if todo or broken:
        info("下一步：python scripts/03_digest.py --next")
    else:
        ok("Stage 3 全數完成 → 下一步：python scripts/04_research.py --next")
    return 0


def emit_next(chs: list[Path], max_chars: int) -> int:
    for p in chs:
        meta, _ = parse_chapter_file(p)
        ch_id = meta.get("ch_id") or p.name.split("_")[0]
        dp = digest_path(ch_id)
        if not dp.exists() or validate_digest(dp, ch_id):
            return emit_prompt(chs, ch_id, max_chars)
    ok("所有章節都已完成且通過驗證。下一步：python scripts/04_research.py --next")
    return 0


def emit_prompt(chs: list[Path], ch_id: str, max_chars: int) -> int:
    path = find_chapter(chs, ch_id)
    meta, body = parse_chapter_file(path)
    ch_id = meta.get("ch_id", ch_id)

    if not PROMPT_FILE.exists():
        die(f"找不到提示詞：{PROMPT_FILE}")
    tpl = PROMPT_FILE.read_text(encoding="utf-8")
    tpl = tpl.replace("{chapter_file}", str(path.relative_to(path.parent.parent.parent)))
    tpl = tpl.replace("{ch_id}", ch_id)

    truncated = False
    if len(body) > max_chars:
        body = body[:max_chars]
        truncated = True

    print("=" * 78)
    print(f"  Stage 3 深讀提示詞 — {ch_id}：{meta.get('title', '')}")
    print(f"  章節檔 {path.name} / 原書頁碼 {meta.get('pages')} / {meta.get('word_count')} 字")
    print(f"  產出目標 work/03_digest/{ch_id}.json")
    print("=" * 78)
    print()
    print(tpl)
    print()
    print("-" * 78)
    print(f"## 章節全文（{ch_id}：{meta.get('title', '')}，原書 p.{meta.get('pages')}）")
    if truncated:
        print(f"（註：全文過長，已截斷至 {max_chars:,} 字元）")
    print("-" * 78)
    print()
    print(body.strip())
    print()
    print("=" * 78)
    print(f"  寫完後執行：python scripts/03_digest.py --validate {ch_id}")
    print("=" * 78)
    return 0


def run_validate(target: str, chs: list[Path]) -> int:
    ids = []
    if target == "all":
        for p in chs:
            meta, _ = parse_chapter_file(p)
            ids.append(meta.get("ch_id") or p.name.split("_")[0])
    else:
        ids = [target]

    step(f"Stage 3 驗證（{len(ids)} 章）")
    total_err = 0
    for ch_id in ids:
        dp = digest_path(ch_id)
        if not dp.exists():
            fail(f"{ch_id}: 檔案不存在 {dp}")
            total_err += 1
            continue
        errs = validate_digest(dp, ch_id)
        if errs:
            fail(f"{ch_id}: {len(errs)} 項不合格")
            for e in errs:
                print(f"      - {e}")
            total_err += len(errs)
        else:
            ok(f"{ch_id}: 通過")
    print()
    if total_err:
        fail(f"共 {total_err} 項不合格 —— 依 prompts/digest.md「品質底線」重寫後再驗一次")
        return 1
    ok("全數通過")
    return 0


# ==========================================================================
# Schema + 品質底線驗證（規劃書 §5）
# ==========================================================================
def validate_digest(path: Path, ch_id: str) -> list[str]:
    errors: list[str] = []
    try:
        d = read_json(path)
    except Exception as e:  # noqa: BLE001
        return [f"JSON 解析失敗：{e}"]

    check_keys(d, ["ch_id", "title", "one_line", "thesis", "key_points", "quotes",
                   "data_points", "counterpoint", "open_questions"], ch_id, errors)
    if errors:
        return errors

    if d.get("ch_id") != ch_id:
        errors.append(f"ch_id 不符：檔名是 {ch_id}，內容寫 {d.get('ch_id')!r}")

    nonempty_str(d, "title", ch_id, errors)
    nonempty_str(d, "one_line", ch_id, errors)
    nonempty_str(d, "thesis", ch_id, errors)

    one_line, thesis = d.get("one_line", ""), d.get("thesis", "")
    if visual_len(one_line) > 30:
        errors.append(f"one_line 超過 30 字（{visual_len(one_line):.0f}）")
    if visual_len(thesis) > 80:
        errors.append(f"thesis 超過 80 字（{visual_len(thesis):.0f}）")
    if thesis and re.match(r"^\s*(本章|這章)(介紹|說明|討論|探討|講述)", thesis):
        errors.append("thesis 是描述不是論點：不要用「本章介紹…」開頭，要寫一個可被反駁的主張")

    # --- key_points ---
    kps = d.get("key_points") or []
    if not isinstance(kps, list) or not (3 <= len(kps) <= 5):
        errors.append(f"key_points 需 3–5 個（目前 {len(kps) if isinstance(kps, list) else '非陣列'}）")
    for i, kp in enumerate(kps if isinstance(kps, list) else []):
        w = f"{ch_id}.key_points[{i}]"
        check_keys(kp, ["point", "elaboration", "book_evidence", "page_ref"], w, errors)
        if not isinstance(kp, dict):
            continue
        nonempty_str(kp, "point", w, errors)
        nonempty_str(kp, "elaboration", w, errors, min_len=40)
        nonempty_str(kp, "book_evidence", w, errors, min_len=10)

        point = kp.get("point", "")
        if visual_len(point) > 12:
            errors.append(f"{w}.point 超過 12 字（{visual_len(point):.0f}）")

        elab = kp.get("elaboration", "") or ""
        el = visual_len(elab)
        if el and not (100 <= el <= 150):
            errors.append(f"{w}.elaboration 需 100–150 字（目前 {el:.0f}）")
        # 底線 1：elaboration 不能是 thesis 的改寫
        if elab and thesis and _overlap_ratio(elab, thesis) > 0.7:
            errors.append(f"{w}.elaboration 與 thesis 重疊度過高，等於改寫，請提供 thesis 沒有的資訊")

        # 底線 2：book_evidence 不可空話
        ev = (kp.get("book_evidence") or "").strip()
        if ev and len(ev) < 25 and any(l in ev for l in LAZY_EVIDENCE):
            errors.append(f"{w}.book_evidence 是空話（「{ev[:20]}」），要有人名／年份／數字／案例")
        if ev and not _has_specific(ev):
            errors.append(f"{w}.book_evidence 沒有任何具體物（人名／公司／年份／數字／案例名）")

    # --- quotes ---
    qs = d.get("quotes") or []
    if not isinstance(qs, list) or not (1 <= len(qs) <= 2):
        errors.append(f"quotes 需 1–2 個（目前 {len(qs) if isinstance(qs, list) else '非陣列'}）")
    for i, q in enumerate(qs if isinstance(qs, list) else []):
        w = f"{ch_id}.quotes[{i}]"
        check_keys(q, ["text", "page_ref"], w, errors)
        if isinstance(q, dict):
            nonempty_str(q, "text", w, errors)
            if visual_len(q.get("text", "")) > 50:
                errors.append(f"{w}.text 超過 50 字（{visual_len(q.get('text','')):.0f}）")

    # --- data_points（可為空，但有就要完整）---
    dps = d.get("data_points")
    if not isinstance(dps, list):
        errors.append("data_points 必須是陣列（沒有資料就給 []）")
    else:
        for i, dp in enumerate(dps):
            w = f"{ch_id}.data_points[{i}]"
            check_keys(dp, ["claim", "value", "as_of", "page_ref"], w, errors)

    # --- counterpoint 底線 3 ---
    cp = (d.get("counterpoint") or "").strip()
    nonempty_str(d, "counterpoint", ch_id, errors, min_len=10)
    if visual_len(cp) > 80:
        errors.append(f"counterpoint 超過 80 字（{visual_len(cp):.0f}）")
    if cp and any(l in cp for l in LAZY_COUNTER):
        errors.append(f"counterpoint 是敷衍句（「{cp[:24]}」），要指出具體弱點："
                      "取樣偏誤／時空背景已變／反例存在／因果倒置／只有個案沒統計")

    # --- open_questions 底線 4 ---
    oqs = d.get("open_questions") or []
    if not isinstance(oqs, list) or not (2 <= len(oqs) <= 3):
        errors.append(f"open_questions 需 2–3 個（目前 {len(oqs) if isinstance(oqs, list) else '非陣列'}）")
    for i, q in enumerate(oqs if isinstance(oqs, list) else []):
        w = f"{ch_id}.open_questions[{i}]"
        if not isinstance(q, str) or len(q.strip()) < 8:
            errors.append(f"{w}: 太短或非字串")
            continue
        if not _has_specific(q) and any(p in q for p in PHILOSOPHICAL):
            errors.append(f"{w}: 像哲學提問而非可查證問題（「{q[:24]}」），"
                          "要能指向具體資料：地區／年份／指標")
    return errors


def _overlap_ratio(a: str, b: str) -> float:
    """兩段中文的字元集合重疊比例（用短的那段當分母）。"""
    sa = {c for c in a if "一" <= c <= "鿿"}
    sb = {c for c in b if "一" <= c <= "鿿"}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


_SPECIFIC_RE = re.compile(
    r"[0-9０-９]"
    r"|[A-Z][A-Za-z&.\-]{1,}"
    r"|[一二三四五六七八九十百千萬]+\s*[年月日%％倍成元人次家間]"
)


def _has_specific(text: str) -> bool:
    return bool(_SPECIFIC_RE.search(text or ""))


if __name__ == "__main__":
    sys.exit(main())
