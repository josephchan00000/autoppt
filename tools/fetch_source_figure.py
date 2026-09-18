#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓外部機構自己畫的圖表，直接放上投影片（見 prompts/visuals.md 第 2 級）。

聯準會的圖長得像聯準會，可信度是附帶的——比拿它的數字自己重畫有說服力得多。

    # FRED（美國聖路易聯邦準備銀行），指定序列代號
    python tools/fetch_source_figure.py --fred DGS10 --start 2015-01-01 \\
        --out work/09_srcfigs/dgs10.png

    # 兩條序列畫在同一張
    python tools/fetch_source_figure.py --fred DGS10 --fred FEDFUNDS \\
        --start 2000-01-01 --out work/09_srcfigs/rates.png

    # 其他機構：直接給那張圖的實際網址
    python tools/fetch_source_figure.py \\
        --url "https://www.bis.org/statistics/xxx/chart.png" \\
        --out work/09_srcfigs/bis.png

注意：
- 只抓得到**靜態圖檔**。很多機構的圖是瀏覽器用 JS 畫的，沒有靜態檔，
  這支就抓不到——抓不到就往 visuals.md 的第 3 級走，不要硬拗。
- 雲端環境（Cowork、Claude Code on the web）的對外連線走 proxy，
  多半會被擋，這支只有在使用者自己的機器上跑得動。
- 抓下來一定要自己開圖看過，確認座標軸與時間範圍跟你要講的一致。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlencode

FRED_GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.png"
UA = "Mozilla/5.0 (compatible; autoppt/1.0; +internal book-share deck)"
MIN_BYTES = 2048          # 比這還小多半是錯誤頁或佔位圖


def build_fred_url(series: list[str], start: str, end: str, width: int, height: int) -> str:
    q = {"id": ",".join(series), "width": width, "height": height}
    if start:
        q["cosd"] = start
    if end:
        q["coed"] = end
    return f"{FRED_GRAPH}?{urlencode(q)}"


def main() -> int:
    ap = argparse.ArgumentParser(description="抓外部機構的官方圖表")
    ap.add_argument("--fred", action="append", default=[], metavar="SERIES",
                    help="FRED 序列代號，可重複給，會畫在同一張（如 DGS10）")
    ap.add_argument("--url", help="直接給圖檔網址（非 FRED 的來源用這個）")
    ap.add_argument("--out", required=True, help="輸出 PNG 路徑")
    ap.add_argument("--start", default="", help="起日 YYYY-MM-DD（只對 --fred 有效）")
    ap.add_argument("--end", default="", help="迄日 YYYY-MM-DD（只對 --fred 有效）")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=750)
    args = ap.parse_args()

    if not args.fred and not args.url:
        print("✗ 要給 --fred 或 --url 其中一個", file=sys.stderr)
        return 2
    if args.fred and args.url:
        print("✗ --fred 與 --url 只能擇一", file=sys.stderr)
        return 2

    url = args.url or build_fred_url(args.fred, args.start, args.end, args.width, args.height)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"▶ 抓圖 {url}")
    try:
        import requests
    except ImportError:
        print("✗ 需要 requests：pip install requests", file=sys.stderr)
        return 1

    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"✗ 抓不到：{e}", file=sys.stderr)
        print("  這通常是三種情況之一：", file=sys.stderr)
        print("    1. 在雲端環境跑，對外連線被 proxy 擋掉 → 換到本機跑", file=sys.stderr)
        print("    2. 那張圖是 JS 畫的，沒有靜態檔 → 改走 visuals.md 第 3 級", file=sys.stderr)
        print("    3. 網址過期或打錯 → 回原始頁面重找", file=sys.stderr)
        return 1

    ctype = (r.headers.get("Content-Type") or "").lower()
    if "image" not in ctype:
        print(f"✗ 回來的不是圖（Content-Type: {ctype or '未提供'}）", file=sys.stderr)
        print("  多半是被導到錯誤頁或登入頁，請開瀏覽器確認那個網址。", file=sys.stderr)
        return 1
    if len(r.content) < MIN_BYTES:
        print(f"✗ 檔案只有 {len(r.content)} bytes，看起來不是真的圖表", file=sys.stderr)
        return 1

    out.write_bytes(r.content)
    size = ""
    try:
        from PIL import Image
        with Image.open(out) as im:
            size = f"  {im.width}×{im.height}"
    except Exception:  # noqa: BLE001
        pass
    print(f"  ✓ {out}（{len(r.content):,} bytes{size}）")
    print()
    print("  下一步：自己開圖看過，確認座標軸與時間範圍跟你要講的一致，")
    print("          再寫進 work/05_deck.json：")
    print(f'          "image": {{"path": "{out}"}}')
    print("          sources 要寫機構全稱與資料時點，不要只寫網址。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
