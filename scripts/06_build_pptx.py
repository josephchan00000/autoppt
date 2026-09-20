#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6 — 由 work/05_deck.json 產出 PPTX。

三個最容易翻車的地方（規劃書 §12），這支腳本全部處理掉：
    1. 母片內建 11 張示範頁沒清乾淨 → delete_all_slides() 必在 add_slide 之前，且要 drop_rel
    2. 中文字型只設了 latin → 所有 run 都過 set_ea_font()，寫 <a:ea> 與 <a:cs>
    3. 版面 9 的裝飾群組 → 放圖表前移除 slide 上的 GROUP shape

文字頁的三種樣式（chain / labeled / prose）全部畫在母片原生的內文 placeholder 裡，
用 run 層級的顏色與粗體做標記，不加自建 shape，QA 的版型純度檢查因此不受影響。

用法：
    python scripts/06_build_pptx.py
    python scripts/06_build_pptx.py --deck work/05_deck.json --out output/xxx.pptx
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BODY_STYLES, CARD_GAP, CARD_H_MAX, CARD_H_MIN, CARD_MARKER_W, CARD_PAD_X,
    CARD_SIZES, CARD_TEXT_RATIO, CHAIN_GLYPHS, DECK_JSON, OUTPUT, PROSE_INDENT,
    PROSE_SIZES, PROSE_TEXT_RATIO, TEMPLATE, WORK, card_per_page, die, ensure_dirs,
    estimate_lines, fit_pt, format_timecode, info, limits, line_height_emu, load_project,
    load_spec, ok, read_json, safe_filename, step, visual_len, warn, wrapped_lines, stop,
)

from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Emu, Pt  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR  # noqa: E402
from pptx.enum.dml import MSO_LINE  # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR  # noqa: E402

EA_FONT = "微軟正黑體"
LATIN_FONT = "Arial"

# <a:ea> / <a:cs> 在 CT_TextCharacterProperties 裡有固定順序，
# 不能直接 append，否則產出的 XML 不合 schema、PowerPoint 會報修復。
_EA_SUCCESSORS = ("a:cs", "a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")
_CS_SUCCESSORS = ("a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")

SPEC = load_spec()
FH_COLORS = ["#B82837", "#939396", "#B08F6E", "#00A0E9", "#262627"]

FLOW_FILL = "E9E4DA"                   # 米白（內頁2 色系）
FLOW_LINE = "B82837"                   # 復華紅：流程圖線條、樣式標籤與序號
FLOW_TEXT = "262627"
FLOW_NOTE = "6B6B6B"

CARD_FILL = "F4F1EA"                   # 卡片底：比 FLOW_FILL 再淡一階，文字才讀得清楚
CARD_EDGE = "E0D9CC"                   # 卡片描邊
# 幾何與字級階梯在 _common 的「卡片式內文的容量模型」，QA 用同一份，不要在這裡複製


# ==========================================================================
# 必備工具函式（規劃書 §8.1）
# ==========================================================================
def delete_all_slides(prs: Presentation) -> int:
    """母片檔內建 11 張示範頁，必須先清空。python-pptx 沒有 API，要動 XML。"""
    xml_slides = prs.slides._sldIdLst
    n = 0
    for sld in list(xml_slides):
        rId = sld.get(qn("r:id"))
        prs.part.drop_rel(rId)
        xml_slides.remove(sld)
        n += 1
    return n


def add(prs: Presentation, layout_idx: int):
    return prs.slides.add_slide(prs.slide_layouts[layout_idx])


def set_ea_font(run, name: str = EA_FONT, latin: str = LATIN_FONT) -> None:
    """python-pptx 只會設 latin 字型，中文要直接插 <a:ea>。

    不設的話，在沒有裝該字型的機器上會 fallback 成新細明體。
    """
    rPr = run._r.get_or_add_rPr()
    if latin:
        rPr.get_or_add_latin().set("typeface", latin)
    for tag, succ in (("a:ea", _EA_SUCCESSORS), ("a:cs", _CS_SUCCESSORS)):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.insert_element_before(el, *succ)
        el.set("typeface", name)


def set_ph(slide, idx: int, text, size_pt: int | None = None, color: str | None = None,
           middle: bool = False, space_after_pt: int | None = None):
    """依 placeholder idx 填字，並強制設定中文字型。

    text 可以是字串，或 [{"level": 0, "text": "..."}] 這種段落陣列。
    middle=True 會垂直置中——內文條數少的時候，靠上對齊會在下半頁留一片空白，
    看起來像沒寫完；置中之後即使只有五成滿也像是刻意排的。
    """
    try:
        ph = slide.placeholders[idx]
    except KeyError:
        warn(f"版面缺少 placeholder idx={idx}，已略過")
        return None

    tf = ph.text_frame
    tf.clear()
    if middle:
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    lines = text if isinstance(text, list) else [{"level": 0, "text": text}]
    lines = [ln for ln in lines if (ln.get("text") or "").strip()]
    if not lines:
        return ph

    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = int(ln.get("level", 0))
        if space_after_pt is not None and i < len(lines) - 1:
            p.space_after = Pt(space_after_pt)
        r = p.add_run()
        r.text = ln["text"]
        if size_pt:
            r.font.size = Pt(size_pt)
        if color:
            r.font.color.rgb = RGBColor.from_string(color)
        set_ea_font(r, EA_FONT)
    return ph


def _bu_none(p) -> None:
    """明確關掉這一段的項目符號。三種樣式自帶序號或標籤，不要再出現母片的 •／–。

    <a:buNone> 在 CT_TextParagraphProperties 裡有固定位置（在 tabLst / defRPr 之前），
    直接 append 會排到 spcAft 後面而不合 schema，所以用 insert_element_before。
    """
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buNone", "a:buAutoNum", "a:buChar", "a:buBlip"):
        el = pPr.find(qn(tag))
        if el is not None:
            pPr.remove(el)
    pPr.insert_element_before(pPr.makeelement(qn("a:buNone"), {}), "a:tabLst", "a:defRPr", "a:extLst")


def set_ph_styled(slide, idx: int, body: list[dict], style: str, size_pt: int,
                  space_after_pt: int | None = None):
    """三種內文樣式（prompts/outline.md）：

        chain    ① 因為… / ② 所以… / ③ 因此…    序號用復華紅粗體
        labeled  機制　折現率貼近零…               標籤用復華紅粗體，全形空格後接說明
        prose    一到兩段短文                        沒有任何標記，段距拉開

    一律垂直置中，跟 set_ph(middle=True) 的內容頁一致。
    """
    try:
        ph = slide.placeholders[idx]
    except KeyError:
        warn(f"版面缺少 placeholder idx={idx}，已略過")
        return None
    tf = ph.text_frame
    tf.clear()
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    items = [b for b in (body or []) if (b.get("text") or "").strip()]
    if not items:
        return ph
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = 0
        p.alignment = PP_ALIGN.LEFT
        if space_after_pt is not None and i < len(items) - 1:
            p.space_after = Pt(space_after_pt)
        _bu_none(p)
        text = it["text"].strip()
        if style == "chain":
            glyph = CHAIN_GLYPHS[i] if i < len(CHAIN_GLYPHS) else "・"
            runs = [(glyph + " ", FLOW_LINE, True), (text, None, False)]
        elif style == "labeled":
            label = (it.get("label") or "").strip()
            runs = ([(label + "　", FLOW_LINE, True)] if label else []) + [(text, None, False)]
        else:                                                   # prose
            runs = [(text, None, False)]
        for txt, color, bold in runs:
            r = p.add_run()
            r.text = txt
            r.font.size = Pt(size_pt)
            if bold:
                r.font.bold = True
            if color:
                r.font.color.rgb = RGBColor.from_string(color)
            set_ea_font(r, EA_FONT)
    return ph


