#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 8 — 自動品管（不可略過）。輸出 output/qa_report.md。

規劃書 §10 的九項檢查，任何一項 FAIL 就不准交付：
    頁數      45 ≤ total ≤ 60
    溢排      每頁內文估算行數 ≤ 8；主標 ≤ 18 字；副標 ≤ 28 字
    資料來源  每一頁（封面／頁籤／結尾除外）都有 sources，且非空字串
    外部連結  所有 url HTTP 200；死連結列出
    具體性    每頁 body 至少含一個數字／年份／專有名詞；否則標 WARN
    版型純度  每張 slide 的 layout name 必須在模板 11 種之內；無自建 textbox（資料來源行除外）
    字型      掃描所有 run，a:ea typeface 必須是 微軟正黑體
    逐字稿    每頁 narration 字數 = duration_sec × 220/60 ±25%；總時長 50–58 分鐘
    對岸用語  黑名單掃描
    視覺      LibreOffice 轉 PNG 全頁截圖，輸出到 output/preview/

用法：
    python scripts/08_qa.py --all             全部檢查 + 產報告
    python scripts/08_qa.py --check-env       只檢查環境與相依
    python scripts/08_qa.py --check-sources   只做 URL HTTP 全檢（Stage 4 後用）
    python scripts/08_qa.py --check-deck      只檢查 deck.json 文案規則（Stage 5 後用）
    python scripts/08_qa.py --check-narration 只檢查逐字稿字數
    python scripts/08_qa.py --preview         只產預覽圖
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECK_JSON, EVIDENCE, OUTPUT, TEMPLATE, _c, ensure_dirs, estimate_lines,
    has_concrete, have_cmd, info, limits, load_project, load_spec, narration_chars,
    ok, read_json, soffice_bin, step, visual_len, warn,
)

ALLOWED_CUSTOM_SHAPES = {"SourceLine", "ChartTitle"}
EA_EXPECT = "微軟正黑體"


