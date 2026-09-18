#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6 — 由 work/05_deck.json 產出 PPTX。

三個最容易翻車的地方（規劃書 §12），這支腳本全部處理掉：
    1. 母片內建 11 張示範頁沒清乾淨 → delete_all_slides() 必在 add_slide 之前，且要 drop_rel
    2. 中文字型只設了 latin → 所有 run 都過 set_ea_font()，寫 <a:ea> 與 <a:cs>
    3. 版面 9 的裝飾群組 → 放圖表前移除 slide 上的 GROUP shape

用法：
    python scripts/06_build_pptx.py
    python scripts/06_build_pptx.py --deck work/05_deck.json --out output/xxx.pptx
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECK_JSON, OUTPUT, TEMPLATE, die, ensure_dirs, estimate_lines, format_timecode,
    info, limits, load_project, load_spec, ok, read_json, safe_filename, step,
    visual_len, warn,
)

from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Emu, Pt  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR  # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR  # noqa: E402

EA_FONT = "微軟正黑體"
LATIN_FONT = "Arial"

# <a:ea> / <a:cs> 在 CT_TextCharacterProperties 裡有固定順序，
# 不能直接 append，否則產出的 XML 不合 schema、PowerPoint 會報修復。
_EA_SUCCESSORS = ("a:cs", "a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")
_CS_SUCCESSORS = ("a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")

SPEC = load_spec()
FH_COLORS = ["#B82837", "#939396", "#B08F6E", "#00A0E9", "#262627"]


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


def set_ph(slide, idx: int, text, size_pt: int | None = None, color: str | None = None):
    """依 placeholder idx 填字，並強制設定中文字型。

    text 可以是字串，或 [{"level": 0, "text": "..."}] 這種段落陣列。
    """
    try:
        ph = slide.placeholders[idx]
    except KeyError:
        warn(f"版面缺少 placeholder idx={idx}，已略過")
        return None

    tf = ph.text_frame
    tf.clear()
    lines = text if isinstance(text, list) else [{"level": 0, "text": text}]
    lines = [ln for ln in lines if (ln.get("text") or "").strip()]
    if not lines:
        return ph

    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = int(ln.get("level", 0))
        r = p.add_run()
        r.text = ln["text"]
        if size_pt:
            r.font.size = Pt(size_pt)
        if color:
            r.font.color.rgb = RGBColor.from_string(color)
        set_ea_font(r, EA_FONT)
    return ph


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
def fit_body(body: list[dict]) -> tuple[list[dict], int, list[dict] | None]:
    """回傳 (body, size_pt, 溢出的下一頁 body or None)。

    24pt 中文一行約 18 字，行高約 0.45in，內文 placeholder 高 4,537,075 EMU
    → 最多約 8 行。超過就：先降到 20pt → 還是超過就拆兩頁。
    絕不允許自動縮到 16pt 以下。
    """
    lim = limits()
    max_lines = int(lim.get("max_body_lines", 8))
    base_pt, down_pt = 24, int(lim.get("font_downgrade_pt", 20))
    floor_pt = int(lim.get("font_floor_pt", 16))

    if not body:
        return body, base_pt, None

    if estimate_lines(body, base_pt) <= max_lines:
        return body, base_pt, None

    if down_pt >= floor_pt and estimate_lines(body, down_pt) <= max_lines:
        return body, down_pt, None

    # 還是爆 → 拆頁：以 20pt 為準，塞到滿為止
    head: list[dict] = []
    for i, item in enumerate(body):
        if estimate_lines(head + [item], down_pt) > max_lines and head:
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

FLOW_FILL = "E9E4DA"                   # 米白（內頁2 色系）
FLOW_LINE = "B82837"                   # 復華紅
FLOW_TEXT = "262627"
FLOW_NOTE = "6B6B6B"


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
    top = (VIS_TOP if top is None else top) + 120000
    height = min(SPEC["content_area_bottom_emu"] - top - 150000, 380000 * nr)
    shape = slide.shapes.add_table(nr, nc, Emu(VIS_LEFT), Emu(top), Emu(VIS_WIDTH), Emu(height))
    table = shape.table
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
        _cell(table.cell(0, j), col, 14, "FFFFFF", True, FLOW_LINE)
    for i, row in enumerate(rows, start=1):
        fill = "FFFFFF" if i % 2 else FLOW_FILL
        for j in range(nc):
            val = row[j] if j < len(row) else ""
            _cell(table.cell(i, j), val, 12, FLOW_TEXT, j == 0, fill)


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
    top = (VIS_TOP if top is None else top) + 150000
    bottom = SPEC["content_area_bottom_emu"] - 200000
    cap_lines = [b for b in (caption or []) if (b.get("text") or "").strip()]
    if cap_lines:
        bottom -= 250000 + 300000 * len(cap_lines)
    h = bottom - top
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
                                     Emu(col_w - 120000), Emu(430000))
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
        r.font.size = Pt(17)
        r.font.bold = True
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_ea_font(r, EA_FONT)

        items = data.get("items") or []
        tb = slide.shapes.add_textbox(Emu(left + 150000), Emu(top + 600000),
                                      Emu(col_w - 300000), Emu(h - 700000))
        tb.name = "SplitBody"
        body = tb.text_frame
        body.word_wrap = True
        for i, it in enumerate(items):
            par = body.paragraphs[0] if i == 0 else body.add_paragraph()
            par.space_after = Pt(10)
            r = par.add_run()
            r.text = "・" + str(it)
            r.font.size = Pt(14)
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
    args = ap.parse_args()

    ensure_dirs()
    deck_path, tpl_path = Path(args.deck), Path(args.template)

    if not tpl_path.exists():
        die(f"找不到母片：{tpl_path}\n"
            "請把「FH 投影片母片_2018.pptx」放到 assets/FH_template.pptx")
    if not deck_path.exists():
        die(f"找不到藍圖：{deck_path}，請先跑 05_outline.py")

    deck = read_json(deck_path)
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
    if split_pages:
        info(f"{split_pages} 頁因內文過長自動拆頁（主標加「(續)」）")
    if charts_made:
        info(f"{charts_made} 張圖表已產生於 output/charts/")
    print()
    info("下一步：python scripts/07_build_script.py（逐字稿）")
    info("        python scripts/08_qa.py --all（品管）")
    return 0


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

    # ---- 章節頁籤 ----
    if kind == "divider":
        s = add(prs, layout)
        ph = SPEC["layouts"][2]["placeholders"]["14"]
        set_ph(s, 14, title, size_pt=ph["size_pt"], color=ph["color"])
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
    rest: list[dict] | None = body
    page_no = 0
    while True:
        cur, size_pt, rest = fit_body(rest or [])
        s = add(prs, layout)
        t = title if page_no == 0 else f"{title}（續）"

        lay = SPEC["layouts"][layout]["placeholders"]
        has_sub = "15" in lay                        # 有副標的版型：13 主標 / 14 副標 / 15 內文
        body_idx = 15 if has_sub else 14

        set_ph(s, 13, t, size_pt=lay["13"].get("size_pt", 36))
        if has_sub and subtitle:
            set_ph(s, 14, subtitle, size_pt=lay["14"].get("size_pt", 24),
                   color=lay["14"].get("color"))
        set_ph(s, body_idx, cur, size_pt=size_pt)

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
