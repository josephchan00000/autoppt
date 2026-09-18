#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 7 — 逐字稿 Word（規劃書 §9）。

    - 表格式版面：左欄頁碼 + 投影片主標，右欄逐字稿
    - 每章起始插入分頁
    - 頁首寫累計時間軸（「第 12 頁 / 累計 14:30」）
    - 文末附「預期提問與備答」一節（從各章 counterpoint 生成）

逐字稿本身由 Claude Code 依 prompts/narration.md 寫進 deck.json 的 narration 欄位，
這支腳本只負責排版成 docx。narration 空白的頁會標【待填】並在最後統計。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECK_JSON, DIGEST, OUTPUT, SCRIPT_JSON, die, ensure_dirs, info, load_project,
    narration_chars, ok, read_json, safe_filename, step, warn, write_json,
)

from docx import Document  # noqa: E402
from docx.enum.section import WD_SECTION  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

EA_FONT = "微軟正黑體"
FH_RED = RGBColor(0xB8, 0x28, 0x37)
FH_GRAY = RGBColor(0x93, 0x93, 0x96)
FH_DARK = RGBColor(0x26, 0x26, 0x27)


def set_ea(run, name: str = EA_FONT) -> None:
    """python-docx 同樣只設 latin，中文要設 w:eastAsia。"""
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {})
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:ascii"), "Arial")
    rFonts.set(qn("w:hAnsi"), "Arial")


def para(container, text: str = "", size: int = 11, bold: bool = False,
         color: RGBColor | None = None, align=None, space_after: int = 6):
    p = container.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    if text:
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = bold
        if color is not None:
            r.font.color.rgb = color
        set_ea(r)
    return p


def mmss(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 7：逐字稿 Word")
    ap.add_argument("--deck", default=str(DECK_JSON))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    ensure_dirs()
    deck_path = Path(args.deck)
    if not deck_path.exists():
        die(f"找不到藍圖：{deck_path}，請先跑 05_outline.py")

    deck = read_json(deck_path)
    meta, slides = deck.get("meta", {}), deck.get("slides", [])
    if not slides:
        die("deck.json 沒有任何 slides")

    cfg = load_project()
    out = Path(args.out) if args.out else OUTPUT / _out_name(meta, cfg)

    step(f"Stage 7 逐字稿（{len(slides)} 頁）")

    doc = Document()
    _setup_styles(doc)
    _cover(doc, meta, slides, cfg)
    stats = _body(doc, meta, slides)
    _qa_section(doc, meta)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))

    # 同步輸出 06_script.json，供 QA 與改稿使用
    write_json(SCRIPT_JSON, {
        "meta": meta,
        "total_sec": stats["total_sec"],
        "total_chars": stats["chars"],
        "slides": [{"id": s.get("id"), "title": s.get("title"),
                    "duration_sec": s.get("duration_sec", 0),
                    "narration": s.get("narration", ""),
                    "chars": narration_chars(s.get("narration", ""))} for s in slides],
    })

    ok(f"逐字稿 → {out}")
    ok(f"逐字稿索引 → {SCRIPT_JSON}")
    total = stats["total_sec"]
    lo, hi = cfg.get("narration", {}).get("total_minutes_range", [50, 58])
    info(f"總時長 {mmss(total)}（目標 {lo}–{hi} 分鐘）／全文 {stats['chars']:,} 字")
    if stats["empty"]:
        warn(f"{stats['empty']} 頁的 narration 仍空白 —— "
             "請 Claude Code 依 prompts/narration.md 寫進 deck.json 後重跑")
    if not (lo * 60 <= total <= hi * 60):
        warn(f"總時長 {mmss(total)} 不在 {lo}–{hi} 分鐘區間，請調整 deck.json 的 duration_sec")
    print()
    info("下一步：python scripts/08_qa.py --all")
    return 0


def _out_name(meta: dict, cfg: dict) -> str:
    title = safe_filename(meta.get("book_title") or cfg["book"].get("title_zh") or "書名", 30)
    return f"FH_{title}_逐字稿.docx"


def _setup_styles(doc: Document) -> None:
    st = doc.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), EA_FONT)
    for sec in doc.sections:
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(2.2)
        sec.right_margin = Cm(2.2)