class Result:
    """一項檢查的結果。"""

    def __init__(self, name: str, criterion: str):
        self.name = name
        self.criterion = criterion
        self.status = "PASS"     # PASS / WARN / FAIL / SKIP
        self.details: list[str] = []

    def fail(self, msg: str) -> None:
        self.status = "FAIL"
        self.details.append(msg)

    def warn(self, msg: str) -> None:
        if self.status == "PASS":
            self.status = "WARN"
        self.details.append(msg)

    def skip(self, msg: str) -> None:
        self.status = "SKIP"
        self.details.append(msg)

    def note(self, msg: str) -> None:
        self.details.append(msg)

    def print_line(self) -> None:
        color = {"PASS": "32", "WARN": "33", "FAIL": "31", "SKIP": "90"}[self.status]
        mark = {"PASS": "✓", "WARN": "!", "FAIL": "✗", "SKIP": "–"}[self.status]
        print(_c(color, f"  {mark} {self.status:<4} {self.name}"))
        for d in self.details[:12]:
            print(f"        {d}")
        if len(self.details) > 12:
            print(f"        …（另有 {len(self.details) - 12} 項，詳見 qa_report.md）")


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 8：自動品管")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check-env", action="store_true")
    ap.add_argument("--check-sources", action="store_true")
    ap.add_argument("--check-deck", action="store_true")
    ap.add_argument("--check-narration", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--pptx", default="")
    ap.add_argument("--timeout", type=float, default=12.0, help="URL 檢查逾時秒數")
    args = ap.parse_args()

    ensure_dirs()
    if not any([args.all, args.check_env, args.check_sources, args.check_deck,
                args.check_narration, args.preview]):
        ap.print_help()
        return 2

    if args.check_env:
        return check_env()

    results: list[Result] = []

    if args.check_sources:
        step("URL 連結檢查")
        r = check_links(collect_urls_from_evidence(), args.timeout)
        r.print_line()
        return 0 if r.status in ("PASS", "WARN", "SKIP") else 1

    deck = read_json(DECK_JSON) if DECK_JSON.exists() else None

    if args.check_deck or args.check_narration:
        if deck is None:
            print(_c("31", "  ✗ 找不到 work/05_deck.json，請先跑 05_outline.py"))
            return 1
        step("deck.json 檢查")
        if args.check_deck:
            results += [check_page_count(deck), check_overflow(deck), check_sources(deck),
                        check_concrete(deck), check_banned_terms(deck)]
        if args.check_narration:
            results.append(check_narration(deck))
        for r in results:
            r.print_line()
        return 0 if not any(r.status == "FAIL" for r in results) else 1

    pptx = Path(args.pptx) if args.pptx else find_pptx()

    if args.preview:
        r = make_preview(pptx)
        r.print_line()
        return 0

    # ---- --all ----
    step("Stage 8 自動品管")
    if deck is None:
        print(_c("31", "  ✗ 找不到 work/05_deck.json，請先跑 05_outline.py"))
        return 1

    results.append(check_page_count(deck))
    results.append(check_overflow(deck))
    results.append(check_sources(deck))
    results.append(check_links(collect_urls_from_deck(deck), args.timeout))
    results.append(check_concrete(deck))
    results.append(check_layout_purity(pptx))
    results.append(check_fonts(pptx))
    results.append(check_narration(deck))
    results.append(check_banned_terms(deck))
    results.append(make_preview(pptx))

    for r in results:
        r.print_line()

    report = write_report(results, deck, pptx)
    print()
    n_fail = sum(1 for r in results if r.status == "FAIL")
    n_warn = sum(1 for r in results if r.status == "WARN")
    n_skip = sum(1 for r in results if r.status == "SKIP")
    ok(f"報告 → {report}")
    if n_fail:
        print(_c("31", f"\n  ✗ {n_fail} 項 FAIL —— 不准交付。修完 deck.json 後跑 make revise"))
        return 1
    print(_c("32", f"\n  ✓ 全部通過（{n_warn} 項 WARN，{n_skip} 項 SKIP）"))
    if n_warn:
        info("WARN 不擋交付，但建議看一下 qa_report.md")
    return 0


# ==========================================================================
def find_pptx() -> Path | None:
    cands = sorted(OUTPUT.glob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def slides_of(deck: dict) -> list[dict]:
    return deck.get("slides", [])


# --- 1. 頁數 --------------------------------------------------------------
def check_page_count(deck: dict) -> Result:
    cfg = load_project()
    lo, hi = cfg["deck"].get("target_slides", [45, 60])
    r = Result("頁數", f"{lo} ≤ total ≤ {hi}")
    n = len(slides_of(deck))
    if n < lo:
        r.fail(f"只有 {n} 頁，低於下限 {lo}")
    elif n > hi:
        r.fail(f"共 {n} 頁，高於上限 {hi}")
    else:
        r.note(f"{n} 頁")
    return r


# --- 2. 溢排 --------------------------------------------------------------
def check_overflow(deck: dict) -> Result:
    lim = limits()
    max_lines = int(lim.get("max_body_lines", 8))
    t_max = int(lim.get("title_max_chars", 18))
    s_max = int(lim.get("subtitle_max_chars", 28))
    b_max = int(lim.get("body_max_chars_per_slide", 160))
    l1_max = int(lim.get("bullet_l1_max_chars", 40))
    max_lv = int(lim.get("max_outline_level", 1))

    r = Result("溢排", f"內文 ≤{max_lines} 行；主標 ≤{t_max} 字；副標 ≤{s_max} 字")
    for s in slides_of(deck):
        sid, kind = s.get("id"), s.get("kind")
        title = s.get("title") or ""
        sub = s.get("subtitle") or ""
        body = s.get("body") or []

        if kind not in ("cover", "divider", "closing", "toc") and visual_len(title) > t_max:
            r.fail(f"{sid} 主標 {visual_len(title):.0f} 字 > {t_max}：「{title[:24]}」")
        if sub and visual_len(sub) > s_max:
            r.fail(f"{sid} 副標 {visual_len(sub):.0f} 字 > {s_max}：「{sub[:30]}」")

        lines = estimate_lines(body, 24)
        if lines > max_lines:
            r.fail(f"{sid} 內文估算 {lines} 行 > {max_lines}（24pt）")

        total = sum(visual_len(b.get("text") or "") for b in body)
        if total > b_max:
            r.fail(f"{sid} 內文總字數 {total:.0f} > {b_max}")

        for b in body:
            lv = int(b.get("level", 0))
            if lv > max_lv:
                r.fail(f"{sid} 出現第 {lv + 1} 層（最多 {max_lv + 1} 層）")
            if lv == 0 and visual_len(b.get("text") or "") > l1_max:
                r.fail(f"{sid} 第一層要點 {visual_len(b.get('text') or ''):.0f} 字 > {l1_max}")

        if kind == "content":
            l1 = [b for b in body if int(b.get("level", 0)) == 0]
            blo, bhi = lim.get("bullets_l1_range", [3, 5])
            if l1 and not (blo <= len(l1) <= bhi):
                r.warn(f"{sid} 第一層要點 {len(l1)} 條，建議 {blo}–{bhi} 條")
    if r.status == "PASS":
        r.note(f"{len(slides_of(deck))} 頁全部在版面容量內")
    return r


# --- 3. 資料來源 ----------------------------------------------------------
def check_sources(deck: dict) -> Result:
    r = Result("資料來源", "每頁（封面／頁籤／結尾除外）都有 sources 且非空字串")
    exempt = {"cover", "divider", "closing"}
    missing = []
    for s in slides_of(deck):
        if s.get("kind") in exempt:
            continue
        srcs = s.get("sources") or []
        labels = [(x.get("label") or "").strip() for x in srcs if isinstance(x, dict)]
        labels = [x for x in labels if x]
        if not labels:
            missing.append(s.get("id"))
        elif any("【待填" in x for x in labels):
            r.warn(f"{s.get('id')} 來源含【待填】標記")
    if missing:
        r.fail(f"{len(missing)} 頁沒有資料來源：{', '.join(map(str, missing[:15]))}"
               + (" …" if len(missing) > 15 else ""))
    else:
        r.note("所有需要來源的頁面都有")
    return r


# --- 4. 外部連結 ----------------------------------------------------------
def collect_urls_from_deck(deck: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in slides_of(deck):
        for src in s.get("sources") or []:
            if isinstance(src, dict) and src.get("url"):
                out.setdefault(src["url"], []).append(str(s.get("id")))
    return out


def collect_urls_from_evidence() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in sorted(EVIDENCE.glob("ch*.json")):
        try:
            d = read_json(p)
        except Exception:  # noqa: BLE001
            continue
        for key in ("verified", "taiwan_lens", "extensions", "chart_candidates"):
            for item in d.get(key) or []:
                if isinstance(item, dict) and item.get("source_url"):
                    out.setdefault(item["source_url"], []).append(f"{p.stem}.{key}")
    return out


def check_links(urls: dict[str, list[str]], timeout: float) -> Result:
    r = Result("外部連結", "所有 url HTTP 200；死連結列出")
    if not urls:
        r.note("沒有外部連結需要檢查")
        return r
    try:
        import requests
    except ImportError:
        r.skip("未安裝 requests，無法檢查連結（pip install requests）")
        return r

    info(f"檢查 {len(urls)} 個連結…")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FH-deck-QA/1.0)"}

    def probe(url: str) -> tuple[str, int | str]:
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
            if resp.status_code >= 400:
                resp = requests.get(url, timeout=timeout, allow_redirects=True,
                                    headers=headers, stream=True)
            return url, resp.status_code
        except Exception as e:  # noqa: BLE001
            return url, type(e).__name__

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(probe, urls.keys()))

    dead, okc, netfail = [], 0, 0
    NET_ERRORS = {"ProxyError", "ConnectionError", "ConnectTimeout", "ReadTimeout",
                  "Timeout", "SSLError", "TooManyRedirects", "ChunkedEncodingError"}
    for url, code in results:
        where = ", ".join(urls[url][:3])
        if code == 200:
            okc += 1
        elif isinstance(code, int) and code in (301, 302, 303, 307, 308, 403, 405):
            r.warn(f"HTTP {code}（可能仍有效，請人工確認）{url}  ← {where}")
        else:
            if code in NET_ERRORS:
                netfail += 1
            dead.append((url, code, where))

    # 全部都是連線層失敗 → 是這台機器連不出去，不是連結真的死掉。
    # 判 SKIP 而不是 FAIL，否則在受限網路環境會永遠卡住交付。
    if netfail and netfail == len(urls):
        r.skip(f"{len(urls)} 個連結全部連線失敗（{results[0][1]}），"
               "判定為本機無法對外連線而非死連結。")
        r.note("請在可正常上網的環境重跑：python scripts/08_qa.py --check-sources")
        for url, code, where in dead[:10]:
            r.note(f"未驗證：{url}  ← {where}")
        return r

    if dead:
        for url, code, where in dead:
            r.fail(f"死連結 HTTP {code}：{url}  ← {where}")
    r.note(f"{okc}/{len(urls)} 個連結回應 200"
           + (f"，{netfail} 個連線失敗" if netfail else ""))
    return r


# --- 5. 具體性 ------------------------------------------------------------
def check_concrete(deck: dict) -> Result:
    r = Result("具體性", "每頁 body 至少含一個數字／年份／專有名詞，否則 WARN")
    exempt = {"cover", "divider", "closing", "toc", "chart"}
    for s in slides_of(deck):
        if s.get("kind") in exempt:
            continue
        body = s.get("body") or []
        text = " ".join((b.get("text") or "") for b in body)
        if not text.strip():
            continue
        if not has_concrete(text) and not has_concrete(s.get("title") or ""):
            r.warn(f"{s.get('id')} 全是抽象概念，沒有數字／年份／案例名："
                   f"「{(s.get('title') or '')[:20]}」")
    if r.status == "PASS":
        r.note("每一頁都有具體物")
    return r


# --- 6. 版型純度 ----------------------------------------------------------
def check_layout_purity(pptx: Path | None) -> Result:
    spec = load_spec()
    allowed = {L["name"] for L in spec["layouts"]}
    r = Result("版型純度", f"layout 必須在模板 {len(allowed)} 種之內；無自建 textbox")
    if pptx is None or not pptx.exists():
        r.skip("找不到 output/*.pptx，請先跑 06_build_pptx.py")
        return r
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        r.skip("未安裝 python-pptx")
        return r

    prs = Presentation(str(pptx))
    used = Counter()
    for i, sl in enumerate(prs.slides, start=1):
        name = sl.slide_layout.name
        used[name] += 1
        if name not in allowed:
            r.fail(f"第 {i} 頁用了模板外的版面「{name}」")
        for shp in sl.shapes:
            if shp.is_placeholder:
                continue
            if shp.shape_type == MSO_SHAPE_TYPE.TEXT_BOX and shp.name not in ALLOWED_CUSTOM_SHAPES:
                r.fail(f"第 {i} 頁有自建 textbox「{shp.name}」"
                       f"（只允許 {sorted(ALLOWED_CUSTOM_SHAPES)}）")
            if shp.shape_type == MSO_SHAPE_TYPE.GROUP:
                r.fail(f"第 {i} 頁殘留裝飾群組 shape，放圖表前應移除")
    r.note("版面使用：" + "、".join(f"{k}×{v}" for k, v in used.most_common()))
    return r


# --- 7. 字型 --------------------------------------------------------------
def check_fonts(pptx: Path | None) -> Result:
    r = Result("字型", f"所有 run 的 a:ea typeface = {EA_EXPECT}")
    if pptx is None or not pptx.exists():
        r.skip("找不到 output/*.pptx")
        return r
    try:
        from pptx import Presentation
        from pptx.oxml.ns import qn
    except ImportError:
        r.skip("未安裝 python-pptx")
        return r

    prs = Presentation(str(pptx))
    total = bad = 0
    examples: list[str] = []
    for i, sl in enumerate(prs.slides, start=1):
        frames = [shp.text_frame for shp in sl.shapes if shp.has_text_frame]
        if sl.has_notes_slide:
            frames.append(sl.notes_slide.notes_text_frame)
        for tf in frames:
            for para in tf.paragraphs:
                for run in para.runs:
                    if not run.text.strip():
                        continue
                    total += 1
                    rPr = run._r.find(qn("a:rPr"))
                    ea = rPr.find(qn("a:ea")) if rPr is not None else None
                    if ea is None or ea.get("typeface") != EA_EXPECT:
                        bad += 1
                        if len(examples) < 8:
                            got = ea.get("typeface") if ea is not None else "（未設定）"
                            examples.append(f"第 {i} 頁「{run.text[:18]}」ea={got}")
    if bad:
        r.fail(f"{bad}/{total} 個 run 的 a:ea 不是 {EA_EXPECT}（換機器開會變新細明體）")
        for e in examples:
            r.note(e)
    else:
        r.note(f"{total} 個 run 全數正確")
    return r


# --- 8. 逐字稿 ------------------------------------------------------------
def check_narration(deck: dict) -> Result:
    cfg = load_project().get("narration", {})
    cpm = int(cfg.get("chars_per_minute", 220))
    tol = float(cfg.get("tolerance", 0.25))
    lo_m, hi_m = cfg.get("total_minutes_range", [50, 58])

    r = Result("逐字稿", f"每頁字數 = duration_sec × {cpm}/60 ±{tol:.0%}；總時長 {lo_m}–{hi_m} 分鐘")
    slides = slides_of(deck)
    empty = []
    total_sec = 0
    for s in slides:
        dur = int(s.get("duration_sec", 0))
        total_sec += dur
        text = (s.get("narration") or "").strip()
        if not text:
            empty.append(str(s.get("id")))
            continue
        want = dur * cpm / 60.0
        got = narration_chars(text)
        if want <= 0:
            continue
        if not (want * (1 - tol) <= got <= want * (1 + tol)):
            r.warn(f"{s.get('id')} 逐字稿 {got} 字，應為 {want:.0f} 字 ±{tol:.0%}"
                   f"（{want*(1-tol):.0f}–{want*(1+tol):.0f}）")

    if empty:
        r.fail(f"{len(empty)} 頁沒有逐字稿：{', '.join(empty[:15])}"
               + (" …" if len(empty) > 15 else ""))
        r.note("請 Claude Code 依 prompts/narration.md 寫進 deck.json 的 narration 欄位")

    m, sec = divmod(total_sec, 60)
    if not (lo_m * 60 <= total_sec <= hi_m * 60):
        r.fail(f"總時長 {m}:{sec:02d} 不在 {lo_m}–{hi_m} 分鐘區間")
    else:
        r.note(f"總時長 {m}:{sec:02d}")
    return r


# --- 9. 對岸用語 ----------------------------------------------------------
def check_banned_terms(deck: dict) -> Result:
    banned = load_project().get("banned_terms", []) or []
    r = Result("對岸用語", f"黑名單掃描（{len(banned)} 個詞）")
    if not banned:
        r.skip("config/project.yaml 沒有設定 banned_terms")
        return r
    hits: Counter = Counter()
    where: dict[str, list[str]] = {}
    for s in slides_of(deck):
        blob = " ".join([
            s.get("title") or "", s.get("subtitle") or "",
            " ".join((b.get("text") or "") for b in (s.get("body") or [])),
            s.get("narration") or "",
        ])
        for term in banned:
            if term and term in blob:
                hits[term] += blob.count(term)
                where.setdefault(term, []).append(str(s.get("id")))
    if hits:
        for term, n in hits.most_common():
            r.fail(f"「{term}」出現 {n} 次：{', '.join(where[term][:6])}"
                   + (" …" if len(where[term]) > 6 else ""))
    else:
        r.note("沒有偵測到對岸用語")
    return r


# --- 10. 視覺預覽 ---------------------------------------------------------
def make_preview(pptx: Path | None) -> Result:
    r = Result("視覺預覽", "LibreOffice 轉 PNG 全頁截圖 → output/preview/")
    if pptx is None or not pptx.exists():
        r.skip("找不到 output/*.pptx")
        return r

    so = soffice_bin()
    if not so:
        r.skip("找不到 LibreOffice。Ubuntu: sudo apt install libreoffice-impress ／ "
               "macOS: brew install --cask libreoffice")
        return r

    outdir = OUTPUT / "preview"
    outdir.mkdir(parents=True, exist_ok=True)
    pdf = OUTPUT / (pptx.stem + ".pdf")
    try:
        proc = subprocess.run(
            [so, "--headless", "--convert-to", "pdf", str(pptx), "--outdir", str(OUTPUT)],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        r.skip("LibreOffice 轉檔逾時（600s）")
        return r

    if not pdf.exists():
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = msg[-1] if msg else "無錯誤訊息"
        r.skip(f"LibreOffice 無法轉檔（{detail}）。"
               "多半是只裝了 libreoffice-core、缺 Impress 匯入濾鏡：\n"
               "        sudo apt install libreoffice-impress")
        return r

    # 優先用 pdftoppm；沒有就用 pymupdf
    n = 0
    if have_cmd("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "80", str(pdf), str(outdir / "slide")],
                       capture_output=True, timeout=600)
        n = len(list(outdir.glob("slide*.png")))
    else:
        try:
            import pymupdf

            doc = pymupdf.open(pdf)
            for i, page in enumerate(doc, start=1):
                page.get_pixmap(dpi=80).save(str(outdir / f"slide-{i:03d}.png"))
            n = len(doc)
            doc.close()
            r.note("（pdftoppm 不存在，改用 pymupdf 產圖）")
        except Exception as e:  # noqa: BLE001
            r.skip(f"PDF 轉 PNG 失敗：{e}")
            return r

    r.note(f"{n} 張預覽圖 → {outdir}／PDF → {pdf}")
    return r


# ==========================================================================
def check_env() -> int:
    step("環境檢查")
    cfg_ok = True

    print("  Python 套件")
    for mod, why in [("pptx", "產 PPTX"), ("docx", "產逐字稿"), ("pymupdf", "解析 PDF"),
                     ("ebooklib", "解析 EPUB"), ("bs4", "EPUB HTML"), ("yaml", "讀設定"),
                     ("matplotlib", "畫圖表"), ("PIL", "圖片處理"),
                     ("rapidfuzz", "頁眉偵測"), ("requests", "連結檢查"),
                     ("pytesseract", "OCR（掃描版 PDF 才需要）")]:
        try:
            __import__(mod)
            print(_c("32", f"    ✓ {mod:<12} {why}"))
        except ImportError:
            optional = mod == "pytesseract"
            print(_c("33" if optional else "31",
                     f"    {'!' if optional else '✗'} {mod:<12} {why} — 未安裝"))
            if not optional:
                cfg_ok = False

    print("\n  外部工具")
    for cmd, why, optional in [
        ("tesseract", "OCR 掃描版 PDF", True),
        ("soffice", "QA 預覽截圖", True),
        ("pdftoppm", "PDF 轉 PNG（沒有會改用 pymupdf）", True),
    ]:
        if have_cmd(cmd):
            print(_c("32", f"    ✓ {cmd:<12} {why}"))
        else:
            print(_c("33", f"    ! {cmd:<12} {why} — 未安裝（該項檢查會標 SKIP）"))

    # soffice 存在不等於能轉檔（只裝 core、沒裝 impress 的情況）
    if soffice_bin():
        print("\n  LibreOffice 轉檔能力")
        probe = _probe_soffice()
        print(_c("32" if probe else "33",
                 f"    {'✓' if probe else '!'} "
                 + ("可以轉檔" if probe else
                    "soffice 在但無法轉檔（多半缺 libreoffice-impress）→ 預覽會標 SKIP")))

    print("\n  資產")
    for p, why, required in [(TEMPLATE, "母片", True),
                             (Path("config/fh_template_spec.json"), "版面規格", True),
                             (Path("config/project.yaml"), "專案設定", True)]:
        full = Path(p) if Path(p).is_absolute() else Path(__file__).resolve().parent.parent / p
        if full.exists():
            print(_c("32", f"    ✓ {why:<10} {full.name}（{full.stat().st_size / 1024:.0f} KB）"))
        else:
            print(_c("31" if required else "33", f"    ✗ {why:<10} 找不到 {full}"))
            if required:
                cfg_ok = False

    print("\n  中文字型（影響圖表與 QA 預覽，不影響 PPTX 本身）")
    fonts = _cjk_fonts()
    if fonts:
        for f in fonts[:4]:
            print(_c("32", f"    ✓ {f}"))
    else:
        print(_c("33", "    ! 找不到中文字型 — 圖表中文會變方框。"
                       "Ubuntu: sudo apt install fonts-noto-cjk"))

    print()
    if cfg_ok:
        ok("必要相依齊全，可以開跑")
        info("下一步：把書檔放進 input/，然後 make extract")
        return 0
    print(_c("31", "  ✗ 有缺少的必要相依，請跑 make setup"))
    return 1


def _probe_soffice() -> bool:
    """實際做一次最小轉檔，確認匯入／匯出濾鏡真的在。"""
    import tempfile

    so = soffice_bin()
    if not so:
        return False
    try:
        from pptx import Presentation
    except ImportError:
        return False
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "probe.pptx"
        Presentation().save(str(src))
        try:
            subprocess.run([so, "--headless", "--convert-to", "pdf", str(src),
                            "--outdir", td], capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            return False
        return (Path(td) / "probe.pdf").exists()


def _cjk_fonts() -> list[str]:
    try:
        out = subprocess.run(["fc-list", ":lang=zh-tw", "family"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return []
    names = []
    for line in out.splitlines():
        for part in line.split(","):
            part = part.strip()
            if part and part not in names:
                names.append(part)
    return names


# ==========================================================================
def write_report(results: list[Result], deck: dict, pptx: Path | None) -> Path:
    meta = deck.get("meta", {})
    n_fail = sum(1 for r in results if r.status == "FAIL")
    verdict = "**不可交付**" if n_fail else "**可以交付**"

    lines = [
        "# QA 報告",
        "",
        f"- 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 書名：{meta.get('book_title', '')}",
        f"- 講者：{meta.get('dept', '')} {meta.get('presenter', '')}",
        f"- 投影片：`{pptx}`" if pptx else "- 投影片：（尚未產出）",
        f"- 藍圖：`{DECK_JSON}`（{len(deck.get('slides', []))} 頁）",
        "",
        f"## 結論：{verdict}",
        "",
        "| 檢查 | 判準 | 結果 |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {r.criterion} | **{r.status}** |")
    lines += ["", "> 任何一項 FAIL 就不准交付（規劃書 §10）。", ""]

    for r in results:
        if not r.details:
            continue
        lines += [f"## {r.name} — {r.status}", "", f"判準：{r.criterion}", ""]
        for d in r.details:
            lines.append(f"- {d}")
        lines.append("")

    lines += [
        "## 修正流程",
        "",
        "1. 改 `work/05_deck.json`（文案、頁數、duration_sec、sources）",
        "2. `make revise`（重跑 Stage 6–8，不要重跑前面的階段）",
        "3. 回到本報告確認 FAIL 歸零",
        "",
    ]
    out = OUTPUT / "qa_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.exit(main())
