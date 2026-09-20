#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 — 外部研究擴編（由 Claude Code 驅動 + WebSearch）。

與 03_digest.py 同樣是「發題 / 收題 / 進度」三件事，不自己產內容。

    python scripts/04_research.py --next           # 印出下一章的研究提示詞（含 digest）
    …模型用 WebSearch 查證，寫入 work/04_evidence/chNN.json…
    python scripts/04_research.py --validate ch01  # 驗證 schema 與硬性規則
    python scripts/04_research.py --author         # 全書一次：作者解析 + 中譯本章名的提示詞
    python scripts/04_research.py --validate-author
    python scripts/08_qa.py --check-sources        # 全章跑完後做 URL 全檢

硬性規則（規劃書 §6）：每一筆都必須有 source_url，查不到就不要寫，
絕對不准編造 URL 或推測數字。這支腳本會擋掉沒有 URL、
以及看起來像自行拼湊的網址。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    AUTHOR_JSON, DIGEST, EVIDENCE, PROJECT_FILE, PROMPTS, chapter_files, check_keys, die,
    ensure_dirs, fail, format_timecode, info, load_project, nonempty_str, ok,
    parse_chapter_file, parse_timecode, read_json, step, strip_chapter_number, visual_len,
    warn,
)

PROMPT_FILE = PROMPTS / "research.md"
AUTHOR_PROMPT = PROMPTS / "author.md"

VALID_STATUS = {"confirmed", "outdated", "contested"}
VALID_CHART = {"bar", "line", "stacked"}

