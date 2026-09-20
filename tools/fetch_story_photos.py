#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""到 Wikimedia Commons 找章名頁籤要用的照片，抓回來讓使用者挑。

**這支要在可以上網的電腦跑。** 雲端 session 的對外連線是白名單，
Commons 的 API 與圖檔網址都會被擋（CONNECT tunnel failed, 403），
所以簡報裡預設畫的是「場景卡」（年份／人物／地點），不是照片。

    python tools/fetch_story_photos.py                 # 每頁抓 4 張候選
    python tools/fetch_story_photos.py --per-page 6    # 多抓幾張
    python tools/fetch_story_photos.py --only s009     # 只補某幾頁

流程：

    1. 這支把候選圖放進 work/09_photos/_candidates/<頁面 id>/
       每個資料夾附一份 授權.md，寫明授權、作者、原始網址
    2. 你自己開圖挑一張，確認授權可以用
    3. 複製成 work/09_photos/<頁面 id>.jpg（副檔名照原檔）
    4. make revise —— 06_build_pptx.py 看到檔案就會自動用照片取代場景卡

**只抓 Wikimedia Commons**：那裡的圖至少標了授權。即便如此，
授權還是要自己看過——CC BY 要標作者，CC BY-SA 要同樣方式分享，
公有領域才真的可以隨便用。授權.md 把每一張的授權原文抄下來給你判斷。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _common import (  # noqa: E402
    DECK_JSON, WORK, die, info, ok, read_json, step, stop, warn,
)

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia 要求帶可辨識的 User-Agent，不然會被擋
UA = "autoppt/1.0 (book-deck pipeline; contact: repo owner)"
PHOTOS = WORK / "09_photos"
CANDIDATES = PHOTOS / "_candidates"
OK_EXT = (".jpg", ".jpeg", ".png")


def _get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _meta(info_block: dict) -> dict:
    ext = info_block.get("extmetadata") or {}

    def val(key: str) -> str:
        raw = (ext.get(key) or {}).get("value") or ""
        return re.sub(r"<[^>]+>", "", raw).strip()   # extmetadata 會夾 HTML

    return {
        "license": val("LicenseShortName") or val("UsageTerms") or "未標示",
        "artist": val("Artist"),
        "credit": val("Credit"),
        "desc": val("ImageDescription")[:200],
    }


def search(query: str, limit: int) -> list[dict]:
    """用關鍵字搜 Commons 的檔案（namespace 6），回傳縮圖網址與授權。"""
    try:
        data = _get({
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": 1400,
        })
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise RuntimeError(str(e)) from e

    out = []
    for page in (data.get("query") or {}).get("pages", {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        if not ii.get("thumburl"):
            continue
        if not (ii.get("mime") or "").startswith("image/"):
            continue
        if not any((ii.get("url") or "").lower().endswith(x) for x in OK_EXT):
            continue
        out.append({
            "title": page.get("title", ""),
            "thumb": ii["thumburl"],
            "page": ii.get("descriptionurl", ""),
            **_meta(ii),
        })
    return out


def download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:  # noqa: BLE001  網路什麼都可能壞，訊息帶出來就好
        warn(f"下載失敗 {dest.name}：{e}")
        return False


def hints(deck: dict, only: set[str]) -> list[tuple[str, str, dict]]:
    out = []
    for s in deck.get("slides") or []:
        h = s.get("image_hint")
        sid = s.get("id") or ""
        if not h or (only and sid not in only):
            continue
        out.append((sid, (s.get("title") or "").strip(), h))
    return out


def query_of(hint: dict) -> str:
    """英文關鍵字優先（Commons 的檔名與說明大多是英文），沒有才用中文。"""
    en = (hint.get("keywords_en") or "").strip()
    if en:
        return en
    return " ".join(x for x in (hint.get("who"), hint.get("where")) if x).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="到 Wikimedia Commons 找章名頁籤的照片")
    ap.add_argument("--deck", default=str(DECK_JSON))
    ap.add_argument("--per-page", type=int, default=4, help="每頁抓幾張候選（預設 4）")
    ap.add_argument("--only", nargs="*", default=[], help="只處理這幾個頁面 id")
    args = ap.parse_args()

    deck_path = Path(args.deck)
    if not deck_path.exists():
        die(f"找不到 {deck_path}，請先跑 05_outline.py")

    step("找照片（Wikimedia Commons）")
    items = hints(read_json(deck_path), set(args.only))
    if not items:
        warn("deck.json 裡沒有 image_hint，沒東西可以找")
        return 0

    CANDIDATES.mkdir(parents=True, exist_ok=True)
    got = skipped = 0
    for sid, title, hint in items:
        if any((PHOTOS / f"{sid}{e}").exists() for e in OK_EXT):
            info(f"{sid} {title}　已經有照片，跳過")
            skipped += 1
            continue
        q = query_of(hint)
        if not q:
            info(f"{sid} {title}　沒有可用的關鍵字（故事裡沒有人名），跳過")
            skipped += 1
            continue

        try:
            hits = search(q, args.per_page)
        except RuntimeError as e:
            die(f"連不上 Wikimedia（{e}）。\n"
                f"  這支要在可以上網的電腦跑；雲端 session 的對外連線是白名單，Commons 被擋。")

        if not hits:
            info(f"{sid} {title}　搜「{q}」沒有結果")
            skipped += 1
            continue

        folder = CANDIDATES / sid
        folder.mkdir(parents=True, exist_ok=True)
        lines = [f"# {sid}　{title}\n\n",
                 f"- 搜尋關鍵字：`{q}`\n",
                 f"- 要拍到什麼：{hint.get('what', '')}\n\n",
                 "**授權要自己確認**：公有領域才可以隨便用；"
                 "CC BY 要標作者；CC BY-SA 要以相同方式分享。\n\n"]
        n = 0
        for i, h in enumerate(hits, start=1):
            ext = Path(urllib.parse.urlparse(h["thumb"]).path).suffix.lower() or ".jpg"
            dest = folder / f"{i:02d}{ext}"
            if not download(h["thumb"], dest):
                continue
            n += 1
            lines += [f"## {dest.name}\n\n",
                      f"- 檔名：{h['title']}\n",
                      f"- 授權：**{h['license']}**\n",
                      f"- 作者：{h['artist'] or '未標示'}\n",
                      f"- 來源：{h['credit'] or '未標示'}\n",
                      f"- 原始頁面：{h['page']}\n",
                      (f"- 說明：{h['desc']}\n" if h["desc"] else ""),
                      "\n"]
        (folder / "授權.md").write_text("".join(lines), encoding="utf-8")
        ok(f"{sid} {title}　{n} 張 → {folder}")
        got += n

    print()
    info(f"候選 {got} 張，跳過 {skipped} 頁")
    stop("挑好圖、確認授權了嗎？",
         f"work/09_photos/_candidates/<頁面 id>/ 裡的圖與同資料夾的 授權.md",
         "挑中的複製成 work/09_photos/<頁面 id>.jpg，然後 make revise")
    return 0


if __name__ == "__main__":
    sys.exit(main())
