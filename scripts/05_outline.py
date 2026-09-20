#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 — 論證設計 → 投影片藍圖。

5a  --thesis-prompt    印「論證設計」提示詞：全書 digest / evidence 的濃縮索引 + 規則，
                       Claude 讀完寫 work/05a_thesis.json（prompts/thesis.md）
    --validate-thesis  驗 thesis.json：欄位、字數、每筆 evidence 的編號都要對得上
5b  （預設）           由 thesis.json 生成 work/05_deck.json 骨架，文案由 Claude 依
                       prompts/outline.md 潤飾

金字塔結構：
    序幕   封面 → 執行摘要（主張／證據／意義）→ 全書地圖（N 個主張句）
    每幕   主張頁籤 → 主張頁（論證鏈）→ 證據頁 ×2–8 → 意涵頁（對長期投資）
    反方   本書站不住的地方
    結語   一句收束 + Q&A
    附錄   未進主線的章、沒用到的過期數據（不計時、不需逐字稿）

沒有頁數預算、不裁頁：品質優先。時間只在 08_qa 當 WARN。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECK_JSON, DIGEST, EVIDENCE, LAYOUT_FAMILIES, PROMPTS, ROOT, ROLE_LABELS, THESIS_JSON,
    WORK, chapter_files, check_keys, die, ensure_dirs, fail, family_layouts,
    format_timecode, info, is_appendix, layout_family, load_project, looks_like_topic, ok,
    parse_chapter_file, read_json, step, talk_minutes_range, target_slides,
    tone_directive, tone_key, tone_preset, videos, visual_len, warn, write_json,
)

# 固定版面：封面／目錄／頁籤／空白內頁／結尾（config/fh_template_spec.json）
L_COVER, L_TOC, L_DIVIDER, L_BLANK, L_CLOSING = 0, 1, 2, 9, 10

TODO = "【待填】"
PROMPT_FILE = PROMPTS / "thesis.md"

EVIDENCE_REF_KEYS = ("kp", "quote", "data", "figure", "taiwan", "verified", "chart", "extension")
VISUALS = ("image", "table", "split", "flow", "timeline", "stat", "quote", "chart",
           "labeled", "chain", "prose")


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 5：論證設計 → 藍圖")
    ap.add_argument("--thesis-prompt", action="store_true",
                    help="5a：印論證設計提示詞（Claude 讀完寫 work/05a_thesis.json）")
    ap.add_argument("--validate-thesis", action="store_true", help="驗 work/05a_thesis.json")
    ap.add_argument("--force", action="store_true", help="覆寫既有的 05_deck.json")
    ap.add_argument("--dry-run", action="store_true", help="只印頁面清單，不寫檔")
    args = ap.parse_args()

    ensure_dirs()
    cfg = load_project()
    chapters = load_chapters()
    if not chapters:
        die("沒有可用的章節資料。請先跑 Stage 2–4。")

    if args.thesis_prompt:
        return emit_thesis_prompt(chapters, cfg)

    if args.validate_thesis:
        return run_validate_thesis(chapters)

    if not THESIS_JSON.exists():
        die(f"找不到 {THESIS_JSON}\n"
            "  這一版的藍圖是從「論證設計」長出來的，不是照章節排：\n"
            "    python scripts/05_outline.py --thesis-prompt   # 印提示詞，依 prompts/thesis.md 寫 thesis.json\n"
            "    python scripts/05_outline.py --validate-thesis\n"
            "    python scripts/05_outline.py                   # 再回來產藍圖")
    thesis = read_json(THESIS_JSON)
    errs = validate_thesis(thesis, chapters)
    if errs:
        for e in errs:
            fail(e)
        die(f"thesis.json 有 {len(errs)} 項不合格，修好再產藍圖")

    if DECK_JSON.exists() and not args.force and not args.dry_run:
        die(f"{DECK_JSON} 已存在。要重建請加 --force\n"
            "（注意：--force 會蓋掉你手改過的文案。改稿迴圈請直接改 deck.json 再跑 Stage 6–8）")

    step(f"Stage 5b 藍圖生成（{len(thesis['acts'])} 幕，{len(chapters)} 章）")
    fam = LAYOUT_FAMILIES[layout_family()]
    info(f"內頁色系：{fam['label']}（內頁{layout_family()} / {layout_family()}-1）"
         f"　語氣：{tone_preset().get('label', tone_key())}")

    slides = build_slides(thesis, chapters, cfg)
    slides = assign_durations(slides)

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
                "book_claim": thesis["book_claim"],
                "book_claim_short": thesis["book_claim_short"],
                "acts": [{"id": a["id"], "claim": a["claim"], "question": a["question"],
                          "ch_ids": a["ch_ids"]} for a in thesis["acts"]],
                "counter_claim": thesis["counter"]["claim"],
                "closing": thesis["closing"],
                "appendix_ch_ids": thesis.get("appendix_ch_ids") or [],
            },
            "chapters": [{"ch_id": c["ch_id"], "title": c["title"]} for c in chapters],
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
    info("   2) 視覺頁另讀 prompts/visuals.md")
    info("   3) python scripts/08_qa.py --check-deck  驗證文案與結構")
    return 0