def _card_text(slide, left, top, w, h, text, size_pt, color=FLOW_TEXT,
               name="CardText", align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(Emu(int(left)), Emu(int(top)), Emu(int(w)), Emu(int(h)))
    tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    par = tf.paragraphs[0]
    par.alignment = align
    _bu_none(par)
    r = par.add_run()
    r.text = text
    r.font.size = Pt(size_pt)
    r.font.color.rgb = RGBColor.from_string(color)
    set_ea_font(r, EA_FONT)
    return tb


_CJK_LATIN_SP = re.compile(r"(?<=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])[ ]+(?=[A-Za-z0-9$])")
_LATIN_CJK_SP = re.compile(r"(?<=[A-Za-z0-9%)\]])[ ]+(?=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])")


def tidy_spacing(text: str) -> str:
    """刪掉中文與英數之間手打的半形空格。

    PowerPoint 與 LibreOffice 本來就會在中英交界補視覺間距，原文再打一個空格
    就會變成兩倍寬的縫，整頁看起來很鬆散（實跑《時間的代價》時整份都是這個問題）。
    英文字與英文字之間的空格不動。
    """
    if not text or " " not in text:
        return text
    return _LATIN_CJK_SP.sub("", _CJK_LATIN_SP.sub("", text))


def tidy_deck(node):
    """整份 deck 走一遍，把所有字串正規化。"""
    if isinstance(node, str):
        return tidy_spacing(node)
    if isinstance(node, list):
        return [tidy_deck(x) for x in node]
    if isinstance(node, dict):
        return {k: (v if k in ("url", "path") else tidy_deck(v)) for k, v in node.items()}
    return node


IMG_SLOT = (5990000, 2010000, 2520000, 2750000)   # 章名頁籤右側的直式空白區（EMU）


PHOTOS = WORK / "09_photos"          # 使用者自己找到的照片：<頁面 id>.jpg / .png
_YEAR = r"(?:1[0-9]{3}|20[0-9]{2})"
_YEAR_ONLY = re.compile(rf"^({_YEAR})\s*年?$")
# 「年代」不能拆：1890 年代是一個詞，挑掉 1890 只會剩「代至 1930」
_YEAR_HEAD = re.compile(rf"^({_YEAR})\s*年(?!代)\s*(.+)$")
_YEAR_SPAN = re.compile(rf"^({_YEAR}\s*[–—\-~]\s*{_YEAR})$")


def split_when(when: str) -> tuple[str, int, str]:
    """把「什麼時候」拆成（大字, 字級, 小字）。

    「1866 年 5 月 10 日」→（1866, 40,「5 月 10 日」）
    「2013–2018」→（2013–2018, 28, ""）
    「1890 年代至 1930」→ 挑不出乾淨的年份（挑掉 1890 會剩「代至 1930」），整句當一行
    """
    when = (when or "").strip()
    if not when:
        return "", 0, ""
    m = _YEAR_ONLY.match(when)
    if m:
        return m.group(1), 40, ""
    m = _YEAR_HEAD.match(when)
    if m:
        return m.group(1), 40, m.group(2).strip()
    m = _YEAR_SPAN.match(when)
    if m:
        return m.group(1).replace(" ", ""), 28, ""
    return when, 16, ""


def story_photo(slide_id: str) -> Path | None:
    """work/09_photos/<頁面 id>.(jpg|jpeg|png|webp) 有圖就用圖，沒有就畫場景卡。"""
    if not slide_id:
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        f = PHOTOS / f"{slide_id}{ext}"
        if f.exists():
            return f
    return None


def place_story_photo(slide, png: Path) -> None:
    """把照片等比裁切填滿章名頁籤右側的直式區塊。"""
    from PIL import Image

    left, top, w, h = IMG_SLOT
    with Image.open(png) as im:
        iw, ih = im.size
    # 以「填滿」為準：短邊貼齊，長邊溢出的部分用 crop 切掉
    scale = max(w / iw, h / ih)
    dw, dh = int(iw * scale), int(ih * scale)
    pic = slide.shapes.add_picture(str(png), Emu(left), Emu(top), Emu(dw), Emu(dh))
    pic.name = "StoryPhoto"
    pic.crop_left = pic.crop_right = max(0.0, (dw - w) / dw / 2)
    pic.crop_top = pic.crop_bottom = max(0.0, (dh - h) / dh / 2)
    pic.left, pic.top, pic.width, pic.height = Emu(left), Emu(top), Emu(w), Emu(h)


def draw_story_card(slide, hint: dict) -> None:
    """章名頁籤右側的「場景卡」：年份、人物、地點。

    這裡本來是一個空的虛線框，寫著「該去搜什麼圖」——交出去的檔案看起來就沒做完。
    改成直接畫一張卡：大字年份 ＋ 人物 ＋ 地點，那是待會兒口頭要講的那個故事的場景。
    故事本身不上投影片（CLAUDE.md：故事進逐字稿），卡片只負責把時空標出來。

    使用者之後找到照片，放成 work/09_photos/<頁面 id>.jpg 就會自動換成照片。
    """
    if not hint:
        return
    left, top, w, h = IMG_SLOT
    who = (hint.get("who") or "").strip()
    where = (hint.get("where") or "").strip()
    when = (hint.get("when") or "").strip()
    year, year_pt, rest = split_when(when)

    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(left), Emu(top), Emu(w), Emu(h))
    card.name = "StoryCard"
    card.fill.solid()
    card.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
    card.line.color.rgb = RGBColor.from_string(CARD_EDGE)
    card.line.width = Pt(1)
    card.shadow.inherit = False

    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(left + 120000), Emu(top + 200000),
                                  Emu(w - 240000), Emu(50800))
    band.name = "StoryRule"
    band.fill.solid()
    band.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
    band.line.fill.background()
    band.shadow.inherit = False

    def tx(y, height, text, size, color, bold=False, name="StoryText"):
        tb = slide.shapes.add_textbox(Emu(left + 110000), Emu(y), Emu(w - 220000), Emu(height))
        tb.name = name
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Emu(0)
        tf.margin_top = tf.margin_bottom = Emu(0)
        par = tf.paragraphs[0]
        par.alignment = PP_ALIGN.CENTER
        _bu_none(par)
        r = par.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = RGBColor.from_string(color)
        set_ea_font(r, EA_FONT)

    # 由上而下配預算：年份與人物先取，地點用剩下的空間，所以不會溢出卡片；
    # 最後整疊垂直置中，卡片裡不會上面擠、下面空一塊。
    inner_w = w - 220000
    gap = 150000
    # 紅線在 top+200000，卡片下緣留 160000
    area_top, area_bot = top + 380000, top + h - 160000
    budget = area_bot - area_top

    def row(txt, sizes, color, bold, name, cap):
        """排一列，回傳 (文字, 字級, 顏色, 粗體, 名稱, 高度)；cap 是這一列最多能佔多高。"""
        pt = sizes[0] if len(sizes) == 1 else fit_pt([txt], inner_w, cap, sizes)
        hh = int(wrapped_lines(txt, inner_w, pt) * line_height_emu(pt) * 1.08)
        return (txt, pt, color, bold, name, min(hh, cap))

    rows = []
    if year:
        rows.append(row(year, (year_pt,) if year_pt >= 28 else (16, 14, 12),
                        FLOW_LINE, True, "StoryYear", int(budget * 0.45)))
    if rest:
        rows.append(row(rest, (12,), FLOW_NOTE, False, "StoryText", int(budget * 0.2)))
    used = sum(r[5] for r in rows) + gap * len(rows)
    if who:
        rows.append(row(who, (20, 18, 16, 14), FLOW_TEXT, True, "StoryWho",
                        max(300000, int((budget - used) * 0.62))))
        used = sum(r[5] for r in rows) + gap * len(rows)
    if where:
        rows.append(row(where, (13, 12, 11, 10, 9), FLOW_NOTE, False, "StoryText",
                        max(260000, budget - used)))
    if not rows:
        return
    block = sum(r[5] for r in rows) + gap * (len(rows) - 1)
    y = area_top + max(0, (budget - block) // 2)
    for txt, sz, col, bold, name, hh in rows:
        tx(y, hh, txt, sz, col, bold, name)
        y += hh + gap


def _divider_visual(slide, spec: dict) -> None:
    """章名頁籤右側：使用者放了照片就用照片，沒有就畫場景卡。"""
    photo = story_photo(spec.get("id", ""))
    if photo:
        place_story_photo(slide, photo)
    else:
        draw_story_card(slide, spec.get("image_hint") or {})


def placeholder_box(slide, idx: int):
    """回傳 placeholder 的 (left, top, width, height)；沒有就回 None。"""
    try:
        ph = slide.placeholders[idx]
    except KeyError:
        warn(f"版面缺少 placeholder idx={idx}，卡片改用預設座標")
        return None
    return int(ph.left), int(ph.top), int(ph.width), int(ph.height)


def draw_cards(slide, items: list[dict], style: str,
               left: int, top: int, width: int, height: int) -> None:
    """卡片式內文（prompts/outline.md「文字頁只准三種樣式」的畫法）。

        labeled  每條一張卡，標籤做成紅底白字的圓角標籤，說明在右側
        chain    每條一張卡，左側紅色圓形序號，卡與卡之間用細線串起來
        prose    不做卡片：左側一條紅色粗線 ＋ 大字段落，像引文

    卡片高度由「可用高度 ÷ 條數」決定並夾在 CARD_H_MIN–CARD_H_MAX 之間，
    整疊置中，所以 2 條與 4 條的頁面看起來都是滿的，不會下面空一大塊。
    """
    items = [b for b in (items or []) if (b.get("text") or "").strip()]
    if not items:
        return

    if style == "prose":
        paras = [b["text"].strip() for b in items]
        inner_w = width - PROSE_INDENT
        size_pt = fit_pt(paras, inner_w, int(height * PROSE_TEXT_RATIO), PROSE_SIZES)
        need = sum(wrapped_lines(x, inner_w, size_pt) for x in paras) * line_height_emu(size_pt)
        need += 200000 * (len(paras) - 1)
        block_h = min(height, need + 120000)
        block_top = top + (height - block_h) // 2
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(left)), Emu(int(block_top)),
                                     Emu(76200), Emu(int(block_h)))
        bar.name = "ProseBar"
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
        bar.line.fill.background()
        bar.shadow.inherit = False
        tb = slide.shapes.add_textbox(Emu(int(left + 300000)), Emu(int(block_top)),
                                      Emu(int(inner_w)), Emu(int(block_h)))
        tb.name = "ProseText"
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Emu(0)
        for i, txt in enumerate(paras):
            par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            par.alignment = PP_ALIGN.LEFT
            _bu_none(par)
            if i < len(paras) - 1:
                par.space_after = Pt(16)
            r = par.add_run()
            r.text = txt
            r.font.size = Pt(size_pt)
            r.font.color.rgb = RGBColor.from_string(FLOW_TEXT)
            set_ea_font(r, EA_FONT)
        return

    n = len(items)
    card_h = (height - CARD_GAP * (n - 1)) / n
    card_h = int(max(CARD_H_MIN, min(CARD_H_MAX, card_h)))
    stack_h = card_h * n + CARD_GAP * (n - 1)
    y0 = top + max(0, (height - stack_h) // 2)

    pad_x = CARD_PAD_X
    marker_w = CARD_MARKER_W["labeled"] if style == "labeled" else CARD_MARKER_W["chain"]
    text_left = left + pad_x + marker_w + 120000
    text_w = width - pad_x * 2 - marker_w - 120000
    # 每條各自一張卡，所以只要最長的那條在單張卡裡塞得下就好；
    # 把四條的行數加總去比一張卡的高度，會讓每一頁都掉到最小字級。
    longest = max((b["text"].strip() for b in items), key=visual_len)
    size_pt = fit_pt([longest], text_w, int(card_h * CARD_TEXT_RATIO), CARD_SIZES)

    for i, it in enumerate(items):
        cy = y0 + i * (card_h + CARD_GAP)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(int(left)), Emu(int(cy)),
                                      Emu(int(width)), Emu(int(card_h)))
        card.name = "CardBox"
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor.from_string(CARD_FILL)
        card.line.color.rgb = RGBColor.from_string(CARD_EDGE)
        card.line.width = Pt(1)
        card.shadow.inherit = False
        card.adjustments[0] = 0.08
        card.text_frame.text = ""

        if style == "labeled":
            label = (it.get("label") or "").strip()
            chip_h = min(520000, int(card_h * 0.62))
            chip = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Emu(int(left + pad_x)),
                Emu(int(cy + (card_h - chip_h) / 2)), Emu(int(marker_w)), Emu(int(chip_h)))
            chip.name = "CardChip"
            chip.fill.solid()
            chip.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
            chip.line.fill.background()
            chip.shadow.inherit = False
            chip.adjustments[0] = 0.18
            ctf = chip.text_frame
            ctf.word_wrap = True
            ctf.vertical_anchor = MSO_ANCHOR.MIDDLE
            ctf.margin_left = ctf.margin_right = Emu(36000)
            cp = ctf.paragraphs[0]
            cp.alignment = PP_ALIGN.CENTER
            _bu_none(cp)
            cr = cp.add_run()
            cr.text = label
            cr.font.size = Pt(18 if visual_len(label) <= 4 else 16)
            cr.font.bold = True
            cr.font.color.rgb = RGBColor.from_string("FFFFFF")
            set_ea_font(cr, EA_FONT)
        else:                                             # chain：圓形序號
            d = min(560000, int(card_h * 0.56))
            cx = left + pad_x + (marker_w - d) // 2
            circ = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(cx)),
                                          Emu(int(cy + (card_h - d) / 2)), Emu(int(d)), Emu(int(d)))
            circ.name = "CardNum"
            circ.fill.solid()
            circ.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
            circ.line.fill.background()
            circ.shadow.inherit = False
            ntf = circ.text_frame
            ntf.vertical_anchor = MSO_ANCHOR.MIDDLE
            ntf.margin_left = ntf.margin_right = Emu(0)
            np_ = ntf.paragraphs[0]
            np_.alignment = PP_ALIGN.CENTER
            _bu_none(np_)
            nr = np_.add_run()
            nr.text = str(i + 1)
            nr.font.size = Pt(20)
            nr.font.bold = True
            nr.font.color.rgb = RGBColor.from_string("FFFFFF")
            set_ea_font(nr, EA_FONT)
            if i < n - 1:                                 # 串起序號的細線，讓推論看得出順序
                link = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE, Emu(int(cx + d / 2 - 12700)),
                    Emu(int(cy + card_h)), Emu(25400), Emu(int(CARD_GAP)))
                link.name = "CardLink"
                link.fill.solid()
                link.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
                link.line.fill.background()
                link.shadow.inherit = False

        _card_text(slide, text_left, cy + 60000, text_w, card_h - 120000,
                   it["text"].strip(), size_pt)


