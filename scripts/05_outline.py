#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 — 投影片藍圖 work/05_deck.json。

把 03_digest + 04_evidence 合成藍圖，算好頁數預算與版面分派。
文案潤飾由 Claude Code 依 prompts/outline.md 接手，這支只負責「骨架與配額」。

頁數預算（規劃書 §7.1，60 分鐘 / 45–60 頁）：
    封面              標題 (0)                    1
    全書地圖/Agenda   目錄 (1)                    1–2
    為什麼讀這本書    內頁1-1 (4)                 1
    每章：章節頁籤    頁籤 (2)                    1 × N
    每章：核心主張    內頁1-1 (4)                 1 × N
    每章：論點展開    內頁1-1 (4)                 1–2 × N
    每章：台灣對照    內頁2-1 (6) 或 空白內頁 (9) 1 × N
    全書綜合          內頁3-1 (8)                 2–3
    可落地的行動      內頁3-1 (8)                 1–2
    我的異議          內頁2-1 (6)                 1
    結語 / Q&A        結尾 (10)                   1

若書超過 10 章，自動合併相鄰章節成「主題群組」，每群組共用一個頁籤頁。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECK_JSON, DIGEST, EVIDENCE, LAYOUT_FAMILIES, chapter_files, die, ensure_dirs,
    estimate_lines, family_layouts, format_timecode, info, layout_family, limits,
    load_project, ok, parse_chapter_file, read_json, step, talk_minutes_range,
    target_slides,
    tone_directive, tone_key, videos, visual_len, warn, write_json,
)

# 版面 index（config/fh_template_spec.json）
# 固定的：封面／目錄／頁籤／空白內頁／結尾
L_COVER, L_TOC, L_DIVIDER = 0, 1, 2
L_BLANK = 9         # 空白內頁（整頁圖表與影片頁）
L_CLOSING = 10
# 內頁三組（主力／次要／第三）由 config/project.yaml 的 deck.layout_family 決定，
# 在 build_slides() 內取得，不寫死。

MAX_CHAPTERS_BEFORE_GROUPING = 10


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 5：投影片藍圖")
    ap.add_argument("--force", action="store_true", help="覆寫既有的 05_deck.json")
    ap.add_argument("--dry-run", action="store_true", help="只印頁數預算，不寫檔")
    args = ap.parse_args()

    ensure_dirs()
    cfg = load_project()

    if DECK_JSON.exists() and not args.force and not args.dry_run:
        die(f"{DECK_JSON} 已存在。要重建請加 --force\n"
            "（注意：--force 會蓋掉你手改過的文案。改稿迴圈請直接改 deck.json 再跑 Stage 6–8）")

    chapters = load_chapters()
    if not chapters:
        die("沒有可用的章節資料。請先跑 Stage 2–4。")

    step(f"Stage 5 藍圖生成（{len(chapters)} 章）")

    groups = group_chapters(chapters)
    if len(groups) != len(chapters):
        ok(f"超過 {MAX_CHAPTERS_BEFORE_GROUPING} 章，已合併為 {len(groups)} 個主題群組")

    slides = build_slides(chapters, groups, cfg)
    slides = trim_to_budget(slides)
    slides = assign_durations(slides, cfg)

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
            "layout_family_label": LAYOUT_FAMILIES[layout_family()]["label"],
            "tone": tone_key(),
            "tone_directive_slide": tone_directive("slide"),
            "tone_directive_narration": tone_directive("narration"),
            "chapters": [{"ch_id": c["ch_id"], "title": c["title"]} for c in chapters],
            "groups": [{"name": g["name"], "ch_ids": g["ch_ids"]} for g in groups],
        },
        "slides": slides,
    }

    print_budget(slides, cfg)

    if args.dry_run:
        info("--dry-run：未寫檔")
        return 0

    for sl in deck["slides"]:
        sl.pop("_trim", None)          # 內部裁切標記，不寫進 deck.json
    write_json(DECK_JSON, deck)
    ok(f"藍圖 → {DECK_JSON}（{len(slides)} 頁）")
    print()
    info("→ 停：接下來是最省時的修改點。")
    info("   1) Claude Code 依 prompts/outline.md 潤飾 work/05_deck.json 文案")
    info("   2) 你直接讀 work/05_deck.json 改字")
    info("   3) python scripts/08_qa.py --check-deck  驗證文案規則")
    return 0


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
            warn(f"{ch_id} 缺 evidence，台灣對照頁會留空殼（跑 04_research.py 補上）")
        out.append({
            "ch_id": ch_id,
            "title": digest.get("title") or meta.get("title") or ch_id,
            "pages": meta.get("pages"),
            "digest": digest,
            "evidence": evidence,
        })
    return out


