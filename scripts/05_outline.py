#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 — 導讀設計 → 投影片藍圖（作者章序、章名當節名）。

5a  --guide-prompt     印「導讀設計」提示詞：全書 digest / evidence / 作者解析的濃縮索引 + 規則，
                       Claude 讀完寫 work/05a_guide.json（prompts/guide.md）
    --validate-guide   驗 guide.json：欄位、字數、每筆引用的編號都要對得上
5b  （預設）           由 guide.json 生成 work/05_deck.json 骨架，文案由 Claude 依
                       prompts/outline.md 潤飾

導讀體結構：
    序幕   封面 → 作者是誰（2–3 頁）→ 執行摘要（全書主張）→ 章序地圖
    每章   章名頁籤（官方中譯，否則原文）→ 大綱頁（論證鏈）→ 示意圖／書中原圖 → 重點 → 今天的數字
    收尾   全書對長期投資的意義 → 反方 → 結語
    附錄   沒進主線的章（不計時、不需逐字稿）

故事不做成投影片：每章選一則，掛在大綱頁的 story_hint，寫逐字稿時當開場。
沒有頁數預算、不裁頁：品質優先。時間只在 08_qa 當 WARN。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECK_JSON, DIGEST, EVIDENCE, GUIDE_JSON, LAYOUT_FAMILIES, PROMPTS, ROLE_LABELS, ROOT,
    WORK, chapter_display_name, chapter_files, check_keys, die, ensure_dirs, fail,
    family_layouts, format_timecode, info, is_appendix, layout_family, load_author,
    load_project, looks_like_topic, ok, parse_chapter_file, read_json, step,
    strip_chapter_number, talk_minutes_range, target_slides, tone_directive, tone_key,
    tone_preset, videos, visual_len, warn, write_json,
)

# 固定版面：封面／目錄／頁籤／空白內頁／結尾（config/fh_template_spec.json）
L_COVER, L_TOC, L_DIVIDER, L_BLANK, L_CLOSING = 0, 1, 2, 9, 10

TODO = "【待填】"
PROMPT_FILE = PROMPTS / "guide.md"

REF_KEYS = ("kp", "quote", "data", "figure", "taiwan", "verified", "chart", "extension", "story")
VISUALS = ("image", "table", "split", "flow", "timeline", "stat", "quote", "chart",
           "labeled", "chain", "prose")


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 5：導讀設計 → 藍圖")
    ap.add_argument("--guide-prompt", action="store_true",
                    help="5a：印導讀設計提示詞（Claude 讀完寫 work/05a_guide.json）")
    ap.add_argument("--validate-guide", action="store_true", help="驗 work/05a_guide.json")
    ap.add_argument("--force", action="store_true", help="覆寫既有的 05_deck.json")
    ap.add_argument("--dry-run", action="store_true", help="只印頁面組成，不寫檔")
    args = ap.parse_args()

    ensure_dirs()
    cfg = load_project()
    chapters = load_chapters()
    if not chapters:
        die("沒有可用的章節資料。請先跑 Stage 2–4。")

    if args.guide_prompt:
        return emit_guide_prompt(chapters, cfg)
    if args.validate_guide:
        return run_validate_guide(chapters)

    if not GUIDE_JSON.exists():
        die(f"找不到 {GUIDE_JSON}\n"
            "  藍圖是從「導讀設計」長出來的：\n"
            "    python scripts/05_outline.py --guide-prompt     # 印提示詞，依 prompts/guide.md 寫 guide.json\n"
            "    python scripts/05_outline.py --validate-guide\n"
            "    python scripts/05_outline.py                    # 再回來產藍圖")
    guide = read_json(GUIDE_JSON)
    errs = validate_guide(guide, chapters)
    if errs:
        for e in errs:
            fail(e)
        die(f"guide.json 有 {len(errs)} 項不合格，修好再產藍圖")

    if DECK_JSON.exists() and not args.force and not args.dry_run:
        die(f"{DECK_JSON} 已存在。要重建請加 --force\n"
            "（注意：--force 會蓋掉你手改過的文案。改稿迴圈請直接改 deck.json 再跑 Stage 6–8）")

    step(f"Stage 5b 藍圖生成（主線 {len(guide['main_ch_ids'])} 章／共 {len(chapters)} 章）")
    fam = LAYOUT_FAMILIES[layout_family()]
    info(f"內頁色系：{fam['label']}（內頁{layout_family()} / {layout_family()}-1）"
         f"　語氣：{tone_preset().get('label', tone_key())}")
    author = load_author()
    if not author:
        warn("沒有 work/04_author.json，作者頁會是空殼：python scripts/04_research.py --author")

    slides = build_slides(guide, chapters, cfg, author)
    slides = assign_durations(slides)

    cm = chapter_map(chapters)
    parts = (author.get("book") or {}).get("parts") or []
    deck = {
        "meta": {
            "book_title": cfg["book"].get("title_zh", ""),
            "book_title_en": cfg["book"].get("title_en", ""),
            "author": cfg["book"].get("author", ""),
            "presenter": cfg["presenter"].get("name", ""),
            "dept": cfg["presenter"].get("dept", ""),
            "date": cfg["presenter"].get("date", ""),
            "minutes": cfg["deck"].get("minutes", 60),
            "layout_family": layout_family(),
            "layout_family_label": fam["label"],
            "tone": tone_key(),
            "tone_directive_slide": tone_directive("slide"),
            "tone_directive_narration": tone_directive("narration"),
            "structure": {
                "form": "guided",
                "book_claim": guide["book_claim"],
                "book_claim_short": guide["book_claim_short"],
                "main_ch_ids": guide["main_ch_ids"],
                "parts": parts,
                "counter_claim": guide["counter"]["claim"],
                "closing": guide["closing"],
                "appendix_ch_ids": [c["ch_id"] for c in chapters if c["ch_id"] not in guide["main_ch_ids"]],
            },
            "chapters": [{"ch_id": c["ch_id"], "title": c["title"], "no_label": c["no_label"],
                          "title_en": c["title_en"], "display": c["display"]} for c in chapters],
        },
        "slides": slides,
    }

    print_summary(slides)
    if args.dry_run:
        info("--dry-run：未寫檔")
        return 0

    write_json(DECK_JSON, deck)
    ok(f"藍圖 → {DECK_JSON}（{len(slides)} 頁）")
    print()
    info("→ 停：接下來是最省時的修改點。")
    info("   1) Claude 依 prompts/outline.md 潤飾 work/05_deck.json（把所有【待填】補掉）")
    info("   2) 視覺頁另讀 prompts/visuals.md；故事寫進逐字稿（大綱頁的 story_hint）")
    info("   3) python scripts/08_qa.py --check-deck  驗證文案與結構")
    return 0