def add_source_line(slide, sources: list[dict]) -> None:
    """模板無『資料來源』預留位置，需自行加 textbox（spec.custom_elements）。"""
    if not sources:
        return
    c = SPEC["custom_elements"]["source_line"]
    box = slide.shapes.add_textbox(*[Emu(v) for v in c["emu"]])
    box.name = "SourceLine"                      # QA 版型純度檢查靠這個名字放行
    tf = box.text_frame
    tf.word_wrap = True
    labels = "；".join((s.get("label") or "").strip() for s in sources if s.get("label"))
    if not labels:
        return
    r = tf.paragraphs[0].add_run()
    r.text = f"資料來源：{labels}"
    r.font.size = Pt(c["size_pt"])
    r.font.color.rgb = RGBColor.from_string(c["color"])
    set_ea_font(r, EA_FONT)


def set_notes(slide, text: str) -> None:
    """逐字稿寫入備忘稿。"""
    if not (text or "").strip():
        return
    tf = slide.notes_slide.notes_text_frame
    tf.clear()
    r = tf.paragraphs[0].add_run()
    r.text = text
    set_ea_font(r, EA_FONT)


def strip_group_shapes(slide) -> int:
    """版面 9 的裝飾群組：放圖表前要移除（規劃書 §12-3）。

    註：本模板的裝飾 GROUP 其實在「示範投影片」上而不是版面上，
    delete_all_slides() 之後就不存在了。這個函式留著當保險，
    換版本的母片若把群組放到版面上，這裡仍會清掉。
    """
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    n = 0
    for shp in list(slide.shapes):
        if shp.shape_type == MSO_SHAPE_TYPE.GROUP:
            shp._element.getparent().remove(shp._element)
            n += 1
    return n