# 常見「自行拼湊」特徵：只有網域沒有路徑、或路徑帶明顯佔位符
PLACEHOLDER_RE = re.compile(
    r"(example\.com|your-?url|xxx|\.\.\.|<[^>]+>|\{[^}]+\}|placeholder|TODO)", re.I
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 4：外部研究（Claude Code 驅動）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--next", action="store_true", help="印出下一個未完成章節的研究提示詞")
    g.add_argument("--prompt", metavar="CH_ID", help="印出指定章節的研究提示詞")
    g.add_argument("--validate", metavar="CH_ID", help="驗證指定章節，all = 全部")
    g.add_argument("--status", action="store_true", help="顯示各章進度")
    g.add_argument("--videos", action="store_true",
                   help="列出所有章節找到的影片建議，讓使用者挑")
    g.add_argument("--accept-video", metavar="CH_ID:N",
                   help="把某章的第 N 支影片加進 config/project.yaml 的 videos[]，如 ch03:0")
    g.add_argument("--author", action="store_true",
                   help="印出作者解析（含中譯本章名）的提示詞，全書只跑一次")
    g.add_argument("--validate-author", action="store_true", help="驗證 work/04_author.json")
    args = ap.parse_args()

    ensure_dirs()
    ids = _all_ch_ids()
    if not ids:
        die("work/02_chapters/ 是空的，請先跑 02_split_chapters.py")

    if args.author:
        return emit_author_prompt(ids)
    if args.validate_author:
        return run_validate_author()
    if args.status:
        return show_status(ids)
    if args.videos:
        return list_videos(ids)
    if args.accept_video:
        return accept_video(args.accept_video)
    if args.next:
        return emit_next(ids)
    if args.prompt:
        return emit_prompt(args.prompt)
    if args.validate:
        return run_validate(args.validate, ids)
    return 0


# ==========================================================================
def _all_ch_ids() -> list[str]:
    out = []
    for p in chapter_files():
        meta, _ = parse_chapter_file(p)
        out.append(meta.get("ch_id") or p.name.split("_")[0])
    return out


def ev_path(ch_id: str) -> Path:
    return EVIDENCE / f"{ch_id}.json"


def show_status(ids: list[str]) -> int:
    step("Stage 4 進度")
    done = todo = broken = missing_digest = 0
    for ch_id in ids:
        if not (DIGEST / f"{ch_id}.json").exists():
            print(f"  ⊘ {ch_id}  缺 digest（Stage 3 還沒做）")
            missing_digest += 1
            continue
        p = ev_path(ch_id)
        if not p.exists():
            print(f"  ○ {ch_id}  未處理")
            todo += 1
            continue
        errs = validate_evidence(p, ch_id)
        if errs:
            print(f"  ✗ {ch_id}  {len(errs)} 項不合格")
            broken += 1
        else:
            d = read_json(p)
            print(f"  ● {ch_id}  已完成 "
                  f"(verified {len(d.get('verified', []))} / "
                  f"台灣視角 {len(d.get('taiwan_lens', []))} / "
                  f"圖表 {len(d.get('chart_candidates', []))})")
            done += 1
    print()
    info(f"完成 {done} / 共 {len(ids)} 章"
         + (f"，{broken} 章不合格" if broken else "")
         + (f"，{todo} 章未處理" if todo else "")
         + (f"，{missing_digest} 章缺 digest" if missing_digest else ""))
    if AUTHOR_JSON.exists():
        a_errs = validate_author(AUTHOR_JSON)
        print(("  ✗ 作者解析  %d 項不合格" % len(a_errs)) if a_errs else
              "  ● 作者解析  已完成（work/04_author.json）")
    else:
        print("  ○ 作者解析  未做：python scripts/04_research.py --author")
    if missing_digest:
        info("先補 Stage 3：python scripts/03_digest.py --next")
    elif todo or broken:
        info("下一步：python scripts/04_research.py --next")
    else:
        ok("Stage 4 全數完成 → 先跑 python scripts/08_qa.py --check-sources 驗證連結")
    return 0


def emit_next(ids: list[str]) -> int:
    for ch_id in ids:
        if not (DIGEST / f"{ch_id}.json").exists():
            continue
        p = ev_path(ch_id)
        if not p.exists() or validate_evidence(p, ch_id):
            return emit_prompt(ch_id)
    ok("所有章節都已完成。下一步：python scripts/08_qa.py --check-sources")
    return 0


def emit_prompt(ch_id: str) -> int:
    dp = DIGEST / f"{ch_id}.json"
    if not dp.exists():
        die(f"{ch_id} 還沒有 digest（{dp}），請先跑 Stage 3")
    if not PROMPT_FILE.exists():
        die(f"找不到提示詞：{PROMPT_FILE}")

    cfg = load_project()
    digest_txt = dp.read_text(encoding="utf-8")
    tpl = PROMPT_FILE.read_text(encoding="utf-8")
    tpl = tpl.replace("{ch_id}", ch_id).replace("{digest_json}", f"work/03_digest/{ch_id}.json")

    d = read_json(dp)
    res = cfg.get("research", {})

    print("=" * 78)
    print(f"  Stage 4 研究提示詞 — {ch_id}：{d.get('title', '')}")
    print(f"  產出目標 work/04_evidence/{ch_id}.json")
    print(f"  設定：每章至少 {res.get('min_sources_per_chapter', 2)} 筆來源；"
          f"超過 {res.get('max_source_age_years', 3)} 年的數據要更新；"
          f"台灣視角 {'必要' if res.get('taiwan_lens') else '選用'}")
    print("=" * 78)
    print()
    print(tpl)
    print()
    print("-" * 78)
    print(f"## 輸入：{ch_id} 的 Stage 3 摘要")
    print("-" * 78)
    print()
    print(digest_txt)
    print("-" * 78)
    print()
    print("## 建議的檢索起點（從 open_questions 直接來，請自行補充中英各半）")
    for q in d.get("open_questions", []):
        print(f"  - {q}")
    for dp_ in d.get("data_points", []):
        print(f"  - 查證：{dp_.get('claim', '')}（書中值 {dp_.get('value', '')}，"
              f"as_of {dp_.get('as_of', '')}）目前最新值是多少？")
    print()
    print("=" * 78)
    print(f"  寫完後執行：python scripts/04_research.py --validate {ch_id}")
    print("=" * 78)
    return 0


def run_validate(target: str, ids: list[str]) -> int:
    targets = ids if target == "all" else [target]
    step(f"Stage 4 驗證（{len(targets)} 章）")
    total_err = 0
    for ch_id in targets:
        p = ev_path(ch_id)
        if not p.exists():
            fail(f"{ch_id}: 檔案不存在 {p}")
            total_err += 1
            continue
        errs = validate_evidence(p, ch_id)
        if errs:
            fail(f"{ch_id}: {len(errs)} 項不合格")
            for e in errs:
                print(f"      - {e}")
            total_err += len(errs)
        else:
            ok(f"{ch_id}: 通過")
    print()
    if total_err:
        fail(f"共 {total_err} 項不合格 —— 依 prompts/research.md「硬性規則」修正")
        return 1
    ok("全數通過")
    info("下一步：python scripts/08_qa.py --check-sources（做一次 URL HTTP 全檢）")
    return 0



# ==========================================================================
# 作者解析（含中譯本章名）：全書一次
# ==========================================================================
def emit_author_prompt(ids: list[str]) -> int:
    if not AUTHOR_PROMPT.exists():
        die(f"找不到提示詞：{AUTHOR_PROMPT}")
    cfg = load_project()
    book = cfg.get("book") or {}
    rows = []
    for p in chapter_files():
        meta, _ = parse_chapter_file(p)
        rows.append(f"- {meta.get('ch_id')}  {strip_chapter_number(meta.get('title', ''))}")
    tpl = (AUTHOR_PROMPT.read_text(encoding="utf-8")
           .replace("{book_title_en}", book.get("title_en", ""))
           .replace("{book_title_zh}", book.get("title_zh", ""))
           .replace("{author}", book.get("author", ""))
           .replace("{chapter_list}", "\n".join(rows)))
    print("=" * 78)
    print("  Stage 4 作者解析提示詞（讀完寫 work/04_author.json）")
    print("=" * 78)
    print(tpl)
    return 0


def run_validate_author() -> int:
    step("驗證 work/04_author.json")
    if not AUTHOR_JSON.exists():
        die(f"找不到 {AUTHOR_JSON}，先跑 --author")
    errs = validate_author(AUTHOR_JSON)
    if errs:
        for e in errs:
            fail(e)
        print()
        info(f"{len(errs)} 項不合格，依 prompts/author.md 修正後重驗")
        return 1
    d = read_json(AUTHOR_JSON)
    a, b = d.get("author") or {}, d.get("book") or {}
    ez = b.get("edition_zh") or {}
    n_zh = sum(1 for c in (b.get("chapters") or []) if (c.get("title_zh") or "").strip())
    ok(f"通過：{a.get('name')}｜背景 {len(a.get('background') or [])}、生涯 {len(a.get('career') or [])}、"
       f"著作 {len(a.get('works') or [])}、評價 {len(a.get('reception') or [])}、批評 {len(a.get('critics') or [])}")
    if ez:
        info(f"中譯本：《{ez.get('title_zh', '')}》{ez.get('publisher', '')} {ez.get('year', '')}，"
             f"{ez.get('translator', '')} 譯；官方章名 {n_zh}/{len(b.get('chapters') or [])} 章")
    else:
        info("沒有中譯本：簡報章名用原文")
    return 0


def _url_real(url: str) -> bool:
    """看起來是真的網址：http(s)、有網域、路徑不只一個斜線、沒有佔位符。"""
    if not isinstance(url, str) or not url.strip():
        return False
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return False
    if PLACEHOLDER_RE.search(url):
        return False
    return len(u.path.strip("/")) > 0 or bool(u.query)


def _sourced_list(items, key: str, lo: int, hi: int, text_key: str, cap: int,
                  errs: list[str], required: tuple[str, ...] = ()) -> None:
    if not isinstance(items, list) or not (lo <= len(items) <= hi):
        errs.append(f"author.{key} 需 {lo}–{hi} 筆（目前 {len(items) if isinstance(items, list) else '非陣列'}）")
        return
    for i, it in enumerate(items):
        w = f"author.{key}[{i}]"
        if not isinstance(it, dict):
            errs.append(f"{w} 必須是物件")
            continue
        for k in (text_key,) + required:
            nonempty_str(it, k, w, errs)
        if visual_len(it.get(text_key) or "") > cap:
            errs.append(f"{w}.{text_key} 超過 {cap} 字")
        if not _url_real(it.get("source_url")):
            errs.append(f"{w}.source_url 不是真實網址：{it.get('source_url')!r}（查不到就少寫一筆）")


def validate_author(path: Path) -> list[str]:
    errs: list[str] = []
    try:
        d = read_json(path)
    except Exception as e:  # noqa: BLE001
        return [f"JSON 解析失敗：{e}"]
    check_keys(d, ["author", "book"], "04_author", errs)
    if errs:
        return errs
    a, b = d.get("author"), d.get("book")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return ["author 與 book 都必須是物件"]

    nonempty_str(a, "name", "author", errs)
    _sourced_list(a.get("background"), "background", 3, 6, "text", 60, errs)
    _sourced_list(a.get("career"), "career", 3, 8, "what", 40, errs, required=("when",))
    _sourced_list(a.get("works"), "works", 1, 12, "title_en", 60, errs)
    _sourced_list(a.get("stance"), "stance", 1, 3, "text", 60, errs)
    _sourced_list(a.get("reception"), "reception", 1, 4, "text", 60, errs)
    _sourced_list(a.get("critics") if a.get("critics") is not None else [], "critics", 0, 3, "text", 60, errs)
    why = a.get("why_this_book")
    if not isinstance(why, dict) or not (why.get("text") or "").strip():
        errs.append("author.why_this_book.text 必填：作者為什麼寫這本書")
    else:
        if visual_len(why["text"]) > 120:
            errs.append("author.why_this_book.text 超過 120 字")
        if not _url_real(why.get("source_url")):
            errs.append("author.why_this_book.source_url 不是真實網址")
    if not (a.get("reception") and (a.get("critics") or [])):
        errs.append("評價與批評要成對：reception 與 critics 至少各 1 筆（只有掌聲的作者頁不可信）")

    nonempty_str(b, "title_en", "book", errs)
    ez = b.get("edition_zh")
    chapters = b.get("chapters")
    if ez is not None:
        if not isinstance(ez, dict):
            errs.append("book.edition_zh 必須是物件或 null")
        else:
            for k in ("title_zh", "publisher", "translator"):
                nonempty_str(ez, k, "book.edition_zh", errs)
            if not _url_real(ez.get("source_url")):
                errs.append("book.edition_zh.source_url 不是真實網址")
            n_zh = sum(1 for c in (chapters or []) if isinstance(c, dict) and (c.get("title_zh") or "").strip())
            if not n_zh:
                errs.append("有中譯本就要把目錄抄進 book.chapters（title_zh 逐字照抄），一章都沒抄到不准說有中譯本")
    if chapters is not None:
        if not isinstance(chapters, list):
            errs.append("book.chapters 必須是陣列")
        else:
            for i, c in enumerate(chapters):
                w = f"book.chapters[{i}]"
                if not isinstance(c, dict):
                    errs.append(f"{w} 必須是物件")
                    continue
                nonempty_str(c, "title_en", w, errs)
                if not isinstance(c.get("title_zh", ""), str):
                    errs.append(f"{w}.title_zh 必須是字串（抄不到給空字串）")
    return errs


# ==========================================================================
# 影片建議
# ==========================================================================
def _candidates(ids: list[str]) -> list[tuple[str, int, dict]]:
    out = []
    for ch_id in ids:
        p = ev_path(ch_id)
        if not p.exists():
            continue
        try:
            d = read_json(p)
        except Exception:                              # noqa: BLE001
            continue
        for i, v in enumerate(d.get("video_candidates") or []):
            if isinstance(v, dict) and (v.get("url") or "").strip():
                out.append((ch_id, i, v))
    return out


def list_videos(ids: list[str]) -> int:
    cands = _candidates(ids)
    step(f"影片建議（{len(cands)} 支）")
    if not cands:
        info("還沒有影片建議。跑完 Stage 4 之後再看，或該章本來就沒找到合適的。")
        return 0

    chosen = {(v.get("url") or "").strip() for v in (load_project().get("videos") or [])
              if isinstance(v, dict)}
    for ch_id, i, v in cands:
        ss, ee = parse_timecode(v.get("suggested_start")), parse_timecode(v.get("suggested_end"))
        mark = "  ← 已加入" if (v.get("url") or "").strip() in chosen else ""
        print()
        print(f"  {ch_id}:{i}  {v.get('title', '')}{mark}")
        print(f"      {v.get('channel', '')}　建議片段 "
              f"{v.get('suggested_start', '')}–{v.get('suggested_end', '')}"
              f"（{format_timecode(max(0, ee - ss))}）")
        print(f"      {v.get('why', '')}")
        print(f"      {v.get('url', '')}")
    print()
    info("要用哪一支就跑：python scripts/04_research.py --accept-video ch03:0")
    info("（或直接手改 config/project.yaml 的 videos[]）")
    return 0


def accept_video(ref: str) -> int:
    """把 chNN:i 這支影片寫進 config/project.yaml 的 videos[]。"""
    if ":" not in ref:
        die("格式是 chNN:N，例如 ch03:0")
    ch_id, _, idx = ref.partition(":")
    try:
        idx = int(idx)
    except ValueError:
        die("格式是 chNN:N，例如 ch03:0")

    p = ev_path(ch_id)
    if not p.exists():
        die(f"{ch_id} 還沒有 evidence（{p}）")
    cands = read_json(p).get("video_candidates") or []
    if not (0 <= idx < len(cands)):
        die(f"{ch_id} 只有 {len(cands)} 支影片建議，沒有第 {idx} 支")
    v = cands[idx]

    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    cfg = yaml.load(PROJECT_FILE.read_text(encoding="utf-8")) or {}
    vids = cfg.get("videos")
    if not isinstance(vids, list):
        vids = []

    url = (v.get("url") or "").strip()
    if any(isinstance(x, dict) and (x.get("url") or "").strip() == url for x in vids):
        warn(f"這支影片已經在 videos[] 裡了：{v.get('title', '')}")
        return 0

    vids.append({
        "title": Q((v.get("title") or "").strip() or "參考影片"),
        "url": Q(url),
        # 時間碼一定要加引號，YAML 1.1 會把 1:30 當六十進位解析成 90
        "start": Q((v.get("suggested_start") or "0:00").strip()),
        "end": Q((v.get("suggested_end") or "3:00").strip()),
        "after_ch": Q(ch_id),
        "note": Q((v.get("why") or "").strip()),
    })
    cfg["videos"] = vids

    from io import StringIO

    buf = StringIO()
    yaml.dump(cfg, buf)
    PROJECT_FILE.write_text(buf.getvalue(), encoding="utf-8")

    ok(f"已加入：{v.get('title', '')}（放在 {ch_id} 之後）")
    info("下一步：重跑 python scripts/05_outline.py --force 讓影片頁進藍圖")
    return 0


# ==========================================================================
# Schema + 硬性規則驗證（規劃書 §6）
# ==========================================================================
def validate_evidence(path: Path, ch_id: str) -> list[str]:
    errors: list[str] = []
    try:
        d = read_json(path)
    except Exception as e:  # noqa: BLE001
        return [f"JSON 解析失敗：{e}"]

    check_keys(d, ["ch_id", "verified", "taiwan_lens", "extensions", "chart_candidates"],
               ch_id, errors)
    if errors:
        return errors

    if d.get("ch_id") != ch_id:
        errors.append(f"ch_id 不符：檔名是 {ch_id}，內容寫 {d.get('ch_id')!r}")

    cfg = load_project().get("research", {})
    min_src = int(cfg.get("min_sources_per_chapter", 2))
    need_tw = bool(cfg.get("taiwan_lens", True))

    # --- verified ---
    vs = d.get("verified")
    if not isinstance(vs, list):
        errors.append("verified 必須是陣列")
        vs = []
    for i, v in enumerate(vs):
        w = f"{ch_id}.verified[{i}]"
        check_keys(v, ["book_claim", "status", "current_fact", "as_of",
                       "source_title", "source_url"], w, errors)
        if not isinstance(v, dict):
            continue
        nonempty_str(v, "book_claim", w, errors)
        nonempty_str(v, "current_fact", w, errors)
        if v.get("status") not in VALID_STATUS:
            errors.append(f"{w}.status 必須是 {sorted(VALID_STATUS)}（目前 {v.get('status')!r}）")
        _check_url(v, w, errors)
        _check_as_of(v, w, errors)

    # --- taiwan_lens ---
    tls = d.get("taiwan_lens")
    if not isinstance(tls, list):
        errors.append("taiwan_lens 必須是陣列")
        tls = []
    if need_tw and len(tls) < 1:
        errors.append("每章至少 1 筆 taiwan_lens（config/project.yaml research.taiwan_lens: true）")
    for i, t in enumerate(tls):
        w = f"{ch_id}.taiwan_lens[{i}]"
        check_keys(t, ["angle", "insight", "supporting_data", "source_title", "source_url"],
                   w, errors)
        if not isinstance(t, dict):
            continue
        nonempty_str(t, "angle", w, errors)
        nonempty_str(t, "insight", w, errors, min_len=30)
        if visual_len(t.get("insight", "")) > 150:
            errors.append(f"{w}.insight 超過 150 字（{visual_len(t.get('insight','')):.0f}）")
        _check_url(t, w, errors)

    # --- extensions ---
    exts = d.get("extensions")
    if not isinstance(exts, list):
        errors.append("extensions 必須是陣列（沒有就給 []）")
        exts = []
    for i, e in enumerate(exts):
        w = f"{ch_id}.extensions[{i}]"
        check_keys(e, ["title", "content", "source_title", "source_url"], w, errors)
        if isinstance(e, dict):
            nonempty_str(e, "title", w, errors)
            nonempty_str(e, "content", w, errors, min_len=15)
            _check_url(e, w, errors)

    # --- chart_candidates ---
    ccs = d.get("chart_candidates")
    if not isinstance(ccs, list):
        errors.append("chart_candidates 必須是陣列（沒有就給 []）")
        ccs = []
    for i, c in enumerate(ccs):
        w = f"{ch_id}.chart_candidates[{i}]"
        check_keys(c, ["title", "data", "chart_type", "source_title", "source_url"], w, errors)
        if not isinstance(c, dict):
            continue
        nonempty_str(c, "title", w, errors)
        if c.get("chart_type") not in VALID_CHART:
            errors.append(f"{w}.chart_type 必須是 {sorted(VALID_CHART)}"
                          f"（目前 {c.get('chart_type')!r}；規劃書 §8.3 明令不畫圓餅圖）")
        data = c.get("data")
        if not isinstance(data, list) or len(data) < 2:
            errors.append(f"{w}.data 至少要有 2 個資料點")
        else:
            for j, pt in enumerate(data):
                if not isinstance(pt, dict) or "label" not in pt or "value" not in pt:
                    errors.append(f"{w}.data[{j}] 需要 label 與 value 兩個欄位")
                elif not isinstance(pt.get("value"), (int, float)):
                    errors.append(f"{w}.data[{j}].value 必須是數字（目前 {pt.get('value')!r}）")
        _check_url(c, w, errors)

    # --- figure_candidates（選填，有就要完整）---
    fcs = d.get("figure_candidates")
    if fcs is None:
        fcs = []                                   # 舊檔沒有這個欄位，視為空
    elif not isinstance(fcs, list):
        errors.append("figure_candidates 必須是陣列（沒有就給 []）")
        fcs = []
    for i, f in enumerate(fcs):
        w = f"{ch_id}.figure_candidates[{i}]"
        check_keys(f, ["title", "figure_url", "source_title", "as_of"], w, errors)
        if not isinstance(f, dict):
            continue
        nonempty_str(f, "title", w, errors)
        nonempty_str(f, "source_title", w, errors)
        url = (f.get("figure_url") or "").strip()
        if not url:
            errors.append(f"{w}.figure_url 空白 —— 沒有靜態圖檔就不要放這一筆")
        elif PLACEHOLDER_RE.search(url):
            errors.append(f"{w}.figure_url 含佔位符，疑似編造：{url}")
        else:
            pu = urlparse(url)
            if pu.scheme not in ("http", "https") or not pu.netloc:
                errors.append(f"{w}.figure_url 不是合法網址：{url}")
            elif not any(pu.path.lower().endswith(e)
                         for e in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp")) \
                    and "fredgraph" not in url:
                errors.append(f"{w}.figure_url 看起來是頁面網址不是圖檔：{url}"
                              "（圖檔網址放 figure_url，頁面網址放 page_url）")
        _check_as_of(f, w, errors)

    # --- video_candidates（選填，有就要完整）---
    vcs = d.get("video_candidates")
    if vcs is None:
        vcs = []                                   # 舊檔沒有這個欄位，視為空
    elif not isinstance(vcs, list):
        errors.append("video_candidates 必須是陣列（沒有就給 []）")
        vcs = []
    for i, v in enumerate(vcs):
        w = f"{ch_id}.video_candidates[{i}]"
        check_keys(v, ["title", "url", "why", "suggested_start", "suggested_end"], w, errors)
        if not isinstance(v, dict):
            continue
        nonempty_str(v, "title", w, errors)
        nonempty_str(v, "why", w, errors, min_len=8)
        url = (v.get("url") or "").strip()
        if not url:
            errors.append(f"{w}.url 空白 —— 找不到就不要放這一筆")
        elif PLACEHOLDER_RE.search(url):
            errors.append(f"{w}.url 含佔位符，疑似編造：{url}")
        else:
            pu = urlparse(url)
            if pu.scheme not in ("http", "https") or not pu.netloc:
                errors.append(f"{w}.url 不是合法網址：{url}")
        ss, ee = parse_timecode(v.get("suggested_start")), parse_timecode(v.get("suggested_end"))
        if ee <= ss:
            errors.append(f"{w}: suggested_end 要大於 suggested_start"
                          f"（{v.get('suggested_start')!r} → {v.get('suggested_end')!r}）")
        elif ee - ss > 600:
            errors.append(f"{w}: 建議片段 {(ee - ss) // 60} 分鐘太長，"
                          "分享會現場播 3–5 分鐘就好，挑切題的那一段")

    # --- 來源數量下限 ---
    urls = {x.get("source_url") for x in (vs + tls + exts + ccs)
            if isinstance(x, dict) and x.get("source_url")}
    if len(urls) < min_src:
        errors.append(f"本章只有 {len(urls)} 個不重複來源，低於下限 {min_src}")

    return errors


def _check_url(obj: dict, where: str, errors: list[str]) -> None:
    """硬性規則 1&2：必須有 source_url，且不可是拼湊出來的。"""
    url = (obj.get("source_url") or "").strip()
    if not url:
        errors.append(f"{where}.source_url 空白 —— 查不到就不要寫這一筆（不准編造）")
        return
    if PLACEHOLDER_RE.search(url):
        errors.append(f"{where}.source_url 含佔位符，疑似編造：{url}")
        return
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        errors.append(f"{where}.source_url 不是合法網址：{url}")
        return
    if not p.path.strip("/"):
        errors.append(f"{where}.source_url 只有網域沒有路徑（{url}），"
                      "疑似自行拼湊；請貼 WebSearch 實際回傳的頁面網址")
    if not (obj.get("source_title") or "").strip():
        errors.append(f"{where}.source_title 空白，要寫出機構／報告全稱")


def _check_as_of(obj: dict, where: str, errors: list[str]) -> None:
    v = (obj.get("as_of") or "").strip()
    if not v:
        errors.append(f"{where}.as_of 空白（格式 YYYY-MM，寫資料本身的時點）")
    elif not re.fullmatch(r"\d{4}(-\d{2})?", v):
        errors.append(f"{where}.as_of 格式應為 YYYY-MM 或 YYYY（目前 {v!r}）")


if __name__ == "__main__":
    sys.exit(main())
