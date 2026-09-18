#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 — 書檔解析：PDF（文字層）／PDF（掃描，OCR）／EPUB 統一成純文字。

輸出：
    work/01_raw/pages.jsonl          每行 {"page": 12, "text": "..."}
    work/01_raw/toc.json             書籤／目錄（可能為空）
    work/01_raw/ocr_confidence.md    僅 OCR 分支，列出信心值最低的 20 頁

用法：
    python scripts/01_extract.py --input input/book.pdf
    python scripts/01_extract.py --input input/book.epub
    python scripts/01_extract.py --input input/book.pdf --force-ocr
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    PAGES_JSONL, RAW, TOC_JSON, die, ensure_dirs, have_cmd, info, ok, step, warn,
    write_json, write_jsonl,
)

# 幾乎抽不到字就判定為掃描版
TEXT_LAYER_MIN_CHARS = 200
TEXT_LAYER_SAMPLE_PAGES = 8


def _pymupdf():
    """pymupdf 1.24+ 建議用 `import pymupdf`，舊版只有 `fitz`。兩邊都吃。"""
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


# ==========================================================================
# 分派
# ==========================================================================
def extract(path: Path, force_ocr: bool = False, ocr_lang: str = "chi_tra+eng") -> tuple[list[dict], list[dict]]:
    ext = path.suffix.lower()
    if ext == ".epub":
        return extract_epub(path)
    if ext in (".pdf",):
        fitz = _pymupdf()

        doc = fitz.open(path)
        if force_ocr:
            info("--force-ocr 指定，直接走 OCR 分支")
            return extract_pdf_ocr(path, lang=ocr_lang)
        n = min(TEXT_LAYER_SAMPLE_PAGES, len(doc))
        sample = "".join(doc[i].get_text() for i in range(n))
        if len(sample.strip()) < TEXT_LAYER_MIN_CHARS:
            warn(f"前 {n} 頁只抽到 {len(sample.strip())} 個字元 → 判定為掃描版 PDF，走 OCR")
            doc.close()
            return extract_pdf_ocr(path, lang=ocr_lang)
        ok(f"偵測到文字層（前 {n} 頁 {len(sample.strip())} 字元）")
        doc.close()
        return extract_pdf_text(path)
    if ext in (".mobi", ".azw", ".azw3"):
        die(
            f"暫不直接支援 {ext}。請先用 Calibre 轉成 EPUB：\n"
            f"    ebook-convert {path} {path.with_suffix('.epub')}"
        )
    die(f"不支援的格式：{ext}（支援 .pdf / .epub）")


# ==========================================================================
# PDF：有文字層
# ==========================================================================
def extract_pdf_text(path: Path) -> tuple[list[dict], list[dict]]:
    fitz = _pymupdf()

    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc):
        pages.append({"page": i + 1, "text": page.get_text("text") or ""})
    toc = _pdf_toc(doc)
    doc.close()
    pages = clean_pages(pages)
    return pages, toc


def _pdf_toc(doc) -> list[dict]:
    """fitz get_toc() → [[level, title, page], ...]"""
    try:
        raw = doc.get_toc(simple=True) or []
    except Exception as e:  # noqa: BLE001
        warn(f"讀取 PDF 書籤失敗：{e}")
        return []
    return [{"level": lv, "title": (t or "").strip(), "page": pg} for lv, t, pg in raw if pg > 0]


