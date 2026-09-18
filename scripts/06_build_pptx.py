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



def render_qr(url: str, out_png: Path) -> Path | None:
    """影片頁的 QR code。沒裝 qrcode 套件就略過，頁面仍會印出網址。"""
    try:
        import qrcode
    except ImportError:
        warn("未安裝 qrcode 套件，影片頁不會有 QR code（pip install qrcode）")
        return None
    q = qrcode.QRCode(box_size=10, border=2,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    img = q.make_image(fill_color="#262627", back_color="white").convert("RGB")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return out_png


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

    # ---- 圖表頁（空白內頁 9）----
    if kind == "chart" and spec.get("chart"):
        s = add(prs, layout if layout == 9 else 9)
        strip_group_shapes(s)            # 放圖表前移除裝飾群組
        remove_empty_placeholders(s)     # 版面 9 的內容框要讓位給圖

        png = OUTPUT / "charts" / f"{spec.get('id', 'chart')}.png"
        made = render_chart(spec["chart"], png)

        # 標題：版面 9 沒有標題 placeholder，用 textbox 補
        if title:
            tb = s.shapes.add_textbox(Emu(467544), Emu(548680), Emu(8208144), Emu(700000))
            tb.name = "ChartTitle"
            r = tb.text_frame.paragraphs[0].add_run()
            r.text = title
            r.font.size = Pt(32)
            r.font.color.rgb = RGBColor.from_string("262627")
            set_ea_font(r, EA_FONT)
            if subtitle:
                p2 = tb.text_frame.add_paragraph()
                r2 = p2.add_run()
                r2.text = subtitle
                r2.font.size = Pt(18)
                r2.font.color.rgb = RGBColor.from_string("C9A063")
                set_ea_font(r2, EA_FONT)

        if made:
            charts += 1
            from PIL import Image

            w_emu = 8208144
            with Image.open(made) as im:
                ratio = im.height / im.width
            h_emu = int(w_emu * ratio)
            max_h = SPEC["content_area_bottom_emu"] - 1500000
            if h_emu > max_h:
                h_emu = max_h
                w_emu = int(h_emu / ratio)
            left = int((9144000 - w_emu) / 2)
            s.shapes.add_picture(str(made), Emu(left), Emu(1450000), Emu(w_emu), Emu(h_emu))

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