# ==========================================================================
# 資料載入
# ==========================================================================
def chapter_no_label(title: str) -> str:
    """「5: John Bull …」→「第 5 章」；Introduction／Conclusion／Postscript → 引言／結語／後記。"""
    t = (title or "").strip()
    m = re.match(r"^\s*(?:第\s*)?([0-9]+)\s*[章:：.．\-—]", t) or re.match(r"^\s*Chapter\s+([0-9]+)", t, re.I)
    if m:
        return f"第 {int(m.group(1))} 章"
    low = t.lower()
    for key, lab in (("introduction", "引言"), ("prologue", "序章"), ("conclusion", "結語"),
                     ("postscript", "後記"), ("epilogue", "尾聲"), ("preface", "前言")):
        if low.startswith(key):
            return lab
    return ""


def load_chapters() -> list[dict]:
    """把 02/03/04 三層資料併起來，並算好章名的顯示方式。缺 digest 的章節會被略過並警告。"""
    out = []
    for p in chapter_files():
        meta, _ = parse_chapter_file(p)
        ch_id = meta.get("ch_id") or p.name.split("_")[0]
        dp, ep = DIGEST / f"{ch_id}.json", EVIDENCE / f"{ch_id}.json"
        if not dp.exists():
            warn(f"{ch_id} 缺 digest，已略過（跑 03_digest.py 補上）")
            continue
        digest = read_json(dp)
        evidence = read_json(ep) if ep.exists() else {}
        if not ep.exists():
            warn(f"{ch_id} 缺 evidence，外部證據會留空（跑 04_research.py 補上）")
        title = digest.get("title") or meta.get("title") or ch_id
        display, title_en = chapter_display_name(title, digest)
        out.append({
            "ch_id": ch_id,
            "title": title,
            "no_label": chapter_no_label(title),
            "title_en": title_en,
            "display": display,
            "pages": meta.get("pages"),
            "digest": digest,
            "evidence": evidence,
        })
    return out


def chapter_map(chapters: list[dict]) -> dict[str, dict]:
    return {c["ch_id"]: c for c in chapters}


def available_figures() -> list[str]:
    figs = sorted(str(p.relative_to(ROOT)) for p in (WORK / "08_bookfigs").glob("*.png"))
    figs += sorted(str(p.relative_to(ROOT)) for p in (WORK / "09_srcfigs").glob("*.png"))
    return figs


def chapter_source_label(c: dict, page_ref: str = "", book_label: str = "") -> str:
    """資料來源行：《書》第 5 章〈約翰牛受不了 2%〉p.94。"""
    head = " ".join(x for x in (c.get("no_label", ""), f"〈{c['display']}〉") if x)
    return f"{book_label}{head} {page_ref}".strip()


# ==========================================================================
# 5a：導讀設計提示詞
# ==========================================================================
def emit_guide_prompt(chapters: list[dict], cfg: dict) -> int:
    if not PROMPT_FILE.exists():
        die(f"找不到提示詞：{PROMPT_FILE}")
    tpl = PROMPT_FILE.read_text(encoding="utf-8")
    book = cfg["book"]
    figs = available_figures()
    fig_text = "\n".join(f"- `{f}`" for f in figs) if figs else \
        "（還沒抽圖：python tools/extract_book_figures.py --input input/book.pdf --out work/08_bookfigs）"
    ez = (load_author().get("book") or {}).get("edition_zh") or {}
    ez_text = (f"《{ez.get('title_zh', '')}》{ez.get('publisher', '')} {ez.get('year', '')}，"
               f"{ez.get('translator', '')} 譯（章名已對照官方目錄）") if ez else \
        "沒有查到中譯本（章名用原文）"
    body = (tpl.replace("{book_title}", book.get("title_zh", ""))
               .replace("{author}", book.get("author", ""))
               .replace("{n_chapters}", str(len(chapters)))
               .replace("{edition_zh}", ez_text)
               .replace("{digest_summary}", digest_summary(chapters))
               .replace("{figures}", fig_text))
    print("=" * 78)
    print("  Stage 5a 導讀設計提示詞（讀完寫 work/05a_guide.json）")
    print("=" * 78)
    print(body)
    return 0