def _cover(doc: Document, meta: dict, slides: list[dict], cfg: dict) -> None:
    para(doc, "", size=11, space_after=60)
    para(doc, meta.get("book_title", ""), size=26, bold=True, color=FH_RED,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    if meta.get("book_title_en"):
        para(doc, meta["book_title_en"], size=13, color=FH_GRAY,
             align=WD_ALIGN_PARAGRAPH.CENTER, space_after=30)
    para(doc, "分享會逐字稿", size=16, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=40)

    total = sum(s.get("duration_sec", 0) for s in slides)
    for line in (
        f"講者：{meta.get('dept', '')}　{meta.get('name') or meta.get('presenter', '')}",
        f"日期：{meta.get('date', '')}",
        f"原著：{meta.get('author', '')}",
        f"篇幅：{len(slides)} 頁 ／ 預估 {mmss(total)}"
        f"（目標 {cfg['deck'].get('minutes', 60)} 分鐘，含 Q&A）",
    ):
        para(doc, line, size=12, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)

    doc.add_page_break()


def _body(doc: Document, meta: dict, slides: list[dict]) -> dict:
    ch_titles = {c["ch_id"]: c["title"] for c in meta.get("chapters", [])}
    cum = 0
    empty = 0
    chars = 0
    cur_ch = "__none__"
    first = True

    for i, s in enumerate(slides, start=1):
        ch_id = s.get("ch_id")
        # 每章起始插入分頁 + 章名標題
        if ch_id and ch_id != cur_ch:
            cur_ch = ch_id
            if not first:
                doc.add_page_break()
            para(doc, ch_titles.get(ch_id, ch_id), size=16, bold=True, color=FH_RED,
                 space_after=10)
        first = False

        dur = int(s.get("duration_sec", 0))
        narration = (s.get("narration") or "").strip()
        if not narration:
            narration = "【待填】依 prompts/narration.md 寫入 deck.json 的 narration 欄位"
            empty += 1
        else:
            chars += narration_chars(narration)

        # 頁首時間軸
        para(doc, f"第 {i} 頁 / 累計 {mmss(cum)} ／ 本頁 {dur} 秒",
             size=9, color=FH_GRAY, space_after=2)

        # 表格：左欄頁碼+主標，右欄逐字稿
        t = doc.add_table(rows=1, cols=2)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        left, right = t.rows[0].cells
        left.width = Cm(4.6)
        right.width = Cm(11.4)

        lp = left.paragraphs[0]
        lp.paragraph_format.space_after = Pt(2)
        r = lp.add_run(f"P{i}")
        r.font.size = Pt(13)
        r.bold = True
        r.font.color.rgb = FH_RED
        set_ea(r)
        p2 = left.add_paragraph()
        p2.paragraph_format.space_after = Pt(0)
        r2 = p2.add_run(s.get("title", ""))
        r2.font.size = Pt(10)
        r2.font.color.rgb = FH_DARK
        set_ea(r2)
        if s.get("subtitle"):
            p3 = left.add_paragraph()
            p3.paragraph_format.space_after = Pt(0)
            r3 = p3.add_run(s["subtitle"])
            r3.font.size = Pt(9)
            r3.font.color.rgb = FH_GRAY
            set_ea(r3)

        rp = right.paragraphs[0]
        rp.paragraph_format.space_after = Pt(0)
        rr = rp.add_run(narration)
        rr.font.size = Pt(11)
        set_ea(rr)

        para(doc, "", size=8, space_after=10)
        cum += dur

    return {"total_sec": cum, "empty": empty, "chars": chars}


def _qa_section(doc: Document, meta: dict) -> None:
    """文末附「預期提問與備答」一節（從各章 counterpoint 生成）。"""
    doc.add_page_break()
    para(doc, "預期提問與備答", size=18, bold=True, color=FH_RED, space_after=6)
    para(doc, "以下問題由各章的 counterpoint（最值得挑戰的地方）生成，"
              "請在會前補上你自己的答法。", size=10, color=FH_GRAY, space_after=14)

    rows = []
    for c in meta.get("chapters", []):
        p = DIGEST / f"{c['ch_id']}.json"
        if not p.exists():
            continue
        d = read_json(p)
        cp = (d.get("counterpoint") or "").strip()
        if cp:
            rows.append((c["title"], cp))

    if not rows:
        para(doc, "（找不到 work/03_digest/*.json，無法生成。跑完 Stage 3 後重跑本階段。）",
             size=11, color=FH_GRAY)
        return

    t = doc.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    hdr = t.rows[0].cells
    for cell, label, w in zip(hdr, ("章節", "可能被問", "我的答法"), (3.6, 6.4, 6.0)):
        cell.width = Cm(w)
        pr = cell.paragraphs[0]
        r = pr.add_run(label)
        r.bold = True
        r.font.size = Pt(11)
        r.font.color.rgb = FH_DARK
        set_ea(r)

    for title, cp in rows:
        cells = t.add_row().cells
        for cell, text, size, w in zip(
            cells,
            (title, f"「{cp}」這點你怎麼看？", ""),
            (10, 10, 10),
            (3.6, 6.4, 6.0),
        ):
            cell.width = Cm(w)
            pr = cell.paragraphs[0]
            pr.paragraph_format.space_after = Pt(2)
            r = pr.add_run(text)
            r.font.size = Pt(size)
            set_ea(r)

    para(doc, "", space_after=12)
    para(doc, "時間控制提醒", size=13, bold=True, color=FH_RED, space_after=4)
    for line in (
        "・全簡報目標 55 分鐘，留 5 分鐘 Q&A。",
        "・過半時間點（約 27 分）應該剛好講到全書中段，落後就跳過第二層補充。",
        "・章節頁籤頁只講 20–30 秒，不要在過場頁停留。",
    ):
        para(doc, line, size=10, space_after=3)


if __name__ == "__main__":
    sys.exit(main())