# ==========================================================================
# PDF：掃描版 → OCR
# ==========================================================================
def extract_pdf_ocr(path: Path, lang: str = "chi_tra+eng", dpi: int = 300) -> tuple[list[dict], list[dict]]:
    if not have_cmd("tesseract"):
        die(
            "掃描版 PDF 需要 tesseract，但系統找不到。請先安裝：\n"
            "    Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim\n"
            "    macOS : brew install tesseract tesseract-lang"
        )
    fitz = _pymupdf()
    import pytesseract
    from PIL import Image, ImageOps

    doc = fitz.open(path)
    total = len(doc)
    info(f"OCR 共 {total} 頁（{dpi}dpi, lang={lang}），這會花一段時間…")

    pages: list[dict] = []
    confidences: list[tuple[int, float]] = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        # 灰階 + 二值化，中文辨識率差很多
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img)
        img = img.point(lambda p: 255 if p > 180 else 0, mode="1")

        text = pytesseract.image_to_string(img, lang=lang)
        pages.append({"page": i + 1, "text": text})

        try:
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
            vals = [float(c) for c in data.get("conf", []) if str(c) not in ("-1", "")]
            confidences.append((i + 1, sum(vals) / len(vals) if vals else 0.0))
        except Exception:  # noqa: BLE001
            confidences.append((i + 1, 0.0))

        if (i + 1) % 10 == 0 or i + 1 == total:
            info(f"  OCR 進度 {i + 1}/{total}")

    toc = _pdf_toc(doc)
    doc.close()

    pages = clean_pages(pages, ocr=True)
    _write_ocr_report(confidences, pages)
    return pages, toc


def _write_ocr_report(confidences: list[tuple[int, float]], pages: list[dict]) -> None:
    """列出信心值最低的 20 頁——這是整條 pipeline 最容易埋錯的地方。"""
    by_page = {p["page"]: p for p in pages}
    worst = sorted(confidences, key=lambda x: x[1])[:20]
    avg = sum(c for _, c in confidences) / len(confidences) if confidences else 0

    lines = [
        "# OCR 信心值報告",
        "",
        f"全書平均信心值：**{avg:.1f}**（tesseract conf，0–100）",
        "",
        "下面是信心值最低的 20 頁。**請人工掃一眼**，OCR 錯字會一路汙染到投影片。",
        "信心值 < 60 的頁面建議直接比對原書。",
        "",
        "| 頁碼 | 信心值 | 抽到字數 | 開頭 60 字 |",
        "|---:|---:|---:|---|",
    ]
    for pg, conf in worst:
        text = (by_page.get(pg, {}).get("text") or "").strip().replace("\n", " ").replace("|", "／")
        flag = " ⚠️" if conf < 60 else ""
        lines.append(f"| {pg} | {conf:.1f}{flag} | {len(text)} | {text[:60]} |")

    low = [p for p, c in confidences if c < 60]
    lines += ["", f"信心值 < 60 的頁數共 **{len(low)}** 頁：{low if low else '無'}", ""]

    out = RAW / "ocr_confidence.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    ok(f"OCR 信心值報告 → {out}")
    if low:
        warn(f"有 {len(low)} 頁信心值 < 60，強烈建議人工確認後再往下跑")


# ==========================================================================
# EPUB
# ==========================================================================
def extract_epub(path: Path) -> tuple[list[dict], list[dict]]:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(path))
    pages: list[dict] = []
    # EPUB 沒有實體頁碼，用 spine 順序當「頁」，一個 document 一頁
    href_to_page: dict[str, int] = {}

    for idx, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT), start=1):
        soup = BeautifulSoup(item.get_content(), "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text("\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        pages.append({"page": idx, "text": text, "href": item.get_name()})
        href_to_page[item.get_name()] = idx

    toc = _epub_toc(book, href_to_page)
    pages = clean_pages(pages)
    ok(f"EPUB 解析完成：{len(pages)} 個文件節點")
    return pages, toc


def _epub_toc(book, href_to_page: dict[str, int]) -> list[dict]:
    out: list[dict] = []

    def walk(items, level=1):
        for it in items:
            if isinstance(it, (tuple, list)):
                if it and hasattr(it[0], "title"):
                    walk([it[0]], level)
                    walk(it[1] if len(it) > 1 else [], level + 1)
                else:
                    walk(it, level)
                continue
            title = (getattr(it, "title", "") or "").strip()
            href = (getattr(it, "href", "") or "").split("#")[0]
            if title:
                out.append({"level": level, "title": title, "page": href_to_page.get(href, 0), "href": href})

    try:
        walk(book.toc)
    except Exception as e:  # noqa: BLE001
        warn(f"讀取 EPUB 目錄失敗：{e}")
    return out


# ==========================================================================
# 清理：頁眉頁腳、斷字、硬斷段落
# ==========================================================================
def clean_pages(pages: list[dict], ocr: bool = False) -> list[dict]:
    """移除頁眉頁腳、行尾斷字、合併被硬斷的段落。"""
    running = detect_running_heads(pages)
    if running:
        info(f"偵測到 {len(running)} 組頁眉／頁腳，已移除：{[r[:20] for r in list(running)[:5]]}")

    cleaned = []
    for p in pages:
        text = p.get("text") or ""
        lines = [ln.rstrip() for ln in text.splitlines()]
        lines = [ln for ln in lines if _norm(ln) not in running]
        text = "\n".join(lines)

        # 英文行尾連字號斷字：inves-\ntment → investment
        text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)
        # 中文被硬斷的行：前一行尾不是標點、下一行首不是標點 → 接起來
        text = re.sub(r"([一-鿿])\n([一-鿿])", r"\1\2", text)
        if ocr:
            # OCR 常把全形空白塞進中文之間
            text = re.sub(r"(?<=[一-鿿])[ 　]+(?=[一-鿿])", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        q = dict(p)
        q["text"] = text
        cleaned.append(q)
    return cleaned


def _norm(s: str) -> str:
    """正規化：去空白、去純數字（頁碼本身每頁不同，但樣板一樣）。"""
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"[0-9０-９]+", "#", s)
    return s