def _short(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if visual_len(text) <= n else _truncate(text, n)


def digest_summary(chapters: list[dict]) -> str:
    """全書濃縮索引：每章一段，每一筆素材都帶編號，guide.json 只能引用這些編號。"""
    lines: list[str] = []
    for c in chapters:
        d, e = c["digest"], c["evidence"]
        pages = c.get("pages")
        pg = f"（p.{pages[0]}–{pages[1]}）" if isinstance(pages, (list, tuple)) and len(pages) == 2 else ""
        head = " ".join(x for x in (c["no_label"], c["display"]) if x)
        en = f"｜{c['title_en']}" if c["display"] != c["title_en"] else ""
        lines.append(f"### {c['ch_id']}  {head}{en}{pg}")
        lines.append(f"主張：{d.get('thesis', '')}")
        lines.append(f"一句話：{d.get('one_line', '')}")
        for i, kp in enumerate(d.get("key_points") or []):
            lines.append(f"論點 kp{i}　{kp.get('point', '')}｜證據：{_short(kp.get('book_evidence', ''), 70)}"
                         f"（{kp.get('page_ref', '')}）")
        for i, kt in enumerate(d.get("key_terms") or []):
            zh = f"／{kt.get('zh')}" if (kt.get("zh") or "").strip() else ""
            lines.append(f"用語 term{i}　{kt.get('en', '')}{zh}（{kt.get('page_ref', '')}）"
                         + (f"：{kt['note']}" if kt.get("note") else ""))
        for i, st in enumerate(d.get("stories") or []):
            lines.append(f"故事 story{i}　{st.get('who', '')}，{st.get('when', '')}｜{_short(st.get('what', ''), 60)}"
                         f"｜轉折：{_short(st.get('turn', ''), 30)}（{st.get('page_ref', '')}）")
        for i, dp in enumerate(d.get("data_points") or []):
            lines.append(f"數據 data{i}　{_short(dp.get('claim', ''), 40)}＝{_short(str(dp.get('value', '')), 30)}"
                         f"（{dp.get('as_of', '')}，{dp.get('page_ref', '')}）")
        for i, q in enumerate(d.get("quotes") or []):
            qt = (q.get("text") or "").strip().strip("「」\"'")
            lines.append(f"引句 quote{i}　「{_short(qt, 60)}」（{q.get('page_ref', '')}）")
        lines.append(f"反方：{d.get('counterpoint', '')}")
        ext: list[str] = []
        for i, t in enumerate(e.get("taiwan_lens") or []):
            ext.append(f"taiwan{i}　{_short(t.get('angle', ''), 30)}：{_short(t.get('supporting_data', ''), 50)}")
        for i, v in enumerate(e.get("verified") or []):
            st = v.get("status", "")
            if st in ("outdated", "contested"):
                ext.append(f"verified{i}［{st}］　{_short(v.get('book_claim', ''), 30)} → "
                           f"{_short(v.get('current_fact', ''), 50)}（{v.get('as_of', '')}）")
        for i, x in enumerate(e.get("extensions") or []):
            ext.append(f"extension{i}　{_short(x.get('title', ''), 40)}")
        for i, x in enumerate(e.get("chart_candidates") or []):
            ext.append(f"chart{i}　{_short(x.get('title', ''), 40)}（{len(x.get('data') or [])} 點，{x.get('unit', '')}）")
        for i, x in enumerate(e.get("figure_candidates") or []):
            ext.append(f"figure_candidate{i}　{_short(x.get('title', ''), 40)}（機構原圖，抓回本機後用 figure 路徑引用）")
        if ext:
            lines.append("外部　" + "\n　　　".join(ext))
        lines.append("")
    return "\n".join(lines)


# ==========================================================================
# guide.json 驗證
# ==========================================================================
def run_validate_guide(chapters: list[dict]) -> int:
    step("驗證 work/05a_guide.json")
    if not GUIDE_JSON.exists():
        die(f"找不到 {GUIDE_JSON}，先跑 --guide-prompt")
    try:
        guide = read_json(GUIDE_JSON)
    except Exception as ex:  # noqa: BLE001
        die(f"guide.json 不是合法 JSON：{ex}")
    errs = validate_guide(guide, chapters)
    if errs:
        for e in errs:
            fail(e)
        print()
        info(f"{len(errs)} 項不合格，修好再跑一次 --validate-guide")
        return 1
    cm = chapter_map(chapters)
    main = guide["main_ch_ids"]
    n_vis = sum(len(guide["chapters"][c].get("visuals") or []) for c in main)
    ok(f"通過：主線 {len(main)} 章、示意圖／原圖 {n_vis} 張、反方 {len(guide['counter']['points'])} 條、"
       f"附錄 {len(chapters) - len(main)} 章")
    for c in main:
        ch = cm[c]
        info(f"  {ch['no_label'] or c:<6} {ch['display']}　← {guide['chapters'][c]['headline']}")
    info("下一步：python scripts/05_outline.py")
    return 0


def _len_check(obj: dict, key: str, cap: int, where: str, errs: list[str]) -> None:
    v = obj.get(key)
    if not isinstance(v, str) or not v.strip():
        errs.append(f"{where}.{key}: 必須是非空字串")
        return
    n = visual_len(v.strip())
    if n > cap:
        errs.append(f"{where}.{key}: {n:.0f} 字 > {cap}：「{v.strip()[:30]}」")


def validate_guide(guide: dict, chapters: list[dict]) -> list[str]:
    errs: list[str] = []
    if not isinstance(guide, dict):
        return ["guide.json 最外層必須是物件"]
    cm = chapter_map(chapters)
    order = [c["ch_id"] for c in chapters]
    check_keys(guide, ["book_claim", "book_claim_short", "why_now", "implication_short",
                       "implications", "main_ch_ids", "chapters", "counter", "closing"], "guide", errs)
    if errs:
        return errs

    _len_check(guide, "book_claim", 40, "guide", errs)
    _len_check(guide, "book_claim_short", 14, "guide", errs)
    _len_check(guide, "why_now", 21, "guide", errs)
    _len_check(guide, "implication_short", 14, "guide", errs)
    _len_check(guide, "closing", 14, "guide", errs)
    why = looks_like_topic(guide.get("book_claim_short", ""))
    if why:
        errs.append(f"guide.book_claim_short 不是主張句（{why}）")

    imps = guide.get("implications")
    if not isinstance(imps, list) or not (2 <= len(imps) <= 4):
        errs.append("implications 必須是 2–4 條")
    else:
        for j, p in enumerate(imps):
            w = f"implications[{j}]"
            if not isinstance(p, dict):
                errs.append(f"{w} 必須是物件")
                continue
            _len_check(p, "label", 5, w, errs)
            _len_check(p, "text", 40, w, errs)

    main = guide.get("main_ch_ids")
    if not isinstance(main, list) or not (4 <= len(main) <= 18):
        errs.append(f"main_ch_ids 必須是 4–18 章（目前 {len(main) if isinstance(main, list) else '非陣列'}）")
        main = main if isinstance(main, list) else []
    bad = [c for c in main if c not in cm]
    if bad:
        errs.append(f"main_ch_ids 含不存在的章：{'、'.join(map(str, bad))}")
    idx = [order.index(c) for c in main if c in cm]
    if idx != sorted(idx):
        errs.append("main_ch_ids 必須照原書章序排（導讀體不重排章節）")
    if len(set(main)) != len(main):
        errs.append("main_ch_ids 有重複")
    if not (8 <= len(main) <= 14):
        warn(f"主線 {len(main)} 章：60 分鐘的導讀通常 8–14 章，其餘進附錄")

    chs = guide.get("chapters")
    if not isinstance(chs, dict):
        errs.append("chapters 必須是物件 {ch_id: {...}}")
        chs = {}
    for cid in main:
        if cid not in cm:
            continue
        g = chs.get(cid)
        w = f"chapters.{cid}"
        if not isinstance(g, dict):
            errs.append(f"{w} 缺設計（主線章每一章都要有 headline / outline / visuals / story）")
            continue
        check_keys(g, ["headline", "outline", "visuals", "story"], w, errs)
        _len_check(g, "headline", 14, w, errs)
        why = looks_like_topic(g.get("headline", ""))
        if why:
            errs.append(f"{w}.headline 不是結論句（{why}）：「{g.get('headline', '')}」")
        outline = g.get("outline")
        if not isinstance(outline, list) or not (2 <= len(outline) <= 4):
            errs.append(f"{w}.outline 必須是 2–4 步")
        else:
            for j, s in enumerate(outline):
                if not isinstance(s, str) or not s.strip():
                    errs.append(f"{w}.outline[{j}] 必須是非空字串")
                elif visual_len(s) > 40:
                    errs.append(f"{w}.outline[{j}] {visual_len(s):.0f} 字 > 40")
        pts = g.get("points") or []
        if not isinstance(pts, list) or len(pts) == 1 or len(pts) > 3:
            errs.append(f"{w}.points 要嘛不放，要嘛 2–3 條（只有一條就併進 outline）")
        else:
            for j, r in enumerate(pts):
                _validate_ref(r, f"{w}.points[{j}]", cm[cid], errs, need_use=False)
        vis = g.get("visuals")
        if not isinstance(vis, list) or not (1 <= len(vis) <= 3):
            errs.append(f"{w}.visuals 必須是 1–3 張（示意圖／原圖是導讀的骨架）")
        else:
            for j, r in enumerate(vis):
                _validate_ref(r, f"{w}.visuals[{j}]", cm[cid], errs)
        if g.get("today") is not None:
            _validate_ref(g["today"], f"{w}.today", cm[cid], errs)
        stories = cm[cid]["digest"].get("stories")
        if not isinstance(stories, list):
            errs.append(f"{w}: {cid} 的 digest 還沒有 stories（先跑 03_digest.py --supplement {cid}）")
        elif not isinstance(g.get("story"), int) or not (0 <= g["story"] < len(stories)):
            errs.append(f"{w}.story={g.get('story')!r} 超出範圍（{cid} 有 {len(stories)} 則故事）——每章一定要選一則進逐字稿")

    counter = guide.get("counter")
    if not isinstance(counter, dict):
        errs.append("counter 必須是物件 {claim, points}")
    else:
        _len_check(counter, "claim", 14, "counter", errs)
        pts = counter.get("points")
        if not isinstance(pts, list) or not (2 <= len(pts) <= 4):
            errs.append("counter.points 必須是 2–4 條")
        else:
            for j, p in enumerate(pts):
                w = f"counter.points[{j}]"
                if not isinstance(p, dict):
                    errs.append(f"{w} 必須是物件")
                    continue
                _len_check(p, "label", 5, w, errs)
                _len_check(p, "text", 40, w, errs)
                if p.get("ch_id") not in cm:
                    errs.append(f"{w}.ch_id 不存在：{p.get('ch_id')}")
    return errs


def _validate_ref(r: dict, w: str, ch: dict, errs: list[str], need_use: bool = True) -> None:
    if not isinstance(r, dict):
        errs.append(f"{w} 必須是物件")
        return
    keys = [k for k in REF_KEYS if k in r]
    if len(keys) != 1:
        errs.append(f"{w} 必須恰好有一個引用鍵（{'/'.join(REF_KEYS)}），目前：{keys or '無'}")
        return
    if need_use and not (r.get("use") or "").strip():
        errs.append(f"{w}.use 必填：這張圖／這筆資料要說什麼")
    vis = r.get("visual")
    if vis is not None and vis not in VISUALS:
        errs.append(f"{w}.visual 只能是 {'/'.join(VISUALS)}，目前：{vis}")
    key = keys[0]
    val = r[key]
    d, e = ch["digest"], ch["evidence"]
    if key == "figure":
        p = Path(str(val))
        if not (ROOT / p).exists() and not p.exists():
            errs.append(f"{w}.figure 找不到檔案：{val}")
        return
    pools = {
        "kp": d.get("key_points"), "quote": d.get("quotes"), "data": d.get("data_points"),
        "story": d.get("stories"), "taiwan": e.get("taiwan_lens"), "verified": e.get("verified"),
        "chart": e.get("chart_candidates"), "extension": e.get("extensions"),
    }
    pool = pools.get(key) or []
    if not isinstance(val, int) or not (0 <= val < len(pool)):
        errs.append(f"{w}.{key}={val!r} 超出範圍（{ch['ch_id']} 只有 {len(pool)} 筆 {key}）——只能引用索引裡出現的編號")


# ==========================================================================
# 5b：藍圖
# ==========================================================================
def build_slides(guide: dict, chapters: list[dict], cfg: dict, author: dict) -> list[dict]:
    slides: list[dict] = []
    sid = [0]
    L_MAIN, L_VARIANT2, L_VARIANT3 = family_layouts()
    cm = chapter_map(chapters)
    book = cfg["book"]
    pres = cfg["presenter"]
    book_label = f"《{book.get('title_zh', '')}》"
    author_name = book.get("author", "")

    def S(**kw) -> dict:
        sid[0] += 1
        base = {
            "id": f"s{sid[0]:03d}",
            "layout": L_MAIN,
            "kind": "content",
            "role": "evidence",
            "section": None,
            "style": None,
            "title": "",
            "subtitle": None,
            "body": [],
            "chart": None,
            "video": None,
            "sources": [],
            "narration": "",
            "duration_sec": 45,
            "ch_id": None,
        }
        base.update(kw)
        slides.append(base)
        return base

    main_ids = guide["main_ch_ids"]

    # 影片：指定 after_ch 的掛在那一章之後（那章要在主線），其餘放在全書意涵之前
    vids_by_ch: dict[str, list[dict]] = {}
    loose_vids: list[dict] = []
    for v in videos():
        if v["after_ch"] in main_ids:
            vids_by_ch.setdefault(v["after_ch"], []).append(v)
        else:
            if v["after_ch"]:
                warn(f"影片「{v['title']}」的 after_ch={v['after_ch']} 不在主線，改放在全書意涵之前")
            loose_vids.append(v)

    # ---- 序幕 ----
    S(layout=L_COVER, kind="cover", role="cover", section="prologue",
      title=book.get("title_zh", ""),
      subtitle=guide["book_claim_short"],
      body=[{"level": 0, "text": f"{pres.get('dept', '')}　{pres.get('name', '')}"},
            {"level": 0, "text": pres.get("date", "")}],
      duration_sec=20)

    _author_slides(S, author, author_name, L_MAIN, L_BLANK)

    S(layout=L_MAIN, kind="content", role="summary", section="prologue", style="labeled",
      title=guide["book_claim_short"],
      subtitle=guide["why_now"],
      body=[{"label": "主張", "text": guide["book_claim"]},
            {"label": "證據", "text": f"{TODO}全書最有力的一筆證據，帶數字"},
            {"label": "意義", "text": guide["implication_short"]}],
      sources=[{"label": f"{book_label}{author_name}"}], duration_sec=60)

    # 章序地圖：分部（有官方分部就用）+ 主線章
    parts = (author.get("book") or {}).get("parts") or []
    part_of: dict[str, str] = {}
    for k, part in enumerate(parts, start=1):
        for n in part.get("chapter_ns") or []:
            part_of[str(n)] = part.get("title_zh") or part.get("title_en") or f"Part {k}"
    items = []
    seen_parts: set[str] = set()
    for cid in main_ids:
        c = cm[cid]
        pt = part_of.get(_chapter_no(c["title"]), "")
        if pt and pt not in seen_parts:
            items.append({"level": 0, "text": pt})
            seen_parts.add(pt)
        items.append({"level": 1 if pt else 0, "text": f"{c['no_label']} {c['display']}".strip()})
    for i in range(0, max(1, len(items)), 8):
        S(layout=L_TOC, kind="toc", role="map", section="prologue",
          title="今天的路線" if i == 0 else "今天的路線（續）",
          body=items[i:i + 8], sources=[{"label": book_label}], duration_sec=30 if i == 0 else 15)

    # ---- 每一章（原書章序）----
    cur_part: str | None = None
    for cid in main_ids:
        c = cm[cid]
        d = c["digest"]
        g = guide["chapters"][cid]
        pt = part_of.get(_chapter_no(c["title"]), "")
        if pt and pt != cur_part:
            cur_part = pt
            S(layout=L_DIVIDER, kind="divider", role="part", section="part",
              title=pt, duration_sec=15)

        note = " ".join(x for x in (c["no_label"], c["title_en"] if c["display"] != c["title_en"] else "") if x)
        story = (d.get("stories") or [])[g["story"]]
        S(layout=L_DIVIDER, kind="divider", role="divider", section=cid, ch_id=cid,
          title=c["display"], note=note or None, duration_sec=15,
          image_hint=story_image_hint(story, c))

        src_label = chapter_source_label(c, _page_ref(d), book_label)
        S(layout=L_MAIN, kind="content", role="outline", section=cid, ch_id=cid, style="chain",
          title=g["headline"],
          subtitle=_clip(d.get("one_line", ""), 21),
          body=[{"text": s} for s in g["outline"]],
          sources=[{"label": src_label}],
          story_hint=(f"{story.get('who', '')}（{story.get('when', '')}）：{story.get('what', '')}"
                      f"｜轉折：{story.get('turn', '')}｜作者用它證明：{story.get('so_what', '')}"
                      f"（{story.get('page_ref', '')}）"),
          duration_sec=60)

        for r in g.get("visuals") or []:
            _ref_slide(r, c, S, book_label, author_name, L_MAIN, L_VARIANT2, role="evidence")

        pts = g.get("points") or []
        if pts:
            body = []
            for r in pts:
                kp = d["key_points"][r["kp"]]
                body.append({"label": f"{TODO}標籤", "text": _clip(f"{kp.get('point', '')}：{kp.get('book_evidence', '')}", 40)})
            refs = "、".join(sorted({d["key_points"][r["kp"]].get("page_ref", "") for r in pts if d["key_points"][r["kp"]].get("page_ref")}))
            S(layout=L_MAIN, kind="content", role="evidence", section=cid, ch_id=cid, style="labeled",
              title=f"{TODO}結論句", subtitle=f"{TODO}這章的重點",
              body=body, sources=[{"label": chapter_source_label(c, refs, book_label)}], duration_sec=45)

        if g.get("today") is not None:
            _ref_slide(g["today"], c, S, book_label, author_name, L_MAIN, L_VARIANT2, role="today")

        for v in vids_by_ch.get(cid, []):
            _video_slide(S, v, cid)

    for v in loose_vids:
        _video_slide(S, v, None)

    # ---- 全書意涵 ----
    S(layout=L_VARIANT2, kind="content", role="implication", section="implication", style="labeled",
      title=guide["implication_short"],
      subtitle="對長期投資的意義",
      body=[{"label": p["label"], "text": p["text"]} for p in guide["implications"][:3]],
      sources=[{"label": f"{book_label}全書"}], duration_sec=60)
    if len(guide["implications"]) > 3:
        S(layout=L_VARIANT2, kind="content", role="implication", section="implication", style="labeled",
          title=f"{guide['implication_short']}（續）", subtitle="對長期投資的意義",
          body=[{"label": p["label"], "text": p["text"]} for p in guide["implications"][3:]],
          sources=[{"label": f"{book_label}全書"}], duration_sec=40)

    # ---- 反方 ----
    counter = guide["counter"]
    S(layout=L_DIVIDER, kind="divider", role="counter", section="counter", title=counter["claim"], duration_sec=15)
    pts = counter["points"]
    per_page = 2 if len(pts) == 4 else 3
    for i in range(0, len(pts), per_page):
        chunk = pts[i:i + per_page]
        refs = sorted({chapter_source_label(cm[p["ch_id"]], _page_ref(cm[p["ch_id"]]["digest"]), "")
                       for p in chunk})
        S(layout=L_VARIANT3, kind="content", role="counter", section="counter", style="labeled",
          title=counter["claim"] if i == 0 else f"{counter['claim']}（續）",
          subtitle=f"{TODO}這些弱點加起來代表什麼",
          body=[{"label": p["label"], "text": p["text"]} for p in chunk],
          sources=[{"label": f"{book_label}" + "、".join(refs)}],
          duration_sec=60)

    # ---- 結語 ----
    S(layout=L_CLOSING, kind="closing", role="closing", section="closing", title=guide["closing"], duration_sec=30)

    # ---- 祝賀頁：主線的最後一頁，附錄排在它後面 ----
    wish = ((cfg.get("deck") or {}).get("closing_wish") or "業績長紅").strip()
    if wish:
        S(layout=L_CLOSING, kind="wish", role="wish", section="closing", title=wish, duration_sec=10)

    # ---- 附錄：沒進主線的章 ----
    appendix = [c for c in chapters if c["ch_id"] not in main_ids]
    if appendix:
        S(layout=L_DIVIDER, kind="divider", role="appendix", section="appendix", title="附錄：備用頁", duration_sec=0)
    for c in appendix:
        d = c["digest"]
        kp0 = (d.get("key_points") or [{}])[0]
        dps = d.get("data_points") or []
        body = [{"label": "主張", "text": _clip(d.get("thesis", ""), 40)},
                {"label": "證據", "text": _clip(kp0.get("book_evidence", ""), 40)}]
        if dps:
            body.append({"label": "數字", "text": _clip(f"{dps[0].get('claim', '')}：{dps[0].get('value', '')}", 40)})
        S(layout=L_VARIANT3, kind="content", role="appendix", section="appendix", ch_id=c["ch_id"], style="labeled",
          title=_clip(d.get("one_line", "") or c["display"], 14),
          subtitle=_clip(f"{c['no_label']} {c['display']}".strip(), 21),
          body=body,
          sources=[{"label": chapter_source_label(c, _page_ref(d), book_label)}],
          duration_sec=0)
    return slides


def _chapter_no(title: str) -> str:
    m = re.match(r"^\s*(?:第\s*)?([0-9]+)\s*[章:：.．\-—]", (title or "").strip())
    return str(int(m.group(1))) if m else ""


# 人名可能帶重音（Frédéric），不能只吃 A-Za-z，否則會被切成「Fr」
_LATIN_NAME = re.compile(r"[A-ZÀ-Þ][A-Za-zÀ-ÿ.'\-]{2,}(?:\s+[A-ZÀ-Þ][A-Za-zÀ-ÿ.'\-]{2,})*")


def story_image_hint(story: dict, chapter: dict) -> dict:
    """由這一章選的故事，直接組出「該去搜什麼圖」。

    使用者的需求是「建議搜尋什麼圖片放上去讓我們可以去加工」，
    所以關鍵字要能直接貼進搜尋框：中文一組、英文一組，再標建議來源。
    圖檔本身不抓——雲端的對外連線是白名單，機構網站幾乎全被擋。
    """
    who = (story.get("who") or "").strip()
    where = (story.get("where") or "").strip()
    when = (story.get("when") or "").strip()
    en_names = [x for x in _LATIN_NAME.findall(who + " " + (story.get("what") or ""))
                if len(x) >= 4]
    en = " ".join(dict.fromkeys(en_names[:2])) or (chapter.get("title_en") or "")
    zh_who = re.split(r"[（(]", who, 1)[0].strip()
    zh_where = re.split(r"[，,]", where, 1)[0].strip()
    return {
        "what": f"{zh_who}｜{where}｜{when}".strip("｜"),
        "keywords_zh": "、".join(x for x in (zh_who, zh_where, when) if x),
        "keywords_en": (f"{en} historical photograph" if en else "").strip(),
        "source": "Wikimedia Commons（先看授權）／機構官網／圖書館數位典藏",
        "use": "章名頁籤右側，開場講故事時的背景圖",
    }


def _author_slides(S, author: dict, author_name: str, L_MAIN: int, L_BLANK: int) -> None:
    """作者是誰：背景／立場／為什麼寫 → 生涯與著作時間軸 → 評價與批評。全部來自 04_author.json。"""
    a = author.get("author") or {}
    if not a:
        S(layout=L_MAIN, kind="content", role="author", section="prologue", style="labeled",
          title=author_name or f"{TODO}作者", subtitle=f"{TODO}一句話定位作者",
          body=[{"label": "背景", "text": f"{TODO}（跑 04_research.py --author）"},
                {"label": "立場", "text": TODO}, {"label": "為什麼寫", "text": TODO}],
          sources=[{"label": f"{TODO}來源"}], duration_sec=45)
        return

    def src(items: list[dict], n: int = 3) -> list[dict]:
        out, seen = [], set()
        for it in items:
            s = _src(it)
            key = s.get("url") or s["label"]
            if key in seen or s["label"].startswith("【待填"):
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= n:
                break
        return out or [{"label": f"{TODO}來源"}]

    bg = a.get("background") or []
    stance = a.get("stance") or []
    why = a.get("why_this_book") or {}
    name_zh = (a.get("name_zh") or "").strip()
    S(layout=L_MAIN, kind="content", role="author", section="prologue", style="labeled",
      title=_clip(a.get("name") or author_name, 14),
      subtitle=_clip(name_zh or (bg[0].get("text") if bg else ""), 21) or f"{TODO}一句話定位作者",
      body=[{"label": "背景", "text": _clip(bg[0].get("text", "") if bg else "", 40) or TODO},
            {"label": "立場", "text": _clip(stance[0].get("text", "") if stance else "", 40) or TODO},
            {"label": "為什麼寫", "text": _clip(why.get("text", ""), 40) or TODO}],
      sources=src([x for x in (bg[:1] + stance[:1] + [why]) if x]),
      duration_sec=45)

    events = []
    for it in a.get("career") or []:
        events.append((_year_of(it.get("when")), {"when": str(it.get("when", "")), "what": _clip(it.get("what", ""), 24), "note": ""}, it))
    for it in a.get("works") or []:
        events.append((_year_of(it.get("year")), {"when": str(it.get("year", "")), "what": _clip(f"《{it.get('title_en', '')}》", 24),
                                                  "note": _clip(it.get("note", ""), 20)}, it))
    events.sort(key=lambda x: x[0])
    picked = events[:6]
    if len(events) > 6:
        info(f"作者時間軸只放前 6 個事件（共 {len(events)}），其餘寫進逐字稿")
    if picked:
        S(layout=L_BLANK, kind="chart", role="author", section="prologue",
          title=f"{TODO}生涯一句話（≤20 字）", subtitle="生涯與著作",
          timeline={"events": [ev for _, ev, _ in picked]}, body=[],
          sources=src([it for _, _, it in picked]), duration_sec=45)

    rec = a.get("reception") or []
    crit = a.get("critics") or []
    if rec or crit:
        awards = [w for w in (a.get("works") or []) if re.search(r"獎|Prize|Award|入圍|Notable", w.get("note", ""))]
        body = [{"label": "評價", "text": _clip(rec[0].get("text", "") if rec else "", 40) or TODO},
                {"label": "批評", "text": _clip(crit[0].get("text", "") if crit else "", 40) or TODO}]
        extra: list[dict] = []
        if awards:
            body.append({"label": "獎項", "text": _clip(f"{awards[0].get('title_en', '')}：{awards[0].get('note', '')}", 40)})
            extra = awards[:1]
        elif len(rec) > 1:
            body.append({"label": "書評", "text": _clip(rec[1].get("text", ""), 40)})
            extra = rec[1:2]
        S(layout=L_MAIN, kind="content", role="author", section="prologue", style="labeled",
          title=f"{TODO}評價的一句話結論", subtitle="掌聲與批評都要聽",
          body=body, sources=src(rec[:1] + crit[:1] + extra), duration_sec=45)


def _year_of(v) -> int:
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else 9999


# --------------------------------------------------------------------------
def _ref_slide(r: dict, c: dict, S, book_label: str, author: str,
               L_MAIN: int, L_VARIANT2: int, role: str = "evidence") -> dict:
    """一筆引用 → 一頁骨架。素材全部從 digest / evidence 原文帶進來，
    文字上的【待填】留給 Claude 潤飾（絕不在這裡生內容）。"""
    cid = c["ch_id"]
    key = next(k for k in REF_KEYS if k in r)
    val = r[key]
    vis = r.get("visual")
    d, e = c["digest"], c["evidence"]
    use = (r.get("use") or "").strip()
    base = dict(role=role, section=cid, ch_id=cid, duration_sec=45)
    src_book = lambda ref: [{"label": chapter_source_label(c, ref, book_label)}]  # noqa: E731

    if key == "figure":
        return S(layout=L_BLANK, kind="chart", **base,
                 title=f"{TODO}圖的結論", subtitle=f"{TODO}圖名＋時間範圍＋單位",
                 image={"path": str(val)}, body=[],
                 sources=[_fig_source(str(val), c, book_label)])

    if key == "story":
        st = d["stories"][val]
        cap = [{"text": _clip(st.get("so_what", ""), 40)}]
        head = f"{st.get('who', '')}，{st.get('when', '')}"
        if vis == "flow":
            return S(layout=L_BLANK, kind="chart", **base, title=f"{TODO}結論句",
                     subtitle=_clip(head, 30), body=cap, sources=src_book(st.get("page_ref", "")),
                     flow={"type": "chain", "per_row": 3,
                           "nodes": [{"label": f"{TODO}第 {i + 1} 步", "note": ""} for i in range(3)]})
        if vis == "prose":
            return S(layout=L_MAIN, kind="content", style="prose", **base,
                     title=f"{TODO}結論句", subtitle=_clip(head, 21),
                     body=[{"text": _clip(st.get("what", ""), 90)},
                           {"text": _clip(f"{st.get('turn', '')}。{st.get('so_what', '')}", 90)}],
                     sources=src_book(st.get("page_ref", "")))
        return S(layout=L_BLANK, kind="chart", **base, title=f"{TODO}結論句",
                 subtitle=_clip(head, 30), body=[], sources=src_book(st.get("page_ref", "")),
                 timeline={"events": [{"when": st.get("when", ""), "what": f"{TODO}起點", "note": ""},
                                      {"when": TODO, "what": f"{TODO}轉折", "note": ""},
                                      {"when": TODO, "what": f"{TODO}結局", "note": ""}]})

    if key == "quote":
        q = d["quotes"][val]
        text = (q.get("text") or "").strip()
        is_en = sum(ch.isascii() for ch in text) > len(text) * 0.6
        return S(layout=L_BLANK, kind="chart", **{**base, "duration_sec": 20},
                 title="", subtitle=None,
                 quote={"text": text, "zh": f"{TODO}中譯" if is_en else "",
                        "attrib": f"{author}（{chapter_source_label(c, q.get('page_ref', ''), book_label)}）"},
                 sources=src_book(q.get("page_ref", "")))

    if key == "data":
        dp = d["data_points"][val]
        value = str(dp.get("value", "")).strip()
        short = visual_len(value) <= 10
        if vis in (None, "stat"):
            return S(layout=L_BLANK, kind="chart", **{**base, "duration_sec": 20},
                     title="", subtitle=None,
                     stat={"value": value if short else f"{TODO}數字",
                           "label": _clip(dp.get("claim", ""), 30),
                           "note": (f"{dp.get('as_of', '')}" if short else f"{value}（{dp.get('as_of', '')}）")},
                     sources=src_book(dp.get("page_ref", "")))
        return S(layout=L_MAIN, kind="content", style="labeled", **base,
                 title=f"{TODO}結論句", subtitle=_clip(dp.get("claim", ""), 21),
                 body=[{"label": "書中", "text": _clip(f"{dp.get('claim', '')}：{value}", 40)},
                       {"label": "時點", "text": _clip(str(dp.get("as_of", "")), 40)},
                       {"label": "今天", "text": f"{TODO}最新值（04_evidence verified）"}],
                 sources=src_book(dp.get("page_ref", "")))

    if key == "kp":
        kp = d["key_points"][val]
        src = src_book(kp.get("page_ref", ""))
        cap = [{"text": _clip(use, 40)}]
        if vis == "flow":
            return S(layout=L_BLANK, kind="chart", **base, title=f"{TODO}結論句",
                     subtitle=_clip(kp.get("point", ""), 30), body=cap, sources=src,
                     flow={"type": "chain", "per_row": 3,
                           "nodes": [{"label": f"{TODO}步驟 {i + 1}", "note": ""} for i in range(3)]})
        if vis == "timeline":
            return S(layout=L_BLANK, kind="chart", **base, title=f"{TODO}結論句",
                     subtitle=_clip(kp.get("point", ""), 30), body=[], sources=src,
                     timeline={"events": [{"when": TODO, "what": TODO, "note": ""} for _ in range(3)]})
        if vis == "table":
            return S(layout=L_MAIN, kind="chart", **base, title=f"{TODO}結論句",
                     subtitle=_clip(kp.get("point", ""), 21), body=[], sources=src,
                     table={"columns": [f"{TODO}欄一", f"{TODO}欄二"], "widths": [4, 6],
                            "rows": [[_clip(kp.get("book_evidence", ""), 40), TODO]]})
        if vis == "split":
            return S(layout=L_MAIN, kind="chart", **base, title=f"{TODO}結論句",
                     subtitle=_clip(kp.get("point", ""), 21), body=cap, sources=src,
                     split={"left": {"title": f"{TODO}左欄", "items": [_clip(kp.get("book_evidence", ""), 30)]},
                            "right": {"title": f"{TODO}右欄", "accent": True, "items": [TODO]}})
        if vis == "chain":
            return S(layout=L_MAIN, kind="content", style="chain", **base,
                     title=f"{TODO}結論句", subtitle=_clip(kp.get("point", ""), 21),
                     body=[{"text": f"{TODO}第一步"}, {"text": f"{TODO}第二步"},
                           {"text": _clip(kp.get("book_evidence", ""), 40)}],
                     sources=src)
        if vis == "prose":
            return S(layout=L_MAIN, kind="content", style="prose", **base,
                     title=f"{TODO}結論句", subtitle=_clip(kp.get("point", ""), 21),
                     body=[{"text": _clip(kp.get("elaboration", ""), 90)},
                           {"text": _clip(kp.get("book_evidence", ""), 90)}],
                     sources=src)
        return S(layout=L_MAIN, kind="content", style="labeled", **base,
                 title=f"{TODO}結論句", subtitle=_clip(kp.get("point", ""), 21),
                 body=[{"label": "機制", "text": f"{TODO}一句講清楚機制"},
                       {"label": "書中", "text": _clip(kp.get("book_evidence", ""), 40)},
                       {"label": "今天", "text": f"{TODO}最新數字或台灣對照（04_evidence）"}],
                 sources=src)

    if key == "taiwan":
        t = e["taiwan_lens"][val]
        if vis == "split":
            return S(layout=L_VARIANT2, kind="chart", **base,
                     title=f"{TODO}結論句", subtitle=_clip(t.get("angle", ""), 21),
                     body=[{"text": _clip(use, 40)}],
                     split={"left": {"title": "書中", "items": [f"{TODO}書怎麼說"]},
                            "right": {"title": "台灣", "accent": True,
                                      "items": [_clip(t.get("insight", ""), 40), _clip(t.get("supporting_data", ""), 40)]}},
                     sources=[_src(t)])
        return S(layout=L_VARIANT2, kind="content", style="labeled", **base,
                 title=f"{TODO}結論句", subtitle=_clip(t.get("angle", ""), 21),
                 body=[{"label": "書說", "text": f"{TODO}書中對應的說法"},
                       {"label": "台灣", "text": _clip(t.get("insight", ""), 40)},
                       {"label": "數字", "text": _clip(t.get("supporting_data", ""), 40)}],
                 sources=[_src(t)])

    if key == "verified":
        v = e["verified"][val]
        if vis in (None, "table"):
            return S(layout=L_MAIN, kind="chart", **base,
                     title=f"{TODO}結論句", subtitle=_clip(v.get("book_claim", ""), 21),
                     body=[], sources=[_src(v), {"label": chapter_source_label(c, "", book_label)}],
                     table={"columns": ["書中", f"最新（{v.get('as_of', '')}）"], "widths": [5, 5],
                            "rows": [[_clip(v.get("book_claim", ""), 40), _clip(v.get("current_fact", ""), 48)]]})
        return S(layout=L_MAIN, kind="content", style="labeled", **base,
                 title=f"{TODO}結論句", subtitle=_clip(v.get("book_claim", ""), 21),
                 body=[{"label": "書中", "text": _clip(v.get("book_claim", ""), 40)},
                       {"label": "最新", "text": _clip(v.get("current_fact", ""), 40)},
                       {"label": "意義", "text": _clip(use, 40)}],
                 sources=[_src(v), {"label": chapter_source_label(c, "", book_label)}])

    if key == "chart":
        ch = e["chart_candidates"][val]
        return S(layout=L_BLANK, kind="chart", **base,
                 title=f"{TODO}圖的結論",
                 subtitle=_clip(f"{ch.get('title', '')}（{ch.get('unit', '')}）", 30),
                 chart={"type": ch.get("chart_type", "bar"), "title": ch.get("title", ""),
                        "unit": ch.get("unit", ""), "data": ch.get("data", [])},
                 body=[], sources=[_src(ch)])

    x = e["extensions"][val]                      # extension
    return S(layout=L_VARIANT2, kind="content", style="labeled", **base,
             title=f"{TODO}結論句", subtitle=_clip(x.get("title", ""), 21),
             body=[{"label": "書沒講", "text": _clip(x.get("content", ""), 40)},
                   {"label": "為什麼", "text": _clip(use, 40)},
                   {"label": "數字", "text": f"{TODO}帶一個具體數字"}],
             sources=[_src(x)])


def _video_slide(S, v: dict, ch_id: str | None) -> dict:
    """分享會現場要播的影片頁：標題 + 起訖時間碼 + QR code（06_build_pptx 產圖）。"""
    span = f"{format_timecode(v['start'])}–{format_timecode(v['end'])}"
    body = [{"level": 0, "text": f"播放片段 {span}（{format_timecode(v['duration_sec'])}）"}]
    if v["note"]:
        body.append({"level": 0, "text": _clip(v["note"], 60)})
    return S(layout=L_BLANK, kind="video", role="video", section=ch_id or "prologue",
             title=_clip(v["title"], 18), subtitle="現場播放", body=body,
             video={"url": v["url"], "start": v["start"], "end": v["end"], "span": span, "note": v["note"]},
             sources=[{"label": "影片連結見頁面 QR code", "url": v["url"]}],
             duration_sec=max(30, v["duration_sec"] + 20), ch_id=ch_id)


# --------------------------------------------------------------------------
def _fig_source(path: str, c: dict, book_label: str) -> dict:
    """圖檔的資料來源：書中原圖寫章名與 PDF 頁碼；機構原圖從 09_srcfigs/manifest.json 取。"""
    p = Path(path)
    if "08_bookfigs" in path:
        m = re.match(r"p(\d+)", p.stem)
        ref = f"書中圖表，PDF p.{int(m.group(1))}（請核對原書頁碼）" if m else "書中圖表"
        return {"label": chapter_source_label(c, ref, book_label)}
    man = WORK / "09_srcfigs" / "manifest.json"
    if man.exists():
        try:
            data = read_json(man)
        except Exception:  # noqa: BLE001
            data = None
        items = list(data.values()) if isinstance(data, dict) else (data or [])
        for it in items:
            if isinstance(it, dict) and str(it.get("path") or "").endswith(p.name):
                out = _src({**it, "source_url": it.get("page_url") or it.get("figure_url")})
                if out["label"].startswith("【待填"):
                    out["label"] = f"{TODO}機構名（YYYY/MM）"
                return out
    return {"label": f"{TODO}機構名（YYYY/MM）"}


def _src(obj: dict) -> dict:
    """外部來源 label 用「機構名（YYYY/MM）」，url 另存供 QA 檢查。"""
    title = (obj.get("source_title") or "").strip()
    as_of = (obj.get("as_of") or "").strip().replace("-", "/")
    label = f"{title}（{as_of}）" if (title and as_of) else title
    out = {"label": label or "【待填來源】"}
    if obj.get("source_url"):
        out["url"] = obj["source_url"]
    return out


def _page_ref(d: dict) -> str:
    for kp in d.get("key_points", []):
        if kp.get("page_ref"):
            return kp["page_ref"]
    return ""


def _clip(text: str, max_visual: int) -> str:
    """骨架用：放得下就原文，放不下就標【待填】＋截斷——不讓截斷的句子悄悄過關。"""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    if visual_len(text) <= max_visual:
        return text
    return TODO + _truncate(text, max_visual - 4)


def _truncate(text: str, max_visual: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if visual_len(text) <= max_visual:
        return text
    out = ""
    for ch in text:
        if visual_len(out + ch) > max_visual - 1:
            break
        out += ch
    return out.rstrip("，、。；：") + "…"


# --------------------------------------------------------------------------
def assign_durations(slides: list[dict]) -> list[dict]:
    """把講述頁的總時長配到目標區間（總長 − 5 分鐘 Q&A）。

    只配速、不裁頁：節奏頁（頁籤／引言／大數字／影片）不縮放；內容太多時等比壓縮並警告；
    內容太少時最多放大 1.3 倍且不超過 pacing.page_max_sec。附錄頁不計時。
    """
    lo, hi = talk_minutes_range()
    target_sec = int(((lo + hi) / 2) * 60)
    pacing = load_project().get("pacing") or {}
    page_max = int(pacing.get("page_max_sec", 120))
    talk = [s for s in slides if not is_appendix(s)]

    def _fixed(s: dict) -> bool:
        return s["kind"] in ("video", "divider") or bool(s.get("quote") or s.get("stat"))

    fixed = [s for s in talk if _fixed(s)]
    flex = [s for s in talk if not _fixed(s)]
    fixed_sec = sum(s["duration_sec"] for s in fixed)
    cur = sum(s["duration_sec"] for s in flex)
    if cur <= 0 or not flex:
        return slides
    budget = target_sec - fixed_sec
    if budget < cur * 0.35:
        warn(f"影片與節奏頁佔掉 {format_timecode(fixed_sec)}，剩給講述的時間不足。考慮減少影片或拉長 deck.minutes。")
        budget = max(budget, int(cur * 0.35))
    scale = budget / cur
    if scale < 0.6:
        warn(f"內容量約為時段的 {1 / scale:.1f} 倍。時間是指引不是門檻：與其壓縮每一頁，"
             "不如把次要的章移出主線（進附錄），或拉長 deck.minutes。")
    if scale > 1.3:
        info(f"內容比時段少（可放大 {scale:.1f} 倍），只放大到 1.3 倍，其餘留給互動；要填滿就多挑幾章進主線。")
        scale = 1.3
    for s in flex:
        s["duration_sec"] = min(page_max, max(20, int(round(s["duration_sec"] * scale / 5) * 5)))
    return slides


def print_summary(slides: list[dict]) -> None:
    talk = [s for s in slides if not is_appendix(s)]
    by_role: dict[str, int] = {}
    for s in slides:
        by_role[s.get("role", "?")] = by_role.get(s.get("role", "?"), 0) + 1
    print()
    print("  頁面組成")
    print("  " + "─" * 52)
    for role, n in by_role.items():
        print(f"  {ROLE_LABELS.get(role, role):<22} {n:>3} 頁")
    print("  " + "─" * 52)
    secs = sum(s["duration_sec"] for s in talk)
    n_app = len(slides) - len(talk)
    print(f"  {'講述頁合計':<22} {len(talk):>3} 頁   預估 {format_timecode(secs)}"
          + (f"　（另有附錄 {n_app} 頁不計時）" if n_app else ""))
    vis_keys = ("image", "flow", "timeline", "table", "split", "quote", "stat", "chart")
    n_vis = sum(1 for s in talk if any(s.get(k) for k in vis_keys))
    print(f"  {'視覺頁':<22} {n_vis:>3} 頁   佔講述頁 {n_vis / max(1, len(talk)):.0%}")
    print()
    lo, hi = target_slides()
    if not (lo <= len(talk) <= hi):
        info(f"講述頁 {len(talk)} 頁，參考區間 {lo}–{hi}（只是參考，不裁頁；逐字稿寫完看總時長）")
    todo = sum(1 for s in slides if TODO in _blob(s))
    if todo:
        info(f"{todo} 頁含{TODO}標記，Claude 依 prompts/outline.md 潤飾；08_qa 對殘留的{TODO}判 FAIL")


def _blob(s: dict) -> str:
    import json
    return json.dumps({k: v for k, v in s.items() if k != "narration"}, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