def remove_empty_placeholders(slide) -> None:
    """沒填字的 placeholder 會在投影片上留「按一下以編輯」的提示框，要刪掉。"""
    for shp in list(slide.shapes):
        if shp.is_placeholder and shp.has_text_frame and not shp.text_frame.text.strip():
            shp._element.getparent().remove(shp._element)


# ==========================================================================
# 溢排保護（規劃書 §8.4）
# ==========================================================================
def _line_capacity(size_pt: int, max_lines_at_24: int) -> int:
    """內文框固定高，字級越大能塞的行數越少。8 行是 24pt 的基準。"""
    return max(2, int(max_lines_at_24 * 24 / size_pt))


def fit_body(body: list[dict], style: str | None = None) -> tuple[list[dict], int, list[dict] | None]:
    """回傳 (body, size_pt, 溢出的下一頁 body or None)。

    style 是三種內文樣式之一（或 None）；標籤與序號會佔寬度，估行數要算進去。
    prose 最大只放到 28pt——32pt 的整段敘事看起來像標題。

    24pt 中文一行約 18 字，行高約 0.45in，內文 placeholder 高 4,537,075 EMU
    → 最多約 8 行。

    條數少的時候要「往上」放大：3 條短要點用 24pt 只填得滿六成版面，
    看起來像沒寫完。母片的內文原生就是 32pt，先試 32 再試 28，
    塞得下就用大的。塞不下才往下降（20pt），再不行就拆兩頁。
    絕不允許自動縮到 16pt 以下。
    """
    lim = limits()
    max_lines = int(lim.get("max_body_lines", 8))
    base_pt, down_pt = 24, int(lim.get("font_downgrade_pt", 20))
    floor_pt = int(lim.get("font_floor_pt", 16))

    if not body:
        return body, base_pt, None

    # 由大到小找第一個塞得下的字級（32 是母片 body_lvl1 的原生大小）
    sizes = (28, base_pt) if style == "prose" else (32, 28, base_pt)
    for pt in sizes:
        if estimate_lines(body, pt, style) <= _line_capacity(pt, max_lines):
            return body, pt, None

    if down_pt >= floor_pt and estimate_lines(body, down_pt, style) <= max_lines:
        return body, down_pt, None

    # 還是爆 → 拆頁：以 20pt 為準，塞到滿為止
    head: list[dict] = []
    for i, item in enumerate(body):
        if estimate_lines(head + [item], down_pt, style) > max_lines and head:
            return head, down_pt, body[i:]
        head.append(item)
    return head, down_pt, None


# ==========================================================================
# 圖表（規劃書 §8.3）
# ==========================================================================
def setup_matplotlib() -> str:
    import logging
    import matplotlib

    matplotlib.use("Agg")
    # 中文字型多半沒有 normal weight 變體，findfont 會刷一堆雜訊，壓掉
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    from matplotlib import font_manager
    import matplotlib.pyplot as plt

    wanted = ["Microsoft JhengHei", "微軟正黑體", "PingFang TC", "Noto Sans CJK TC",
              "Noto Sans TC", "WenQuanYi Zen Hei", "文泉驛正黑", "Heiti TC", "sans-serif"]
    have = {f.name for f in font_manager.fontManager.ttflist}
    picked = next((w for w in wanted if w in have), None)
    plt.rcParams["font.sans-serif"] = ([picked] if picked else []) + wanted
    plt.rcParams["axes.unicode_minus"] = False
    if picked is None or picked in ("sans-serif",):
        warn("找不到任何中文字型，圖表中文會變成方框。"
             "Ubuntu: sudo apt install fonts-noto-cjk / macOS 內建微軟正黑體或蘋方")
    elif picked not in ("Microsoft JhengHei", "微軟正黑體"):
        info(f"圖表中文字型使用 {picked}（本機沒有微軟正黑體，PPT 文字本身不受影響）")
    return picked or "sans-serif"


def render_chart(chart: dict, out_png: Path) -> Path | None:
    """matplotlib 出圖再嵌入（不用 PPT 原生圖表，中文字型與配色比較好控）。

    主數列一律用復華紅 #B82837，對照組用灰 #939396；不畫圓餅圖；
    座標軸單位寫清楚。
    """
    import matplotlib.pyplot as plt

    data = chart.get("data") or []
    if len(data) < 2:
        warn(f"圖表「{chart.get('title','')}」資料點不足 2 個，略過")
        return None

    labels = [str(d.get("label", "")) for d in data]
    try:
        values = [float(d.get("value", 0)) for d in data]
    except (TypeError, ValueError):
        warn(f"圖表「{chart.get('title','')}」有非數值資料，略過")
        return None

    ctype = (chart.get("chart_type") or chart.get("type") or "bar").lower()
    unit = chart.get("unit") or ""

    # 內文 placeholder 寬 8,208,144 EMU ≈ 8.98in；200dpi
    fig, ax = plt.subplots(figsize=(8.98, 4.6), dpi=200)

    if ctype == "line":
        ax.plot(labels, values, color=FH_COLORS[0], linewidth=2.6,
                marker="o", markersize=6)
        for x, y in zip(labels, values):
            ax.annotate(f"{y:g}", (x, y), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=10, color=FH_COLORS[4])
    else:  # bar / stacked 都先以長條呈現；主數列復華紅、其餘灰
        colors = [FH_COLORS[0]] + [FH_COLORS[1]] * (len(values) - 1) \
            if ctype == "stacked" else [FH_COLORS[0]] * len(values)
        bars = ax.bar(labels, values, color=colors, width=0.58)
        for b, y in zip(bars, values):
            ax.annotate(f"{y:g}", (b.get_x() + b.get_width() / 2, y),
                        textcoords="offset points", xytext=(0, 5),
                        ha="center", fontsize=10, color=FH_COLORS[4])

    ax.set_ylabel(f"單位：{unit}" if unit else "", fontsize=11, color=FH_COLORS[4])
    ax.tick_params(colors=FH_COLORS[4], labelsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(FH_COLORS[1])
    ax.spines["bottom"].set_color(FH_COLORS[1])
    ax.grid(axis="y", color=FH_COLORS[1], alpha=0.25, linewidth=0.8)
    ax.set_axisbelow(True)

    fig.tight_layout(pad=1.2)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, transparent=True)
    plt.close(fig)
    return out_png




# ==========================================================================
# 視覺頁（版面 9）共用元件
# ==========================================================================
VIS_TOP = 1450000                      # 空白內頁（版面 9）的視覺區上緣
LAYOUT6_VIS_TOP = 1628800              # 內頁2-1（版面 6）內容區上緣
# 這三種視覺走內頁2-1：主標副標用母片原生 placeholder，與內容頁的頁首一致，
# 而且它們的高度需求不高，少掉的 1.2 吋放得下。
# flow / timeline 需要完整高度畫圖形，quote / stat 是滿版設計，都留在版面 9。
LAYOUT6_VISUALS = ("image", "table", "split")
VIS_LEFT = 467544
VIS_WIDTH = 8208144


def visual_title(slide, title: str, subtitle: str | None) -> None:
    """版面 9 沒有標題 placeholder，用 textbox 補。"""
    if not title:
        return
    tb = slide.shapes.add_textbox(Emu(VIS_LEFT), Emu(548680), Emu(VIS_WIDTH), Emu(700000))
    tb.name = "VisualTitle"
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = title
    r.font.size = Pt(32)
    r.font.color.rgb = RGBColor.from_string(FLOW_TEXT)
    set_ea_font(r, EA_FONT)
    if subtitle:
        p2 = tb.text_frame.add_paragraph()
        r2 = p2.add_run()
        r2.text = subtitle
        r2.font.size = Pt(18)
        r2.font.color.rgb = RGBColor.from_string("C9A063")
        set_ea_font(r2, EA_FONT)


