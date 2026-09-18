#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從書檔 PDF 抽出內嵌的圖表影像，供投影片直接引用（見 prompts/visuals.md 第 1 級）。

    python tools/extract_book_figures.py --input input/book.pdf --out work/08_bookfigs

輸出檔名是 pNNN.png（NNN = PDF 頁碼），方便對回章節區間與 page_ref。
抽完一定要自己開圖看過：書衣、作者照片、裝飾線條也會被抽出來。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="抽出 PDF 內嵌圖表")
    ap.add_argument("--input", required=True, help="書檔 PDF")
    ap.add_argument("--out", default="work/08_bookfigs", help="輸出目錄")
    ap.add_argument("--min-width", type=int, default=300, help="小於這個寬度就略過")
    ap.add_argument("--min-height", type=int, default=200, help="小於這個高度就略過")
    ap.add_argument("--pages", default="", help="只抽這幾頁，逗號分隔，如 12,35,46")
    args = ap.parse_args()

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # noqa: N813
        except ImportError:
            print("✗ 需要 pymupdf：pip install pymupdf", file=sys.stderr)
            return 1

    src = Path(args.input)
    if not src.exists():
        print(f"✗ 找不到 {src}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    only = {int(x) for x in args.pages.split(",") if x.strip()} if args.pages else None
    doc = pymupdf.open(str(src))
    made = skipped = 0

    print(f"▶ 掃描 {src.name}（{len(doc)} 頁）")
    for pno in range(len(doc)):
        page_no = pno + 1
        if only and page_no not in only:
            continue
        for im in doc[pno].get_images(full=True):
            xref = im[0]
            try:
                pix = pymupdf.Pixmap(doc, xref)
            except Exception as e:  # noqa: BLE001
                print(f"  ! p.{page_no} xref={xref} 讀取失敗：{e}")
                continue
            if pix.width < args.min_width or pix.height < args.min_height:
                skipped += 1
                del pix
                continue
            if pix.n - pix.alpha >= 4:                # CMYK → RGB
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            dst = out / f"p{page_no:03d}.png"
            if dst.exists():                          # 同頁多張圖
                i = 2
                while (out / f"p{page_no:03d}_{i}.png").exists():
                    i += 1
                dst = out / f"p{page_no:03d}_{i}.png"
            pix.save(str(dst))
            print(f"  ✓ {dst.name}  {pix.width}×{pix.height}")
            made += 1
            del pix

    print()
    print(f"  ✓ 抽出 {made} 張 → {out}（另有 {skipped} 張未達尺寸門檻，已略過）")
    print("  下一步：自己開圖看過，確認是圖表而非書衣／照片／裝飾，")
    print("          再把路徑寫進 work/05_deck.json 的 image 欄位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