# ==========================================================================
# 資料載入
# ==========================================================================
def load_chapters() -> list[dict]:
    """把 02/03/04 三層資料併起來。缺 digest 的章節會被略過並警告。"""
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
        out.append({
            "ch_id": ch_id,
            "title": digest.get("title") or meta.get("title") or ch_id,
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


# ==========================================================================
# 5a：論證設計提示詞
# ==========================================================================
def emit_thesis_prompt(chapters: list[dict], cfg: dict) -> int:
    if not PROMPT_FILE.exists():
        die(f"找不到提示詞：{PROMPT_FILE}")
    tpl = PROMPT_FILE.read_text(encoding="utf-8")
    book = cfg["book"]
    figs = available_figures()
    fig_text = "\n".join(f"- `{f}`" for f in figs) if figs else \
        "（還沒抽圖：python tools/extract_book_figures.py --input input/book.pdf --out work/08_bookfigs）"
    body = (tpl.replace("{book_title}", book.get("title_zh", ""))
               .replace("{author}", book.get("author", ""))
               .replace("{n_chapters}", str(len(chapters)))
               .replace("{digest_summary}", digest_summary(chapters))
               .replace("{figures}", fig_text))
    print("=" * 78)
    print("  Stage 5a 論證設計提示詞（讀完寫 work/05a_thesis.json）")
    print("=" * 78)
    print(body)
    return 0


def _short(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if visual_len(text) <= n else _truncate(text, n)


def digest_summary(chapters: list[dict]) -> str:
    """全書濃縮索引：每章一段，每一筆素材都帶編號，thesis.json 只能引用這些編號。"""
    lines: list[str] = []
    for c in chapters:
        d, e = c["digest"], c["evidence"]
        pages = c.get("pages")
        pg = f"（p.{pages[0]}–{pages[1]}）" if isinstance(pages, (list, tuple)) and len(pages) == 2 else ""
        lines.append(f"### {c['ch_id']}  {c['title']}{pg}")
        lines.append(f"主張：{d.get('thesis', '')}")
        lines.append(f"一句話：{d.get('one_line', '')}")
        for i, kp in enumerate(d.get("key_points") or []):
            lines.append(f"論點 kp{i}　{kp.get('point', '')}｜證據：{_short(kp.get('book_evidence', ''), 70)}"
                         f"（{kp.get('page_ref', '')}）")
        for i, dp in enumerate(d.get("data_points") or []):
            lines.append(f"數據 data{i}　{_short(dp.get('claim', ''), 40)}＝{_short(str(dp.get('value', '')), 30)}"
                         f"（{dp.get('as_of', '')}，{dp.get('page_ref', '')}）")
        for i, q in enumerate(d.get("quotes") or []):
            lines.append(f"引句 quote{i}　「{_short(q.get('text', ''), 60)}」（{q.get('page_ref', '')}）")
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
# thesis.json 驗證
# ==========================================================================
def run_validate_thesis(chapters: list[dict]) -> int:
    step("驗證 work/05a_thesis.json")
    if not THESIS_JSON.exists():
        die(f"找不到 {THESIS_JSON}，先跑 --thesis-prompt")
    try:
        thesis = read_json(THESIS_JSON)
    except Exception as ex:  # noqa: BLE001
        die(f"thesis.json 不是合法 JSON：{ex}")
    errs = validate_thesis(thesis, chapters)
    if errs:
        for e in errs:
            fail(e)
        print()
        info(f"{len(errs)} 項不合格，修好再跑一次 --validate-thesis")
        return 1
    acts = thesis["acts"]
    ok(f"通過：{len(acts)} 幕，{sum(len(a['evidence']) for a in acts)} 筆證據，"
       f"{len(thesis['counter']['points'])} 條反方，附錄 {len(thesis.get('appendix_ch_ids') or [])} 章")
    for a in acts:
        info(f"  {a['id']}  {a['claim']}　← {'、'.join(a['ch_ids'])}")
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


def validate_thesis(thesis: dict, chapters: list[dict]) -> list[str]:
    errs: list[str] = []
    if not isinstance(thesis, dict):
        return ["thesis.json 最外層必須是物件"]
    cm = chapter_map(chapters)
    check_keys(thesis, ["book_claim", "book_claim_short", "why_now", "implication",
                        "acts", "counter", "closing"], "thesis", errs)
    if errs:
        return errs

    _len_check(thesis, "book_claim", 40, "thesis", errs)
    _len_check(thesis, "book_claim_short", 14, "thesis", errs)
    _len_check(thesis, "why_now", 21, "thesis", errs)
    _len_check(thesis, "implication", 40, "thesis", errs)
    _len_check(thesis, "closing", 14, "thesis", errs)
    why = looks_like_topic(thesis.get("book_claim_short", ""))
    if why:
        errs.append(f"thesis.book_claim_short 不是主張句（{why}）")

    acts = thesis.get("acts")
    if not isinstance(acts, list) or not (3 <= len(acts) <= 5):
        errs.append(f"acts 必須是 3–5 幕（目前 {len(acts) if isinstance(acts, list) else '非陣列'}）")
        acts = acts if isinstance(acts, list) else []

    used_ch: set[str] = set()
    seen_ids: set[str] = set()
    for i, a in enumerate(acts):
        w = f"acts[{i}]"
        check_keys(a, ["id", "claim", "question", "support", "evidence", "implication", "ch_ids"],
                   w, errs)
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id", ""))
        if not aid or aid in seen_ids:
            errs.append(f"{w}.id 必須唯一且非空")
        seen_ids.add(aid)
        _len_check(a, "claim", 14, w, errs)
        _len_check(a, "question", 21, w, errs)
        _len_check(a, "implication", 40, w, errs)
        why = looks_like_topic(a.get("claim", ""))
        if why:
            errs.append(f"{w}.claim 不是主張句（{why}）：「{a.get('claim', '')}」")

        sup = a.get("support")
        if not isinstance(sup, list) or not (2 <= len(sup) <= 4):
            errs.append(f"{w}.support 必須是 2–4 步論證鏈")
        else:
            for j, s in enumerate(sup):
                if not isinstance(s, str) or not s.strip():
                    errs.append(f"{w}.support[{j}] 必須是非空字串")
                elif visual_len(s) > 40:
                    errs.append(f"{w}.support[{j}] {visual_len(s):.0f} 字 > 40")

        ch_ids = a.get("ch_ids")
        if not isinstance(ch_ids, list) or not ch_ids:
            errs.append(f"{w}.ch_ids 必須至少列一章")
            ch_ids = []
        for cid in ch_ids:
            if cid not in cm:
                errs.append(f"{w}.ch_ids 含不存在的章 {cid}")
        used_ch.update(c for c in ch_ids if c in cm)

        ev = a.get("evidence")
        if not isinstance(ev, list) or not (2 <= len(ev) <= 8):
            errs.append(f"{w}.evidence 必須是 2–8 筆")
            ev = ev if isinstance(ev, list) else []
        for j, r in enumerate(ev):
            _validate_ref(r, f"{w}.evidence[{j}]", cm, ch_ids, errs)

    counter = thesis.get("counter")
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

    appendix = thesis.get("appendix_ch_ids") or []
    if not isinstance(appendix, list):
        errs.append("appendix_ch_ids 必須是陣列（可為空）")
        appendix = []
    for cid in appendix:
        if cid not in cm:
            errs.append(f"appendix_ch_ids 含不存在的章 {cid}")
        elif cid in used_ch:
            errs.append(f"{cid} 已經進主線，不要同時放附錄")
    missing = [c["ch_id"] for c in chapters if c["ch_id"] not in used_ch and c["ch_id"] not in appendix]
    if missing:
        errs.append("這些章沒被任何一幕用到、也不在 appendix_ch_ids："
                    + "、".join(missing) + "（每一章都要有去處，不能無聲消失）")
    return errs


def _validate_ref(r: dict, w: str, cm: dict, act_ch_ids: list[str], errs: list[str]) -> None:
    if not isinstance(r, dict):
        errs.append(f"{w} 必須是物件")
        return
    keys = [k for k in EVIDENCE_REF_KEYS if k in r]
    if len(keys) != 1:
        errs.append(f"{w} 必須恰好有一個引用鍵（{'/'.join(EVIDENCE_REF_KEYS)}），目前：{keys or '無'}")
        return
    if not (r.get("use") or "").strip():
        errs.append(f"{w}.use 必填：這筆證據撐住論證鏈的哪一步")
    vis = r.get("visual")
    if vis is not None and vis not in VISUALS:
        errs.append(f"{w}.visual 只能是 {'/'.join(VISUALS)}，目前：{vis}")
    cid = r.get("ch_id")
    if cid not in cm:
        errs.append(f"{w}.ch_id 不存在：{cid}")
        return
    if cid not in act_ch_ids:
        errs.append(f"{w} 引用了 {cid}，但這一幕的 ch_ids 沒列它")
    key = keys[0]
    val = r[key]
    d, e = cm[cid]["digest"], cm[cid]["evidence"]
    if key == "figure":
        p = Path(str(val))
        if not (ROOT / p).exists() and not p.exists():
            errs.append(f"{w}.figure 找不到檔案：{val}")
        return
    pools = {
        "kp": d.get("key_points"), "quote": d.get("quotes"), "data": d.get("data_points"),
        "taiwan": e.get("taiwan_lens"), "verified": e.get("verified"),
        "chart": e.get("chart_candidates"), "extension": e.get("extensions"),
    }
    pool = pools.get(key) or []
    if not isinstance(val, int) or not (0 <= val < len(pool)):
        errs.append(f"{w}.{key}={val!r} 超出範圍（{cid} 只有 {len(pool)} 筆 {key}）——只能引用索引裡出現的編號")


# ==========================================================================
# 5b：藍圖
# ==========================================================================
def build_slides(thesis: dict, chapters: list[dict], cfg: dict) -> list[dict]:
    slides: list[dict] = []
    sid = [0]
    L_MAIN, L_VARIANT2, L_VARIANT3 = family_layouts()
    cm = chapter_map(chapters)
    book = cfg["book"]
    pres = cfg["presenter"]
    book_label = f"《{book.get('title_zh', '')}》"
    author = book.get("author", "")

    def S(**kw) -> dict:
        sid[0] += 1
        base = {
            "id": f"s{sid[0]:03d}",
            "layout": L_MAIN,
            "kind": "content",
            "role": "evidence",
            "act": None,
            "style": None,
            "title": "",
            "subtitle": None,
            "body": [],
            "chart": None,
            "video": None,
            "sources": [],
            "narration": "",
            "duration_sec": 60,
            "ch_id": None,
        }
        base.update(kw)
        slides.append(base)
        return base

    # 影片：指定 after_ch 的掛在用到那一章的那一幕之後，其餘放在反方之前
    all_vids = videos()
    act_of_ch: dict[str, str] = {}
    for a in thesis["acts"]:
        for cid in a["ch_ids"]:
            act_of_ch.setdefault(cid, a["id"])
    vids_by_act: dict[str, list[dict]] = {}
    loose_vids: list[dict] = []
    for v in all_vids:
        aid = act_of_ch.get(v["after_ch"] or "")
        if aid:
            vids_by_act.setdefault(aid, []).append(v)
        else:
            if v["after_ch"]:
                warn(f"影片「{v['title']}」的 after_ch={v['after_ch']} 不在任何一幕，改放在反方之前")
            loose_vids.append(v)

    # ---- 序幕 ----
    S(layout=L_COVER, kind="cover", role="cover",
      title=book.get("title_zh", ""),
      subtitle=thesis["book_claim_short"],
      body=[{"level": 0, "text": f"{pres.get('dept', '')}　{pres.get('name', '')}"},
            {"level": 0, "text": pres.get("date", "")}],
      duration_sec=20)

    S(layout=L_MAIN, kind="content", role="summary", style="labeled",
      title=thesis["book_claim_short"],
      subtitle=thesis["why_now"],
      body=[{"label": "主張", "text": thesis["book_claim"]},
            {"label": "證據", "text": f"{TODO}全書最有力的一筆證據，帶數字"},
            {"label": "意義", "text": thesis["implication"]}],
      sources=[{"label": f"{book_label}{author}"}], duration_sec=60)

    S(layout=L_TOC, kind="toc", role="map",
      title=f"{len(thesis['acts'])} 個主張",
      body=[{"level": 0, "text": a["claim"]} for a in thesis["acts"]]
           + [{"level": 0, "text": f"反方：{thesis['counter']['claim']}"}],
      sources=[{"label": book_label}], duration_sec=30)

    # ---- 每一幕 ----
    used_refs: set[tuple] = set()
    for a in thesis["acts"]:
        aid = a["id"]
        first_ch = a["ch_ids"][0]
        S(layout=L_DIVIDER, kind="divider", role="divider", act=aid, ch_id=first_ch,
          title=a["claim"], duration_sec=15)

        refs = [cm[c].get("digest", {}) for c in a["ch_ids"] if c in cm]
        page_refs = [_page_ref(d) for d in refs]
        page_refs = [p for p in page_refs if p][:3]
        S(layout=L_MAIN, kind="content", role="claim", act=aid, ch_id=first_ch, style="chain",
          title=a["claim"], subtitle=a["question"],
          body=[{"text": s} for s in a["support"]],
          sources=[{"label": f"{book_label} {'、'.join(page_refs)}".strip()}],
          duration_sec=60)

        for r in a["evidence"]:
            _evidence_slide(r, a, cm, S, book_label, author, L_MAIN, L_VARIANT2)
            key = next(k for k in EVIDENCE_REF_KEYS if k in r)
            used_refs.add((r["ch_id"], key, str(r[key])))

        S(layout=L_VARIANT2, kind="content", role="implication", act=aid, ch_id=first_ch,
          style="labeled",
          title=f"{TODO}結論句",
          subtitle="對長期投資的意義",
          body=[{"label": "書說", "text": _clip(a["claim"], 40)},
                {"label": "今天", "text": f"{TODO}最新資料怎麼說（04_evidence）"},
                {"label": "長期投資", "text": a["implication"]}],
          sources=[{"label": f"{book_label} {page_refs[0] if page_refs else ''}".strip()}],
          duration_sec=50)

        for v in vids_by_act.get(aid, []):
            _video_slide(S, v, aid)

    for v in loose_vids:
        _video_slide(S, v, None)

    # ---- 反方 ----
    counter = thesis["counter"]
    S(layout=L_DIVIDER, kind="divider", role="counter", title=counter["claim"], duration_sec=15)
    pts = counter["points"]
    per_page = 2 if len(pts) == 4 else 3          # 4 條拆 2+2，不要 3+1
    for i in range(0, len(pts), per_page):
        chunk = pts[i:i + per_page]
        S(layout=L_VARIANT3, kind="content", role="counter", style="labeled",
          title=counter["claim"] if i == 0 else f"{counter['claim']}（續）",
          subtitle=f"{TODO}這些弱點加起來代表什麼",
          body=[{"label": p["label"], "text": p["text"]} for p in chunk],
          sources=[{"label": f"{book_label} " + "、".join(
              sorted({_page_ref(cm[p['ch_id']]['digest']) for p in chunk if _page_ref(cm[p['ch_id']]['digest'])}))}],
          duration_sec=60)

    # ---- 結語 ----
    S(layout=L_CLOSING, kind="closing", role="closing", title=thesis["closing"], duration_sec=30)

    # ---- 附錄：未進主線的章（沒用到的過期數據只提醒，不自動做表：cell 會是長句）----
    appendix = [c for c in thesis.get("appendix_ch_ids") or [] if c in cm]
    if appendix:
        S(layout=L_DIVIDER, kind="divider", role="appendix", title="附錄：備用頁", duration_sec=0)
    for cid in appendix:
        c = cm[cid]
        d = c["digest"]
        kp0 = (d.get("key_points") or [{}])[0]
        dps = d.get("data_points") or []
        body = [{"label": "主張", "text": _clip(d.get("thesis", ""), 40)},
                {"label": "證據", "text": _clip(kp0.get("book_evidence", ""), 40)}]
        if dps:
            body.append({"label": "數字", "text": _clip(
                f"{dps[0].get('claim', '')}：{dps[0].get('value', '')}", 40)})
        S(layout=L_VARIANT3, kind="content", role="appendix", ch_id=cid, style="labeled",
          title=_clip(d.get("one_line", "") or c["title"], 14),
          subtitle=_clip(c["title"], 21),
          body=body,
          sources=[{"label": f"{book_label} {_page_ref(d)}".strip()}],
          duration_sec=0)

    unused_outdated = sum(
        1 for c in chapters for i, v in enumerate(c["evidence"].get("verified") or [])
        if v.get("status") == "outdated" and (c["ch_id"], "verified", str(i)) not in used_refs)
    if unused_outdated:
        info(f"另有 {unused_outdated} 筆過期數據（04_evidence verified[status=outdated]）沒進主線；"
             "要用就在 thesis.json 引用，或潤飾時自己做成對照表放附錄")

    return slides


# --------------------------------------------------------------------------
def _evidence_slide(r: dict, act: dict, cm: dict, S, book_label: str, author: str,
                    L_MAIN: int, L_VARIANT2: int) -> dict:
    """一筆 evidence 引用 → 一頁骨架。素材全部從 digest / evidence 原文帶進來，
    文字上的【待填】留給 Claude 潤飾（絕不在這裡生內容）。"""
    aid, cid = act["id"], r["ch_id"]
    key = next(k for k in EVIDENCE_REF_KEYS if k in r)
    val = r[key]
    vis = r.get("visual")
    c = cm[cid]
    d, e = c["digest"], c["evidence"]
    use = (r.get("use") or "").strip()
    base = dict(role="evidence", act=aid, ch_id=cid, duration_sec=45)

    if key == "figure":
        return S(layout=L_BLANK, kind="chart", **base,
                 title=f"{TODO}圖的結論",
                 subtitle=f"{TODO}圖名＋時間範圍＋單位",
                 image={"path": str(val)}, body=[],
                 sources=[_fig_source(str(val), book_label)])

    if key == "quote":
        q = d["quotes"][val]
        text = (q.get("text") or "").strip()
        is_en = sum(ch.isascii() for ch in text) > len(text) * 0.6
        return S(layout=L_BLANK, kind="chart", **{**base, "duration_sec": 20},
                 title="", subtitle=None,
                 quote={"text": text, "zh": f"{TODO}中譯" if is_en else "",
                        "attrib": f"{author}（{book_label}{q.get('page_ref', '')}）"},
                 sources=[{"label": f"{book_label}{q.get('page_ref', '')}"}])

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
                     sources=[{"label": f"{book_label}{dp.get('page_ref', '')}"}])
        return S(layout=L_MAIN, kind="content", style="labeled", **base,
                 title=f"{TODO}結論句", subtitle=_clip(dp.get("claim", ""), 21),
                 body=[{"label": "書中", "text": _clip(f"{dp.get('claim', '')}：{value}", 40)},
                       {"label": "時點", "text": _clip(str(dp.get("as_of", "")), 40)},
                       {"label": "今天", "text": f"{TODO}最新值（04_evidence verified）"}],
                 sources=[{"label": f"{book_label}{dp.get('page_ref', '')}"}])

    if key == "kp":
        kp = d["key_points"][val]
        src = [{"label": f"{book_label}{kp.get('page_ref', '')}"}]
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
                                      "items": [_clip(t.get("insight", ""), 40),
                                                _clip(t.get("supporting_data", ""), 40)]}},
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
                     body=[], sources=[_src(v), {"label": book_label}],
                     table={"columns": ["書中", f"最新（{v.get('as_of', '')}）"], "widths": [5, 5],
                            "rows": [[_clip(v.get("book_claim", ""), 40),
                                      _clip(v.get("current_fact", ""), 48)]]})
        return S(layout=L_MAIN, kind="content", style="labeled", **base,
                 title=f"{TODO}結論句", subtitle=_clip(v.get("book_claim", ""), 21),
                 body=[{"label": "書中", "text": _clip(v.get("book_claim", ""), 40)},
                       {"label": "最新", "text": _clip(v.get("current_fact", ""), 40)},
                       {"label": "意義", "text": _clip(use, 40)}],
                 sources=[_src(v), {"label": book_label}])

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


