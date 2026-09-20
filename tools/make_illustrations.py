#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 work/10_illus/*.svg 轉成投影片用的 PNG。

SVG 是**你自己畫的**（規則見 prompts/illustration.md）。雲端抓不到照片，
機構網站與圖庫都被 egress 白名單擋掉；自己畫的向量圖沒有這個問題，
也沒有授權問題。

    python tools/make_illustrations.py             # 全部轉檔
    python tools/make_illustrations.py --contact   # 順便出一張總覽圖，自己看過再收
    python tools/make_illustrations.py --status    # 哪幾章還沒畫

檔名就是頁面 id（`work/05_deck.json` 裡章名頁籤那一頁的 `id`，例如 s009.svg）。
轉出來的 PNG 放在同一個資料夾，06_build_pptx.py 會自動撿。

**畫完一定要自己看過 contact.png**。幾何造型（建築、器物、圖表、山形）畫得好，
人臉與動物畫不好，會變成一團色塊——那種就重畫成物件。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _common import (  # noqa: E402
    DECK_JSON, WORK, die, info, ok, read_json, step, stop, warn,
)

ILLUS = WORK / "10_illus"
DPI = 300              # 2.76 吋寬的框，300dpi 約 830px，投影與列印都夠


def render(svg: Path, dpi: int = DPI) -> Path | None:
    try:
        import pymupdf
    except ImportError:
        die("需要 pymupdf：.venv/bin/pip install pymupdf")
    png = svg.with_suffix(".png")
    try:
        doc = pymupdf.open(svg)
        doc[0].get_pixmap(dpi=dpi).save(png)
    except Exception as e:  # noqa: BLE001  SVG 寫壞了要講清楚是哪一個檔
        warn(f"{svg.name} 轉檔失敗：{e}")
        return None
    return png


def contact_sheet(pngs: list[Path], dest: Path, cols: int = 4) -> bool:
    try:
        from PIL import Image
    except ImportError:
        warn("沒有 Pillow，略過總覽圖")
        return False
    tw = th = 240
    rows = (len(pngs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    for i, p in enumerate(pngs):
        with Image.open(p) as im:
            im = im.convert("RGB").resize((tw - 12, th - 12))
            sheet.paste(im, ((i % cols) * tw + 6, (i // cols) * th + 6))
    sheet.save(dest)
    return True


def wanted(deck_path: Path) -> list[tuple[str, str]]:
    """需要示意圖的頁面：章名頁籤（有 image_hint 的那些）。"""
    if not deck_path.exists():
        return []
    out = []
    for s in read_json(deck_path).get("slides") or []:
        if s.get("image_hint"):
            out.append((s.get("id", ""), (s.get("title") or "").strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="把手繪 SVG 轉成投影片用的 PNG")
    ap.add_argument("--deck", default=str(DECK_JSON))
    ap.add_argument("--dpi", type=int, default=DPI)
    ap.add_argument("--contact", action="store_true", help="順便出一張總覽圖")
    ap.add_argument("--status", action="store_true", help="只列出哪幾章還沒畫")
    args = ap.parse_args()

    step("示意圖")
    need = wanted(Path(args.deck))
    have = {f.stem for f in ILLUS.glob("*.svg")}

    if args.status:
        for sid, title in need:
            mark = "●" if sid in have else "○"
            print(f"  {mark} {sid:<8}{title}")
        missing = [s for s, _ in need if s not in have]
        print()
        info(f"{len(need) - len(missing)}/{len(need)} 章已畫")
        if missing:
            info(f"還沒畫：{', '.join(missing)}　（規則見 prompts/illustration.md）")
        return 0

    ILLUS.mkdir(parents=True, exist_ok=True)
    svgs = sorted(ILLUS.glob("*.svg"))
    if not svgs:
        warn(f"{ILLUS} 是空的。依 prompts/illustration.md 把 SVG 畫進去，檔名用頁面 id")
        return 0

    pngs = [p for p in (render(s, args.dpi) for s in svgs) if p]
    ok(f"{len(pngs)}/{len(svgs)} 張 → {ILLUS}")

    unused = sorted(p.stem for p in svgs if p.stem not in {s for s, _ in need})
    if unused:
        warn(f"這幾張沒有對應的頁面，檔名可能打錯：{', '.join(unused)}")
    missing = [f"{s}（{t}）" for s, t in need if s not in have]
    if missing:
        warn(f"還沒畫：{', '.join(missing)}")

    if args.contact and pngs:
        dest = ILLUS / "contact.png"
        if contact_sheet(pngs, dest):
            ok(f"總覽圖 → {dest}")

    stop("這些圖自己看過了嗎？",
         f"{ILLUS / 'contact.png'}（--contact 產生）；人臉與動物畫不好就改成物件",
         "python scripts/06_build_pptx.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
