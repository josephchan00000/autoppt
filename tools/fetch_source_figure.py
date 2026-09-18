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

    # 批次：把 Stage 4 記錄的 figure_candidates 一次全部抓回來（推薦）
    python tools/fetch_source_figure.py --from-evidence

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

ROOT = Path(__file__).resolve().parent.parent

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



# ==========================================================================
# 批次：把 Stage 4 記下的 figure_candidates 一次抓完
# ==========================================================================
def _fetch_one(url: str, out: Path) -> tuple[bool, str]:
    """回傳 (成功, 訊息)。訊息要能讓人判斷是政策擋掉還是網址本身有問題。"""
    import requests

    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "ProxyError" in msg or "403" in msg or "Tunnel connection failed" in msg:
            return False, "對外連線被擋（雲端環境的 egress policy）"
        return False, msg[:90]

    ctype = (r.headers.get("Content-Type") or "").lower()
    if "image" not in ctype:
        return False, f"回來的不是圖（{ctype or '沒有 Content-Type'}），多半被導到登入頁"
    if len(r.content) < MIN_BYTES:
        return False, f"只有 {len(r.content)} bytes，不像真的圖表"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    dim = ""
    try:
        from PIL import Image

        with Image.open(out) as im:
            dim = f" {im.width}×{im.height}"
    except Exception:  # noqa: BLE001
        pass
    return True, f"{len(r.content):,} bytes{dim}"


def from_evidence(outdir: Path) -> int:
    """讀 work/04_evidence/*.json 的 figure_candidates，全部抓下來並寫 manifest。

    這一步需要對外連線。雲端環境（Cowork / Claude Code on the web）的 egress
    policy 多半擋掉機構網站，抓不到的會列出來，換到自己的機器再跑一次就好——
    manifest 會記錄哪些已經有了，重跑只會補缺的。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from _common import EVIDENCE, read_json, write_json

    items = []
    for f in sorted(EVIDENCE.glob("ch*.json")):
        try:
            d = read_json(f)
        except Exception:  # noqa: BLE001
            continue
        for i, c in enumerate(d.get("figure_candidates") or []):
            if isinstance(c, dict) and (c.get("figure_url") or "").strip():
                items.append({"ch_id": f.stem, "idx": i, **c})

    if not items:
        print("  沒有任何 figure_candidates。")
        print("  Stage 4 查證時要把機構自己畫的那張圖的網址記進 evidence，")
        print("  見 prompts/research.md 的「機構原圖」段落。")
        return 0

    manifest_path = outdir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}

    print(f"▶ 共 {len(items)} 張候選圖")
    ok_n = skip_n = fail_n = 0
    blocked = False
    for it in items:
        key = f"{it['ch_id']}_{it['idx']:02d}"
        out = outdir / f"{key}.png"
        label = (it.get("title") or it["figure_url"])[:44]

        if out.exists() and out.stat().st_size >= MIN_BYTES:
            print(f"  – {key}  已存在，略過      {label}")
            manifest[key] = {**manifest.get(key, {}), "path": str(out.relative_to(ROOT)),
                             "figure_url": it["figure_url"],
                             "source_title": it.get("source_title", ""),
                             "as_of": it.get("as_of", ""), "title": it.get("title", "")}
            skip_n += 1
            continue

        good, msg = _fetch_one(it["figure_url"], out)
        if good:
            print(f"  ✓ {key}  {msg:<22} {label}")
            manifest[key] = {"path": str(out.relative_to(ROOT)),
                             "figure_url": it["figure_url"],
                             "page_url": it.get("page_url", ""),
                             "source_title": it.get("source_title", ""),
                             "as_of": it.get("as_of", ""), "title": it.get("title", "")}
            ok_n += 1
        else:
            print(f"  ✗ {key}  {msg}")
            print(f"        {it['figure_url']}")
            if "被擋" in msg:
                blocked = True
            fail_n += 1

    write_json(manifest_path, manifest)
    print()
    print(f"  成功 {ok_n}、已有 {skip_n}、失敗 {fail_n} → {manifest_path}")
    if blocked:
        print()
        print("  有圖是被對外連線政策擋掉的，不是網址有問題。")
        print("  把整個資料夾複製到自己的電腦再跑一次這行就會補齊：")
        print("      python tools/fetch_source_figure.py --from-evidence")
    if ok_n or skip_n:
        print()
        print("  抓到的圖**一定要自己開來看過**，確認座標軸與時間範圍跟你要講的一致，")
        print("  再寫進 work/05_deck.json：")
        print('      "image": {"path": "work/09_srcfigs/ch03_00.png"}')
        print("  sources 寫機構全稱與資料時點，不要只寫網址。")
    return 0 if fail_n == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="抓外部機構的官方圖表")
    ap.add_argument("--fred", action="append", default=[], metavar="SERIES",
                    help="FRED 序列代號，可重複給，會畫在同一張（如 DGS10）")
    ap.add_argument("--url", help="直接給圖檔網址（非 FRED 的來源用這個）")
    ap.add_argument("--out", help="輸出 PNG 路徑（--from-evidence 時不需要）")
    ap.add_argument("--from-evidence", action="store_true",
                    help="讀 work/04_evidence/*.json 的 figure_candidates 批次抓")
    ap.add_argument("--outdir", default="work/09_srcfigs",
                    help="批次模式的輸出資料夾")
    ap.add_argument("--start", default="", help="起日 YYYY-MM-DD（只對 --fred 有效）")
    ap.add_argument("--end", default="", help="迄日 YYYY-MM-DD（只對 --fred 有效）")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=750)
    args = ap.parse_args()

    if args.from_evidence:
        return from_evidence(ROOT / args.outdir)

    if not args.fred and not args.url:
        print("✗ 要給 --fred 或 --url，或用 --from-evidence 批次抓", file=sys.stderr)
        return 2
    if not args.out:
        print("✗ 要給 --out", file=sys.stderr)
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