def _video_slide(S, v: dict, act_id: str | None) -> dict:
    """分享會現場要播的影片頁：標題 + 起訖時間碼 + QR code（06_build_pptx 產圖）。

    duration_sec 直接是播放長度，逐字稿只寫進場與收尾的過場詞。
    """
    span = f"{format_timecode(v['start'])}–{format_timecode(v['end'])}"
    body = [{"level": 0, "text": f"播放片段 {span}（{format_timecode(v['duration_sec'])}）"}]
    if v["note"]:
        body.append({"level": 0, "text": _clip(v["note"], 60)})
    return S(layout=L_BLANK, kind="video", role="video", act=act_id,
             title=_clip(v["title"], 18),
             subtitle="現場播放",
             body=body,
             video={"url": v["url"], "start": v["start"], "end": v["end"],
                    "span": span, "note": v["note"]},
             sources=[{"label": "影片連結見頁面 QR code", "url": v["url"]}],
             duration_sec=max(30, v["duration_sec"] + 20),
             ch_id=v["after_ch"])


# --------------------------------------------------------------------------
def _fig_source(path: str, book_label: str) -> dict:
    """圖檔的資料來源：書中原圖寫 PDF 頁碼；機構原圖從 09_srcfigs/manifest.json 取。"""
    p = Path(path)
    if "08_bookfigs" in path:
        m = re.match(r"p(\d+)", p.stem)
        return {"label": f"{book_label}書中圖表，PDF p.{int(m.group(1))}（請核對原書頁碼）" if m
                else f"{book_label}書中圖表"}
    man = WORK / "09_srcfigs" / "manifest.json"
    if man.exists():
        try:
            data = read_json(man)
        except Exception:  # noqa: BLE001
            data = None
        items = data.get("items") if isinstance(data, dict) else data
        if isinstance(data, dict) and not isinstance(items, list):
            items = list(data.values())
        for it in items or []:
            if not isinstance(it, dict):
                continue
            if str(it.get("path") or "").endswith(p.name):
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

    這只是配速，不裁頁：
      - 節奏頁（頁籤／引言／大數字／影片）的秒數是設計值，不縮放
      - 內容太多時把其餘頁面等比壓縮，但 scale 太小就警告使用者把次要證據頁移到附錄
      - 內容比時段少時「不往上灌」：每頁最多放大到 1.3 倍且不超過 pacing.page_max_sec，
        剩下的時間留給互動，比把每一頁都拖長好
    附錄頁不計時。
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
        warn(f"影片與節奏頁佔掉 {format_timecode(fixed_sec)}，剩給講述的時間不足。"
             "考慮減少影片或拉長 deck.minutes。")
        budget = max(budget, int(cur * 0.35))
    scale = budget / cur
    if scale < 0.6:
        warn(f"內容量約為時段的 {1 / scale:.1f} 倍。時間是指引不是門檻：與其壓縮每一頁，"
             "不如把次要的證據頁移到附錄（role=appendix），或拉長 deck.minutes。")
    if scale > 1.3:
        info(f"內容比時段少（可放大 {scale:.1f} 倍），只放大到 1.3 倍，其餘留給互動；"
             "要填滿就多加證據頁，不要把每頁拖長。")
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