def group_chapters(chapters: list[dict]) -> list[dict]:
    """超過 10 章就合併相鄰章節成主題群組，每群組共用一個頁籤頁。"""
    n = len(chapters)
    if n <= MAX_CHAPTERS_BEFORE_GROUPING:
        return [{"name": c["title"], "ch_ids": [c["ch_id"]], "chapters": [c]} for c in chapters]

    target = MAX_CHAPTERS_BEFORE_GROUPING
    size = -(-n // target)  # ceil
    groups = []
    for i in range(0, n, size):
        chunk = chapters[i:i + size]
        groups.append({
            "name": _group_name(chunk),
            "ch_ids": [c["ch_id"] for c in chunk],
            "chapters": chunk,
        })
    return groups


def _group_name(chunk: list[dict]) -> str:
    """群組名：取首章標題去掉「第N章」前綴，加「等 N 章」。"""
    first = re.sub(r"^\s*第\s*[0-9一二三四五六七八九十百]+\s*[章節課篇回講]\s*", "",
                   chunk[0]["title"]).strip()
    if len(chunk) == 1:
        return first or chunk[0]["title"]
    return f"{first} 等 {len(chunk)} 章"


# ==========================================================================
def build_slides(chapters: list[dict], groups: list[dict], cfg: dict) -> list[dict]:
    slides: list[dict] = []
    sid = [0]
    L_MAIN, L_VARIANT2, L_VARIANT3 = family_layouts()

    def S(**kw) -> dict:
        sid[0] += 1
        base = {
            "id": f"s{sid[0]:03d}",
            "layout": L_MAIN,
            "kind": "content",
            "title": "",
            "subtitle": None,
            "body": [],
            "chart": None,
            "video": None,
            "sources": [],
            "narration": "",
            "duration_sec": 70,
            "ch_id": None,
            # 頁數超出預算時的裁切優先序：數字越大越先被拿掉；0 = 不可裁
            "_trim": 0,
        }
        base.update(kw)
        slides.append(base)
        return base

    book = cfg["book"]
    pres = cfg["presenter"]
    book_label = f"《{book.get('title_zh', '')}》"
    pages_per_ch = cfg["deck"].get("pages_per_chapter", [3, 5])

    # 現場要播的影片：有指定 after_ch 的掛在該章之後，其餘統一放在全書綜合之前
    all_vids = videos()
    ch_ids = {c["ch_id"] for c in chapters}
    vids_by_ch: dict[str, list[dict]] = {}
    loose_vids: list[dict] = []
    for v in all_vids:
        if v["after_ch"] in ch_ids:
            vids_by_ch.setdefault(v["after_ch"], []).append(v)
        else:
            if v["after_ch"]:
                warn(f"影片「{v['title']}」指定的 after_ch={v['after_ch']} 不存在，"
                     "改放在全書綜合之前")
            loose_vids.append(v)

    # ---- 1. 封面 ----
    S(layout=L_COVER, kind="cover",
      title=book.get("title_zh", ""),
      subtitle=book.get("title_en") or None,
      body=[{"level": 0, "text": f"{pres.get('dept','')}　{pres.get('name','')}"},
            {"level": 0, "text": pres.get("date", "")}],
      duration_sec=30)

    # ---- 2. 全書地圖 / Agenda ----
    toc_items = [{"level": 0, "text": g["name"]} for g in groups]
    # 目錄超過 8 條就拆兩頁
    for i in range(0, max(1, len(toc_items)), 8):
        chunk = toc_items[i:i + 8]
        S(layout=L_TOC, kind="toc",
          title="今天的地圖" if i == 0 else "今天的地圖（續）",
          body=chunk, sources=[{"label": book_label}], duration_sec=45)

    # ---- 3. 為什麼讀這本書 ----
    S(layout=L_MAIN, kind="content",
      title="為什麼是這本書",
      subtitle="它解決了我們手上哪個具體問題",
      body=[{"level": 0, "text": "【待填】這本書處理的問題"},
            {"level": 0, "text": "【待填】我們現在遇到的狀況"},
            {"level": 0, "text": "【待填】讀完可以帶走什麼"}],
      sources=[{"label": f"{book_label}{book.get('author','')}／{book.get('publisher_year','')}"}],
      duration_sec=90)

    # ---- 4. 每章 ----
    for g in groups:
        # 4a. 章節頁籤（每群組一張）
        S(layout=L_DIVIDER, kind="divider", title=g["name"],
          ch_id=g["ch_ids"][0], duration_sec=25)

        for ch in g["chapters"]:
            # S() 本身已把頁面 append 進 slides，這裡不要再 extend 一次
            _chapter_slides(ch, S, book_label, pages_per_ch, L_MAIN, L_VARIANT2)
            # 這一章之後要播的影片
            for v in vids_by_ch.get(ch["ch_id"], []):
                _video_slide(S, v)

    # ---- 4b. 沒指定章節的影片 ----
    for v in loose_vids:
        _video_slide(S, v)

    # ---- 5. 全書綜合 ----
    S(layout=L_VARIANT3, kind="content",
      title="把八章接起來看",
      subtitle="全書真正在講的一件事",
      body=[{"level": 0, "text": "【待填】貫穿全書的主線"},
            {"level": 0, "text": "【待填】各章之間的因果關係"},
            {"level": 0, "text": "【待填】最反直覺的一點"}],
      sources=[{"label": book_label}], duration_sec=100)
    S(layout=L_VARIANT3, kind="content", _trim=3,
      title="這本書沒回答的問題",
      subtitle="留白的地方才是我們要想的",
      body=[{"level": 0, "text": "【待填】書的適用邊界"},
            {"level": 0, "text": "【待填】台灣市場的差異"}],
      sources=[{"label": book_label}], duration_sec=80)

    # ---- 6. 可落地的行動 ----
    S(layout=L_VARIANT3, kind="content",
      title="明天就能做的三件事",
      subtitle="不是原則，是動作",
      body=[{"level": 0, "text": "【待填】動作一（誰、做什麼、多久一次）"},
            {"level": 0, "text": "【待填】動作二"},
            {"level": 0, "text": "【待填】動作三"}],
      sources=[{"label": book_label}], duration_sec=100)

    # ---- 7. 我的異議 ----
    counters = [c["digest"].get("counterpoint", "") for c in chapters
                if c["digest"].get("counterpoint")]
    S(layout=L_VARIANT2, kind="content",
      title="我不同意的地方",
      subtitle="全書最站不住腳的三個論點",
      body=_fit_bullets([_truncate(cp, 30) for cp in counters]) or
           [{"level": 0, "text": "【待填】異議"}],
      sources=[{"label": book_label}], duration_sec=110)

    # ---- 8. 結語 / Q&A ----
    S(layout=L_CLOSING, kind="closing", title="Q & A", duration_sec=30)

    return slides


def _chapter_slides(ch: dict, S, book_label: str, pages_per_ch: list[int],
                    L_MAIN: int, L_VARIANT2: int) -> list[dict]:
    """單一章節的內頁：核心主張 1 + 論點展開 1–2 + 台灣對照／圖表 1（+ 過期數據 1）。

    S() 會直接把頁面寫進外層 slides；回傳值只給本函式內部判斷「這章已經幾頁了」，
    呼叫端不要再 extend 一次（會變兩倍頁數）。
    """
    d, e = ch["digest"], ch["evidence"]
    ch_id = ch["ch_id"]
    kps = d.get("key_points", [])
    min_p, max_p = (pages_per_ch + [3, 5])[:2]

    made = []

    # --- 核心主張頁 ---
    body = [{"level": 0, "text": _truncate(d.get("one_line", ""), 40)}]
    # §7.3：每頁至少一個「具體物」。優先塞一筆書中數據，沒有才用引句。
    dps = d.get("data_points") or []
    if dps:
        dp0 = dps[0]
        body.append({"level": 0, "text": _truncate(
            f"{dp0.get('claim','')}：{dp0.get('value','')}"
            + (f"（{dp0.get('as_of','')}）" if dp0.get("as_of") else ""), 40)})
    for q in d.get("quotes", [])[:1]:
        body.append({"level": 1, "text": _truncate(q.get("text", ""), 60)})
    src = [{"label": f"{book_label} {_page_ref(d)}"}]
    made.append(S(layout=L_MAIN, kind="content", ch_id=ch_id,
                  title=_truncate(d.get("thesis", ""), 18),
                  subtitle=_truncate(d.get("one_line", ""), 28),
                  body=body, sources=src, duration_sec=80))

    # --- 論點展開頁（依版面容量打包，最多 2 頁）---
    # 要點縮到 30 字（40 是上限不是目標），且只有第一條掛第二層書證——
    # prompts/outline.md 明訂「不要每條都掛一個第二層」，每條都掛必爆 8 行上限。
    blocks = []
    for j, kp in enumerate(kps):
        blk = [{"level": 0, "text": _truncate(kp.get("point", ""), 30)}]
        ev = kp.get("book_evidence", "")
        if ev and j == 0:
            blk.append({"level": 1, "text": _truncate(ev, 30)})
        blocks.append((kp, blk))

    chunks = _pack_blocks(blocks, max_pages=2) or [[]]
    for i, chunk in enumerate(chunks):
        body = [ln for _, blk in chunk for ln in blk]
        refs = [kp.get("page_ref", "") for kp, _ in chunk if kp.get("page_ref")]
        made.append(S(layout=L_MAIN, kind="content", ch_id=ch_id, _trim=(1 if i else 0),
                      title="【待填】這一頁的結論句",
                      subtitle="【待填】為什麼／所以呢",
                      body=body or [{"level": 0, "text": "【待填】"}],
                      sources=[{"label": f"{book_label} {refs[0] if refs else _page_ref(d)}"}],
                      duration_sec=90))

    # --- 台灣對照／數據頁 ---
    charts = e.get("chart_candidates", [])
    tw = e.get("taiwan_lens", [])
    if charts:
        c = charts[0]
        made.append(S(layout=L_BLANK, kind="chart", ch_id=ch_id,
                      title=_truncate(c.get("title", ""), 18),
                      subtitle=f"單位：{c.get('unit', '')}" if c.get("unit") else None,
                      body=[],
                      chart={"type": c.get("chart_type", "bar"),
                             "title": c.get("title", ""),
                             "unit": c.get("unit", ""),
                             "data": c.get("data", [])},
                      sources=[_src(c)], duration_sec=90))
    elif tw:
        t = tw[0]
        body = [{"level": 0, "text": _truncate(t.get("insight", ""), 40)}]
        if t.get("supporting_data"):
            body.append({"level": 1, "text": _truncate(t["supporting_data"], 60)})
        made.append(S(layout=L_VARIANT2, kind="content", ch_id=ch_id,
                      title=_truncate(t.get("angle", ""), 18),
                      subtitle="台灣市場的對照",
                      body=body, sources=[_src(t)], duration_sec=90))
    else:
        made.append(S(layout=L_VARIANT2, kind="content", ch_id=ch_id,
                      title="【待填】台灣市場對照",
                      subtitle="【待填】這章的觀點在台灣會怎麼呈現",
                      body=[{"level": 0, "text": "【待填】缺 evidence，請跑 04_research.py"}],
                      sources=[], duration_sec=90))

    # --- 過期數據頁（規劃書 §6：outdated 一定要放進投影片）---
    outdated = [v for v in e.get("verified", []) if v.get("status") == "outdated"]
    if outdated and len(made) < max_p:
        v = outdated[0]
        made.append(S(layout=L_VARIANT2, kind="content", ch_id=ch_id, _trim=2,
                      title="書寫的數字已經變了",
                      subtitle=_truncate(v.get("book_claim", ""), 28),
                      body=[{"level": 0, "text": _truncate(f"書中：{v.get('book_claim','')}", 40)},
                            {"level": 0, "text": _truncate(f"最新：{v.get('current_fact','')}", 40)}],
                      sources=[_src(v)], duration_sec=80))

    return made





def _video_slide(S, v: dict) -> dict:
    """分享會現場要播的影片頁：標題 + 起訖時間碼 + QR code（06_build_pptx 產圖）。

    duration_sec 直接是播放長度，逐字稿只寫進場與收尾的過場詞，
    所以 narration 的字數檢查對影片頁另有標準（見 08_qa.check_narration）。
    """
    span = f"{format_timecode(v['start'])}–{format_timecode(v['end'])}"
    body = [{"level": 0, "text": f"播放片段 {span}（{format_timecode(v['duration_sec'])}）"}]
    if v["note"]:
        body.append({"level": 1, "text": _truncate(v["note"], 60)})
    return S(layout=L_BLANK, kind="video",
             title=_truncate(v["title"], 18),
             subtitle="現場播放",
             body=body,
             video={"url": v["url"], "start": v["start"], "end": v["end"],
                    "span": span, "note": v["note"]},
             sources=[{"label": "影片連結見頁面 QR code", "url": v["url"]}],
             # 播放時間 + 前後過場約 20 秒
             duration_sec=max(30, v["duration_sec"] + 20),
             ch_id=v["after_ch"])


def _fit_bullets(texts: list[str]) -> list[dict]:
    """把一串第一層要點收斂到版面容量內（行數與總字數兩個上限都要守）。"""
    lim = limits()
    max_lines = int(lim.get("max_body_lines", 8))
    max_chars = int(lim.get("body_max_chars_per_slide", 160))
    hi = int((lim.get("bullets_l1_range") or [3, 5])[1])

    out: list[dict] = []
    for t in texts:
        if not t:
            continue
        cand = out + [{"level": 0, "text": t}]
        if len(cand) > hi:
            break
        if out and (estimate_lines(cand, 24) > max_lines
                    or sum(visual_len(b["text"]) for b in cand) > max_chars):
            break
        out = cand
    return out


def _pack_blocks(blocks: list[tuple[dict, list[dict]]], max_pages: int = 2) -> list[list]:
    """把 key_point 區塊裝進頁面，同時守住行數與總字數上限。

    05_outline 要先守住版面容量，06_build_pptx 的 fit_body() 才是最後一道保險；
    不這樣做的話 deck.json 永遠會被 08_qa 的「溢排」判 FAIL。
    """
    lim = limits()
    max_lines = int(lim.get("max_body_lines", 8))
    max_chars = int(lim.get("body_max_chars_per_slide", 160))

    pages: list[list] = []
    cur: list = []
    for item in blocks:
        cand = cur + [item]
        body = [ln for _, blk in cand for ln in blk]
        if cur and (estimate_lines(body, 24) > max_lines
                    or sum(visual_len(b["text"]) for b in body) > max_chars):
            pages.append(cur)
            cur = [item]
            if len(pages) >= max_pages:
                break
        else:
            cur = cand
    if cur and len(pages) < max_pages:
        pages.append(cur)
    return pages[:max_pages]


def _src(obj: dict) -> dict:
    """外部來源 label 用「機構名（YYYY/MM）」，url 另存供 QA 檢查。"""
    title = (obj.get("source_title") or "").strip()
    as_of = (obj.get("as_of") or "").strip().replace("-", "/")
    label = f"{title}（{as_of}）" if as_of else title
    out = {"label": label or "【待填來源】"}
    if obj.get("source_url"):
        out["url"] = obj["source_url"]
    return out


def _page_ref(d: dict) -> str:
    for kp in d.get("key_points", []):
        if kp.get("page_ref"):
            return kp["page_ref"]
    return ""


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


def trim_to_budget(slides: list[dict]) -> list[dict]:
    """頁數超出預算就依 _trim 優先序拿掉可選頁面。

    短講（例如 30–45 分鐘）不該產出 60 頁再叫使用者自己刪。
    優先序：3 =「這本書沒回答的問題」→ 2 = 過期數據頁 → 1 = 第二張論點展開頁。
    _trim = 0 的頁面（封面、頁籤、核心主張、圖表、影片…）永不裁切。
    """
    lo, hi = target_slides()
    before = len(slides)
    for level in (3, 2, 1):
        i = 0
        while len(slides) > hi and i < len(slides):
            if slides[i].get("_trim") == level and len(slides) - 1 >= lo:
                slides.pop(i)
            else:
                i += 1
    if len(slides) < before:
        ok(f"依 {lo}–{hi} 頁的預算裁掉 {before - len(slides)} 頁可選內容")
    return slides


def assign_durations(slides: list[dict], cfg: dict) -> list[dict]:
    """把總時長壓到目標區間（規劃書 §9：總長 55 分鐘，留 5 分鐘 Q&A）。

    影片頁的秒數是實際播放長度，不參與縮放；其餘頁面分攤剩下的時間。
    """
    lo, hi = talk_minutes_range()
    target_sec = int(((lo + hi) / 2) * 60)

    fixed = [s for s in slides if s["kind"] == "video"]
    flex = [s for s in slides if s["kind"] != "video"]
    fixed_sec = sum(s["duration_sec"] for s in fixed)

    budget = target_sec - fixed_sec
    cur = sum(s["duration_sec"] for s in flex)
    if cur <= 0 or not flex:
        return slides
    if budget < cur * 0.35:
        warn(f"影片佔掉 {fixed_sec // 60}:{fixed_sec % 60:02d}，"
             f"剩給講述的時間不足。考慮減少影片或拉長 deck.minutes。")
        budget = max(budget, int(cur * 0.35))

    scale = budget / cur
    for s in flex:
        s["duration_sec"] = max(20, int(round(s["duration_sec"] * scale / 5) * 5))
    return slides


def print_budget(slides: list[dict], cfg: dict) -> None:
    lo, hi = target_slides()
    total = len(slides)
    by_kind: dict[str, int] = {}
    for s in slides:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1

    print()
    print("  頁數預算")
    print("  " + "─" * 52)
    names = {"cover": "封面", "toc": "全書地圖 / Agenda", "divider": "章節頁籤",
             "content": "內容頁", "chart": "圖表頁", "video": "影片頁",
             "closing": "結語 / Q&A"}
    for k, n in by_kind.items():
        print(f"  {names.get(k, k):<22} {n:>3} 頁")
    print("  " + "─" * 52)
    secs = sum(s["duration_sec"] for s in slides)
    print(f"  {'合計':<22} {total:>3} 頁   預估 {secs // 60}:{secs % 60:02d}")
    print()

    if total < lo:
        warn(f"只有 {total} 頁，低於目標 {lo}–{hi} 頁。"
             "考慮在 config/project.yaml 調高 pages_per_chapter，或章節拆得太粗。")
    elif total > hi:
        warn(f"共 {total} 頁，高於目標 {lo}–{hi} 頁。"
             "考慮調低 pages_per_chapter，或讓 05_outline.py 合併更多章節。")
    else:
        ok(f"{total} 頁，落在目標 {lo}–{hi} 頁區間內")

    todo = sum(1 for s in slides if "【待填】" in str(s.get("title", "")) + str(s.get("body", "")))
    if todo:
        info(f"{todo} 頁含【待填】標記，需要 Claude Code 依 prompts/outline.md 潤飾")


if __name__ == "__main__":
    sys.exit(main())