def place_picture(slide, png: Path, top: int | None = None) -> None:
    """等比置中放一張圖，高度不超過內容區。"""
    from PIL import Image

    top = VIS_TOP if top is None else top
    w_emu = VIS_WIDTH
    with Image.open(png) as im:
        ratio = im.height / im.width
    h_emu = int(w_emu * ratio)
    max_h = SPEC["content_area_bottom_emu"] - top - 50000
    if h_emu > max_h:
        h_emu = max_h
        w_emu = int(h_emu / ratio)
    left = int((9144000 - w_emu) / 2)
    slide.shapes.add_picture(str(png), Emu(left), Emu(top), Emu(w_emu), Emu(h_emu))


def _flow_box(slide, left, top, w, h, label, note, accent=False):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(left), Emu(top), Emu(w), Emu(h))
    box.name = "FlowBox"
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE if accent else FLOW_FILL)
    box.line.color.rgb = RGBColor.from_string(FLOW_LINE)
    box.line.width = Pt(1.25)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Emu(64000)
    tf.margin_top = tf.margin_bottom = Emu(36000)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string("FFFFFF" if accent else FLOW_TEXT)
    set_ea_font(r, EA_FONT)
    if note:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = note
        r2.font.size = Pt(11)
        r2.font.color.rgb = RGBColor.from_string("FFFFFF" if accent else FLOW_NOTE)
        set_ea_font(r2, EA_FONT)
    return box


def _flow_arrow(slide, x1, y1, x2, y2):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(x1), Emu(y1), Emu(x2), Emu(y2))
    c.name = "FlowArrow"
    c.line.color.rgb = RGBColor.from_string(FLOW_LINE)
    c.line.width = Pt(2)
    # 箭頭：python-pptx 沒有 API，直接寫 XML
    ln = c.line._get_or_add_ln()
    tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    ln.append(tail)
    return c


def _txt(slide, left, top, w, h, runs, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
         name="VisualText"):
    """runs = [(text, size_pt, color_hex, bold), ...]，每個 run 自成一段。"""
    tb = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(w), Emu(h))
    tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, (text, size, color, bold) in enumerate(runs):
        par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        par.alignment = align
        r = par.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = RGBColor.from_string(color)
        set_ea_font(r, EA_FONT)
    return tb


def draw_quote(slide, q: dict) -> None:
    """大字引言：整頁就是一句話。"""
    text = (q.get("text") or "").strip()
    zh = (q.get("zh") or "").strip()
    attrib = (q.get("attrib") or "").strip()

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(VIS_LEFT), Emu(1750000),
                                 Emu(76200), Emu(2600000))
    bar.name = "QuoteBar"
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
    bar.line.fill.background()
    bar.shadow.inherit = False

    left = VIS_LEFT + 420000
    w = VIS_WIDTH - 420000
    size = 30 if visual_len(text) <= 46 else 24
    runs = [(text, size, FLOW_TEXT, True)]
    if zh:
        runs.append(("", 10, FLOW_TEXT, False))
        runs.append((zh, 18, FLOW_NOTE, False))
    _txt(slide, left, 1750000, w, 2600000, runs, align=PP_ALIGN.LEFT, name="QuoteText")
    if attrib:
        _txt(slide, left, 4500000, w, 450000,
             [("— " + attrib, 16, "C9A063", False)], align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, name="QuoteAttrib")


def draw_stat(slide, stat: dict) -> None:
    """大數字：一頁一個數字。"""
    value = str(stat.get("value") or "")
    label = (stat.get("label") or "").strip()
    note = (stat.get("note") or "").strip()
    size = 96 if len(value) <= 6 else (72 if len(value) <= 10 else 54)
    _txt(slide, VIS_LEFT, 1700000, VIS_WIDTH, 1750000,
         [(value, size, FLOW_LINE, True)], name="StatValue")
    runs = [(label, 26, FLOW_TEXT, True)]
    if note:
        runs.append((note, 16, FLOW_NOTE, False))
    _txt(slide, VIS_LEFT, 3550000, VIS_WIDTH, 1500000, runs, anchor=MSO_ANCHOR.TOP,
         name="StatLabel")


def draw_table(slide, tbl: dict, top: int | None = None) -> None:
    """原生表格。columns = [str], rows = [[str, ...]]。"""
    cols = tbl.get("columns") or []
    rows = tbl.get("rows") or []
    if not cols or not rows:
        return
    nr, nc = len(rows) + 1, len(cols)
    area_top = (VIS_TOP if top is None else top) + 120000
    avail = SPEC["content_area_bottom_emu"] - area_top - 150000

    # 列高由可用高度分配，再夾在上下限之間；分不滿就整張表垂直置中。
    # 舊版固定每列 380000 EMU，三列的表只佔內容區四分之一，底下空一大塊。
    hdr_h = 520000
    row_h = int(max(430000, min(1500000, (avail - hdr_h) / max(len(rows), 1))))
    total_h = hdr_h + row_h * len(rows)
    area_top += max(0, (avail - total_h) // 2)

    shape = slide.shapes.add_table(nr, nc, Emu(VIS_LEFT), Emu(area_top),
                                   Emu(VIS_WIDTH), Emu(total_h))
    table = shape.table
    table.rows[0].height = Emu(hdr_h)
    for i in range(1, nr):
        table.rows[i].height = Emu(row_h)
    # 列愈高，字就該愈大，版面才不會看起來是被拉長的空格
    body_pt = 12 if row_h < 620000 else (14 if row_h < 900000 else 16)
    hdr_pt = min(18, body_pt + 2)
    widths = tbl.get("widths")
    if widths and len(widths) == nc:
        total = sum(widths)
        for i, wgt in enumerate(widths):
            table.columns[i].width = Emu(int(VIS_WIDTH * wgt / total))

    def _cell(c, text, size, color, bold, fill):
        c.fill.solid()
        c.fill.fore_color.rgb = RGBColor.from_string(fill)
        c.margin_left = c.margin_right = Emu(64000)
        c.margin_top = c.margin_bottom = Emu(28000)
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = c.text_frame
        tf.word_wrap = True
        par = tf.paragraphs[0]
        r = par.add_run()
        r.text = str(text)
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = RGBColor.from_string(color)
        set_ea_font(r, EA_FONT)

    for j, col in enumerate(cols):
        _cell(table.cell(0, j), col, hdr_pt, "FFFFFF", True, FLOW_LINE)
    for i, row in enumerate(rows, start=1):
        fill = "FFFFFF" if i % 2 else FLOW_FILL
        for j in range(nc):
            val = row[j] if j < len(row) else ""
            _cell(table.cell(i, j), val, body_pt, FLOW_TEXT, j == 0, fill)


def draw_timeline(slide, tl: dict) -> None:
    """水平時間軸：上下交錯標註，避免互相擠壓。"""
    events = tl.get("events") or []
    if not events:
        return
    n = len(events)
    axis_y = 3500000
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(VIS_LEFT), Emu(axis_y),
                                  Emu(VIS_WIDTH), Emu(38100))
    line.name = "TimelineAxis"
    line.fill.solid()
    line.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
    line.line.fill.background()
    line.shadow.inherit = False

    step_x = VIS_WIDTH / max(n - 1, 1) if n > 1 else 0
    for i, ev in enumerate(events):
        cx = int(VIS_LEFT + i * step_x)
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(cx - 76200), Emu(axis_y - 57150),
                                     Emu(152400), Emu(152400))
        dot.name = "TimelineDot"
        dot.fill.solid()
        dot.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE)
        dot.line.color.rgb = RGBColor.from_string("FFFFFF")
        dot.line.width = Pt(1.5)
        dot.shadow.inherit = False

        box_w = int(min(step_x * 1.5, 1500000)) or 1400000
        box_left = cx - box_w // 2
        box_left = max(250000, min(box_left, 9144000 - 250000 - box_w))
        up = (i % 2 == 0)
        runs = [(str(ev.get("when", "")), 15, FLOW_LINE, True),
                (str(ev.get("what", "")), 13, FLOW_TEXT, False)]
        if ev.get("note"):
            runs.append((str(ev["note"]), 10, FLOW_NOTE, False))
        h = 1450000
        top = axis_y - 120000 - h if up else axis_y + 180000
        _txt(slide, box_left, top, box_w, h, runs,
             anchor=MSO_ANCHOR.BOTTOM if up else MSO_ANCHOR.TOP, name="TimelineLabel")