def detect_running_heads(pages: list[dict], threshold: float = 0.6, max_len: int = 40) -> set[str]:
    """出現在 >60% 頁面的短字串就是頁眉頁腳（規劃書 §4.1）。

    用 rapidfuzz 對候選做模糊歸併，避免 OCR 一兩個字差異就漏掉。
    """
    if len(pages) < 5:
        return set()

    counter: Counter[str] = Counter()
    for p in pages:
        lines = (p.get("text") or "").splitlines()
        # 只看每頁前 2 行與後 2 行
        for ln in lines[:2] + lines[-2:]:
            n = _norm(ln)
            if 0 < len(n) <= max_len:
                counter[n] += 1

    need = max(3, int(len(pages) * threshold))
    heads = {s for s, c in counter.items() if c >= need}

    # rapidfuzz 模糊歸併：與已知頁眉高度相似的變體也一起移除
    try:
        from rapidfuzz import fuzz

        for s, c in counter.items():
            if s in heads or c < 3:
                continue
            if any(fuzz.ratio(s, h) >= 90 for h in list(heads)):
                heads.add(s)
    except ImportError:
        pass
    return heads


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 1：書檔解析")
    ap.add_argument("--input", "-i", required=True, help="input/book.pdf | input/book.epub")
    ap.add_argument("--force-ocr", action="store_true", help="強制走 OCR（文字層品質很差時用）")
    ap.add_argument("--ocr-lang", default="chi_tra+eng")
    args = ap.parse_args()

    ensure_dirs()
    path = Path(args.input)
    if not path.exists():
        die(f"找不到書檔：{path}")

    step(f"Stage 1 解析書檔：{path.name}（{path.stat().st_size / 1e6:.1f} MB）")
    pages, toc = extract(path, force_ocr=args.force_ocr, ocr_lang=args.ocr_lang)

    total_chars = sum(len(p["text"]) for p in pages)
    if total_chars < 1000:
        die(f"只抽到 {total_chars} 個字元，解析顯然失敗了。掃描版請加 --force-ocr。")

    write_jsonl(PAGES_JSONL, pages)
    write_json(TOC_JSON, {"source": path.name, "entries": toc})

    ok(f"pages.jsonl  {len(pages)} 頁 / {total_chars:,} 字元 → {PAGES_JSONL}")
    if toc:
        ok(f"toc.json     {len(toc)} 個目錄節點 → {TOC_JSON}")
        for e in toc[:8]:
            info(f"    L{e['level']} p.{e['page']:>4}  {e['title'][:40]}")
        if len(toc) > 8:
            info(f"    …（共 {len(toc)} 筆）")
    else:
        warn("書檔沒有書籤／目錄，Stage 2 會退回正規式掃描章節標題")

    empty = [p["page"] for p in pages if not p["text"].strip()]
    if empty:
        warn(f"{len(empty)} 頁沒有任何文字：{empty[:20]}{' …' if len(empty) > 20 else ''}")

    print()
    info("下一步：python scripts/02_split_chapters.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