def draw_split(slide, sp: dict, caption: list[dict] | None = None,
               top: int | None = None) -> None:
    """雙欄對比；caption 畫在兩欄下方。"""
    gap = 300000
    col_w = int((VIS_WIDTH - gap) / 2)
    area_top = (VIS_TOP if top is None else top) + 150000
    bottom = SPEC["content_area_bottom_emu"] - 200000
    cap_lines = [b for b in (caption or []) if (b.get("text") or "").strip()]
    if cap_lines:
        bottom -= 250000 + 300000 * len(cap_lines)
    avail = bottom - area_top

    # 標題長度決定標題列高與字級：舊版固定 430000 EMU、17pt，
    # 標題一折行就會壓出紅底之外。
    inner_w = col_w - 120000
    titles = [(sp.get(s) or {}).get("title", "") for s in ("left", "right")]
    hdr_pt = 17
    while hdr_pt > 12 and max(wrapped_lines(x, inner_w - 120000, hdr_pt) for x in titles) > 2:
        hdr_pt -= 1
    hdr_lines = max(wrapped_lines(x, inner_w - 120000, hdr_pt) for x in titles)
    hdr_h = 180000 + line_height_emu(hdr_pt) * hdr_lines

    # 內容高度依實際條目計算，兩欄取高者；算完再整體垂直置中，
    # 框就不會是「上面三行字、下面一大片空白」。
    body_w = col_w - 300000
    all_items = [str(x) for s in ("left", "right") for x in ((sp.get(s) or {}).get("items") or [])]
    item_pt = fit_pt(all_items, body_w, int((avail - hdr_h) * 0.8), (18, 17, 16, 15, 14, 13))
    need = 0
    for s in ("left", "right"):
        its = [str(x) for x in ((sp.get(s) or {}).get("items") or [])]
        n_lines = sum(wrapped_lines(x, body_w, item_pt) for x in its)
        need = max(need, n_lines * line_height_emu(item_pt) + 140000 * max(len(its) - 1, 0))
    h = int(min(avail, max(2000000, hdr_h + need + 500000)))
    top = area_top + max(0, (avail - h) // 2)
    for k, side in enumerate(("left", "right")):
        data = sp.get(side) or {}
        left = VIS_LEFT + k * (col_w + gap)
        accent = bool(data.get("accent"))
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(left), Emu(top),
                                     Emu(col_w), Emu(h))
        box.name = "SplitBox"
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
        box.line.color.rgb = RGBColor.from_string(FLOW_LINE if accent else "BFBFBF")
        box.line.width = Pt(1.5 if accent else 1)
        box.shadow.inherit = False

        hdr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(left + 60000), Emu(top + 60000),
                                     Emu(inner_w), Emu(int(hdr_h)))
        hdr.name = "SplitHeader"
        hdr.fill.solid()
        hdr.fill.fore_color.rgb = RGBColor.from_string(FLOW_LINE if accent else "939396")
        hdr.line.fill.background()
        hdr.shadow.inherit = False
        tf = hdr.text_frame
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        par = tf.paragraphs[0]
        par.alignment = PP_ALIGN.CENTER
        r = par.add_run()
        r.text = data.get("title", "")
        r.font.size = Pt(hdr_pt)
        r.font.bold = True
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_ea_font(r, EA_FONT)

        items = data.get("items") or []
        body_top = top + 60000 + hdr_h + 120000
        tb = slide.shapes.add_textbox(Emu(left + 150000), Emu(int(body_top)),
                                      Emu(body_w), Emu(int(top + h - body_top - 120000)))
        tb.name = "SplitBody"
        body = tb.text_frame
        body.word_wrap = True
        body.vertical_anchor = MSO_ANCHOR.MIDDLE
        for i, it in enumerate(items):
            par = body.paragraphs[0] if i == 0 else body.add_paragraph()
            par.space_after = Pt(11)
            _bu_none(par)
            r = par.add_run()
            r.text = "・" + str(it)
            r.font.size = Pt(item_pt)
            r.font.color.rgb = RGBColor.from_string(FLOW_TEXT)
            set_ea_font(r, EA_FONT)

    if cap_lines:
        tb = slide.shapes.add_textbox(Emu(VIS_LEFT), Emu(top + h + 200000),
                                      Emu(VIS_WIDTH), Emu(300000 * len(cap_lines)))
        tb.name = "SplitCaption"
        tf2 = tb.text_frame
        tf2.word_wrap = True
        for i, b in enumerate(cap_lines):
            par = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
            par.alignment = PP_ALIGN.CENTER
            r = par.add_run()
            r.text = b.get("text", "")
            r.font.size = Pt(14)
            r.font.bold = True
            r.font.color.rgb = RGBColor.from_string(FLOW_LINE)
            set_ea_font(r, EA_FONT)


def draw_flow(slide, flow: dict, caption: list[dict] | None = None) -> None:
    """用原生圖形畫流程圖。

    flow = {"type": "chain"|"loop", "per_row": 3, "loop_label": "...",
            "nodes": [{"label": "...", "note": "...", "accent": bool}, ...]}

    chain：由左到右，超過 per_row 就換行，第二列改成由右到左（蛇行），
    換行的箭頭因此是一條乾淨的垂直線，不會斜切過其他方塊。
    loop：chain 再加一條虛線箭頭回到起點。
    caption：deck 的 body，畫在流程圖下方（版面 9 沒有內文 placeholder）。
    """
    nodes = flow.get("nodes") or []
    if not nodes:
        return
    ftype = (flow.get("type") or "chain").lower()
    per_row = int(flow.get("per_row") or (len(nodes) if len(nodes) <= 4 else 3))
    rows = [nodes[i:i + per_row] for i in range(0, len(nodes), per_row)]

    area_top = VIS_TOP + 120000
    area_bottom = SPEC["content_area_bottom_emu"] - 200000
    cap_lines = [b for b in (caption or []) if (b.get("text") or "").strip()]
    if cap_lines:
        area_bottom -= 300000 + 300000 * len(cap_lines)
    if ftype == "loop":
        area_bottom -= 420000            # 留給回頭的虛線箭頭

    gap_y, gap_x = 320000, 300000
    avail = area_bottom - area_top
    box_h = int((avail - gap_y * (len(rows) - 1)) / len(rows))
    box_h = max(760000, min(box_h, 1250000))
    block_h = box_h * len(rows) + gap_y * (len(rows) - 1)
    top0 = area_top + max(0, int((avail - block_h) / 2))   # 垂直置中

    placed = []                          # 依「流程順序」記錄，箭頭才接得對
    for ri, row in enumerate(rows):
        n = len(row)
        box_w = int((VIS_WIDTH - gap_x * (n - 1)) / n)
        top = top0 + ri * (box_h + gap_y)
        order = range(n) if ri % 2 == 0 else range(n - 1, -1, -1)
        for k, ci in enumerate(order):
            node = row[ci]
            left = VIS_LEFT + ci * (box_w + gap_x)
            _flow_box(slide, left, top, box_w, box_h,
                      node.get("label", ""), node.get("note"), bool(node.get("accent")))
            cur = (left, top, box_w, box_h)
            if placed:
                pl, pt, pw, ph = placed[-1]
                if k == 0 and ri > 0:                     # 換行：垂直往下
                    _flow_arrow(slide, pl + pw // 2, pt + ph, left + box_w // 2, top)
                elif left > pl:                           # 同列往右
                    _flow_arrow(slide, pl + pw, pt + ph // 2, left, top + box_h // 2)
                else:                                     # 同列往左（蛇行）
                    _flow_arrow(slide, pl, pt + ph // 2, left + box_w, top + box_h // 2)
            placed.append(cur)

    bottom_y = top0 + block_h

    if ftype == "loop" and len(placed) >= 2:
        fl, ft, fw, fh = placed[0]
        ll, lt, lw, lh = placed[-1]
        y = bottom_y + 180000
        _flow_arrow(slide, ll + lw // 2, y, fl + fw // 2, y).line.dash_style = 4
        tb = slide.shapes.add_textbox(Emu(VIS_LEFT), Emu(y + 40000), Emu(VIS_WIDTH), Emu(280000))
        tb.name = "FlowLoopLabel"
        par = tb.text_frame.paragraphs[0]
        par.alignment = PP_ALIGN.CENTER
        r = par.add_run()
        r.text = flow.get("loop_label") or "回到起點，循環自我強化"
        r.font.size = Pt(12)
        r.font.color.rgb = RGBColor.from_string(FLOW_LINE)
        set_ea_font(r, EA_FONT)
        bottom_y = y + 340000

    if cap_lines:
        tb = slide.shapes.add_textbox(Emu(VIS_LEFT), Emu(bottom_y + 220000),
                                      Emu(VIS_WIDTH), Emu(300000 * len(cap_lines)))
        tb.name = "FlowCaption"
        tf = tb.text_frame
        tf.word_wrap = True
        for i, b in enumerate(cap_lines):
            par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            par.alignment = PP_ALIGN.CENTER
            r = par.add_run()
            r.text = b.get("text", "")
            r.font.size = Pt(14)
            r.font.color.rgb = RGBColor.from_string(FLOW_NOTE)
            set_ea_font(r, EA_FONT)

# ==========================================================================
# 主流程
# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 6：產出 PPTX")
    ap.add_argument("--deck", default=str(DECK_JSON))
    ap.add_argument("--template", default=str(TEMPLATE))
    ap.add_argument("--out", default="")
    ap.add_argument("--no-pdf", action="store_true",
                    help="不要順便轉 PDF（預設會轉，PPT 換台電腦常跑版）")
    args = ap.parse_args()

    ensure_dirs()
    deck_path, tpl_path = Path(args.deck), Path(args.template)

    if not tpl_path.exists():
        die(f"找不到母片：{tpl_path}\n"
            "請把「FH 投影片母片_2018.pptx」放到 assets/FH_template.pptx")
    if not deck_path.exists():
        die(f"找不到藍圖：{deck_path}，請先跑 05_outline.py")

    deck = tidy_deck(read_json(deck_path))
    meta, slides_spec = deck.get("meta", {}), deck.get("slides", [])
    if not slides_spec:
        die("deck.json 沒有任何 slides")

    cfg = load_project()
    out_path = Path(args.out) if args.out else OUTPUT / _out_name(meta, cfg)

    step(f"Stage 6 建置 PPTX（{len(slides_spec)} 頁藍圖）")
    setup_matplotlib()

    prs = Presentation(str(tpl_path))
    n = delete_all_slides(prs)
    ok(f"清除母片內建示範頁 {n} 張"
       + ("" if n == 11 else f"（預期 11 張，實際 {n} 張——母片版本可能不同）"))

    built = 0
    split_pages = 0
    charts_made = 0

    for spec in slides_spec:
        pages = build_one(prs, spec, meta)
        built += pages["count"]
        split_pages += pages["split"]
        charts_made += pages["charts"]

    assert len(prs.slides._sldIdLst) == built, "產出頁數與計數不符"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))

    ok(f"PPTX → {out_path}（{built} 頁）")
    if not args.no_pdf:
        pdf = export_pdf(out_path)
        if pdf:
            ok(f"PDF  → {pdf}")
    if split_pages:
        info(f"{split_pages} 頁因內文過長自動拆頁（主標加「(續)」）")
    if charts_made:
        info(f"{charts_made} 張圖表已產生於 output/charts/")
    print()
    info("下一步：python scripts/07_build_script.py（逐字稿）")
    info("        python scripts/08_qa.py --all（品管）")
    stop("版面看起來對嗎？", "PDF 直接翻（PPT 換台電腦容易跑版）",
         "python scripts/07_build_script.py && python scripts/08_qa.py --all")
    return 0


def export_pdf(pptx_path: Path) -> Path | None:
    """用 LibreOffice 轉 PDF：PPT 在別台電腦開常常跑版，PDF 是唯一保證。

    雲端環境如果只裝了 libreoffice-core（缺 Impress 匯入濾鏡）會轉失敗，
    這不是錯誤，提示使用者在本機補跑即可：
        sudo apt install libreoffice-impress
        python scripts/06_build_pptx.py --pdf-only
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        warn("找不到 LibreOffice，略過 PDF；本機請裝 libreoffice-impress 後重跑")
        return None
    out_pdf = pptx_path.with_suffix(".pdf")
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                        "--outdir", str(pptx_path.parent), str(pptx_path)],
                       check=True, capture_output=True, timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        warn(f"PDF 轉檔失敗（{type(e).__name__}）：本機請裝 libreoffice-impress 後重跑")
        return None
    if not out_pdf.exists():
        warn("PDF 轉檔沒有產出檔案，多半是缺 Impress 匯入濾鏡")
        return None
    return out_pdf


def _out_name(meta: dict, cfg: dict) -> str:
    title = safe_filename(meta.get("book_title") or cfg["book"].get("title_zh") or "書名", 30)
    return f"FH_{title}_分享_{cfg['deck'].get('minutes', 60)}min.pptx"


def build_one(prs, spec: dict, meta: dict) -> dict:
    """建一頁（必要時拆成多頁）。回傳 {count, split, charts}。"""
    kind = spec.get("kind", "content")
    layout = int(spec.get("layout", 4))
    title = (spec.get("title") or "").strip()
    subtitle = (spec.get("subtitle") or "") or None
    body = spec.get("body") or []
    sources = spec.get("sources") or []
    narration = spec.get("narration") or ""

    count = split = charts = 0

    # ---- 封面 ----
    if kind == "cover":
        s = add(prs, layout)
        ph = SPEC["layouts"][0]["placeholders"]
        set_ph(s, 0, title, size_pt=ph["0"]["size_pt"], color=ph["0"]["color"])
        if subtitle:
            set_ph(s, 14, subtitle, size_pt=ph["14"]["size_pt"])
        if body:
            set_ph(s, 13, body, size_pt=ph["13"]["size_pt"])
        remove_empty_placeholders(s)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": 0}

    # ---- 目錄 ----
    if kind == "toc":
        s = add(prs, layout)
        items = body or [{"level": 0, "text": title}]
        size = 36 if len(items) <= 6 else (28 if len(items) <= 9 else 24)
        set_ph(s, 13, items, size_pt=size)
        remove_empty_placeholders(s)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": 0}

    # ---- 章名／分部頁籤 ----
    if kind == "divider":
        s = add(prs, layout)
        ph = SPEC["layouts"][2]["placeholders"]["14"]
        set_ph(s, 14, title, size_pt=ph["size_pt"], color=ph["color"])
        note = (spec.get("note") or "").strip()
        left, top, w, h = SPEC["layouts"][2]["placeholders"]["14"]["emu"]
        if spec.get("image_hint"):
            # 右側要放圖，主標框先讓位，否則長章名會折行蓋到佔位框上
            w = IMG_SLOT[0] - left - 180000
            s.placeholders[14].width = Emu(w)
        if note:
            # 章名用官方中譯時，把「第 N 章｜英文原章名」放在主標下方一行，聽眾追得回原書；
            # 章名折行時要跟著往下移，不然會疊在第二行上
            n_lines = wrapped_lines(title, w, int(ph.get("size_pt", 44)))
            note_top = top + max(h, n_lines * line_height_emu(int(ph.get("size_pt", 44)))) + 60000
            tb = s.shapes.add_textbox(Emu(left), Emu(int(note_top)), Emu(w), Emu(520000))
            tb.name = "DividerNote"
            tf = tb.text_frame
            tf.word_wrap = True
            r = tf.paragraphs[0].add_run()
            r.text = note
            r.font.size = Pt(18)
            r.font.color.rgb = RGBColor.from_string("939396")
            set_ea_font(r, EA_FONT)
        if spec.get("image_hint"):
            _divider_visual(s, spec)
        remove_empty_placeholders(s)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": 0}

    # ---- 祝賀頁（主線最後一頁，走母片「結尾」版面，自帶復華抬頭與電話）----
    if kind == "wish":
        s = add(prs, layout)
        set_ph(s, 14, title or "業績長紅", size_pt=54, color="B82837")
        remove_empty_placeholders(s)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": 0}

    # ---- 結語 ----
    if kind == "closing":
        s = add(prs, layout)
        set_ph(s, 14, title or "Q & A", size_pt=44, color="B82837")
        remove_empty_placeholders(s)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": 0}

    # ---- 影片頁（現場播放）----
    if kind == "video" and spec.get("video"):
        v = spec["video"]
        s = add(prs, 9)
        strip_group_shapes(s)
        remove_empty_placeholders(s)

        # 標題 + 副標
        tb = s.shapes.add_textbox(Emu(467544), Emu(700000), Emu(8208144), Emu(1100000))
        tb.name = "VideoTitle"
        tf = tb.text_frame
        tf.word_wrap = True
        r = tf.paragraphs[0].add_run()
        r.text = title or "參考影片"
        r.font.size = Pt(34)
        r.font.bold = True
        r.font.color.rgb = RGBColor.from_string("262627")
        set_ea_font(r, EA_FONT)
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = f"現場播放　{v.get('span', '')}"
        r2.font.size = Pt(20)
        r2.font.color.rgb = RGBColor.from_string("B82837")
        set_ea_font(r2, EA_FONT)

        # QR code（置中偏左）＋ 右側說明
        png = OUTPUT / "charts" / f"{spec.get('id', 'video')}_qr.png"
        made = render_qr(v.get("url", ""), png) if v.get("url") else None
        qr_size = 2400000
        if made:
            s.shapes.add_picture(str(made), Emu(1100000), Emu(2150000),
                                 Emu(qr_size), Emu(qr_size))

        info_left = 1100000 + qr_size + 500000
        ib = s.shapes.add_textbox(Emu(info_left), Emu(2300000),
                                  Emu(9144000 - info_left - 467544), Emu(2200000))
        ib.name = "VideoInfo"
        itf = ib.text_frame
        itf.word_wrap = True
        lines = [(f"片段 {v.get('span', '')}", 18, "262627")]
        if v.get("note"):
            lines.append((v["note"], 15, "939396"))
        lines.append((v.get("url", ""), 11, "939396"))
        for i, (txt, sz, col) in enumerate(lines):
            para = itf.paragraphs[0] if i == 0 else itf.add_paragraph()
            rr = para.add_run()
            rr.text = txt
            rr.font.size = Pt(sz)
            rr.font.color.rgb = RGBColor.from_string(col)
            set_ea_font(rr, EA_FONT)

        add_source_line(s, sources)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": 0}

    # ---- 視覺頁 ----
    VISUAL_KEYS = ("chart", "image", "flow", "quote", "stat", "table", "timeline", "split")
    if kind == "chart" and any(spec.get(k) for k in VISUAL_KEYS):
        # image / table / split 走內頁2-1，主標副標用母片原生 placeholder；
        # 其餘走空白內頁，標題是自建 textbox。
        on6 = any(spec.get(k) for k in LAYOUT6_VISUALS)
        vis_top = LAYOUT6_VIS_TOP if on6 else VIS_TOP

        s = add(prs, 6 if on6 else 9)
        strip_group_shapes(s)            # 放圖表前移除裝飾群組

        if on6:
            lay = SPEC["layouts"][6]["placeholders"]
            set_ph(s, 13, title, size_pt=lay["13"].get("size_pt", 36))
            if subtitle:
                set_ph(s, 14, subtitle, size_pt=lay["14"].get("size_pt", 24),
                       color=lay["14"].get("color"))
            remove_empty_placeholders(s)   # 內文框讓位給視覺
        else:
            remove_empty_placeholders(s)   # 版面 9 的內容框要讓位給圖
            if not (spec.get("quote") or spec.get("stat")):
                visual_title(s, title, subtitle)

        if spec.get("quote"):            # 大字引言
            draw_quote(s, spec["quote"])
            charts += 1
        elif spec.get("stat"):           # 大數字
            draw_stat(s, spec["stat"])
            charts += 1
        elif spec.get("table"):          # 原生表格（書中值 → 最新值）
            draw_table(s, spec["table"], top=vis_top)
            charts += 1
        elif spec.get("timeline"):       # 時間軸
            draw_timeline(s, spec["timeline"])
            charts += 1
        elif spec.get("split"):          # 雙欄對比
            draw_split(s, spec["split"], spec.get("body"), top=vis_top)
            charts += 1
        elif spec.get("image"):          # 書中原圖（截圖）
            src = Path(spec["image"]["path"])
            if not src.is_absolute():
                src = Path(__file__).resolve().parent.parent / src
            if src.exists():
                place_picture(s, src, top=vis_top)
                charts += 1
            else:
                warn(f"{spec.get('id')} 找不到圖片 {src}")
        elif spec.get("flow"):           # 原生圖形畫的流程圖
            draw_flow(s, spec["flow"], spec.get("body"))
            charts += 1
        else:                            # 由資料生成的圖表
            png = OUTPUT / "charts" / f"{spec.get('id', 'chart')}.png"
            made = render_chart(spec["chart"], png)
            if made:
                place_picture(s, made)
                charts += 1

        add_source_line(s, sources)
        set_notes(s, narration)
        return {"count": 1, "split": 0, "charts": charts}

    # ---- 一般內頁（含溢排保護與自動拆頁）----
    style = spec.get("style") if spec.get("style") in BODY_STYLES else None
    rest: list[dict] | None = body
    page_no = 0
    while True:
        if style:
            # 卡片式自己算字級與高度，這裡只負責「一頁放幾張」：
            # prose 兩段、chain/labeled 四張，超過就拆下一頁。
            per_page = card_per_page(style)
            cur, rest = (rest or [])[:per_page], (rest or [])[per_page:] or None
            size_pt = 0
        else:
            cur, size_pt, rest = fit_body(rest or [], style)
        s = add(prs, layout)
        t = title if page_no == 0 else f"{title}（續）"

        lay = SPEC["layouts"][layout]["placeholders"]
        has_sub = "15" in lay                        # 有副標的版型：13 主標 / 14 副標 / 15 內文
        body_idx = 15 if has_sub else 14

        set_ph(s, 13, t, size_pt=lay["13"].get("size_pt", 36))
        if has_sub and subtitle:
            set_ph(s, 14, subtitle, size_pt=lay["14"].get("size_pt", 24),
                   color=lay["14"].get("color"))
        if style:
            # 內文框只借它的座標，字畫在卡片上；空框稍後由 remove_empty_placeholders 清掉
            geo = placeholder_box(s, body_idx)
            if geo:
                draw_cards(s, cur, style, *geo)
        else:
            # 條數少時把段距拉開，配合垂直置中把版面撐開
            n_l1 = sum(1 for b in cur if int(b.get("level", 0)) == 0)
            gap = 16 if n_l1 <= 3 else (10 if n_l1 <= 4 else None)
            set_ph(s, body_idx, cur, size_pt=size_pt, middle=True, space_after_pt=gap)

        remove_empty_placeholders(s)
        add_source_line(s, sources)
        set_notes(s, narration if page_no == 0 else "")

        count += 1
        page_no += 1
        if not rest:
            break
        split += 1
        if page_no > 4:
            warn(f"「{title}」拆超過 4 頁，剩餘內容已捨棄——請回 deck.json 精簡這一頁")
            break

    return {"count": count, "split": split, "charts": charts}


if __name__ == "__main__":
    sys.exit(main())
