#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「跑下一步」：自動判斷現在在哪一階段，印出該做什麼、做完要給使用者看什麼。

使用者通常只會說「跑下一步」或「繼續」。這支負責回答三個問題：

    1. 現在在哪一步？        （逐項檢查檔案與進度，第一個沒過的就是現在該做的）
    2. 這一步要做什麼？      （是打一行指令，還是 Claude 自己要讀提示詞寫 JSON）
    3. 做完要給使用者看什麼？（每一步都要停下來確認，這是使用者明講的要求）

    python scripts/00_next.py          # 印下一步
    python scripts/00_next.py --all    # 印完整進度表

判斷順序寫死在 STAGES，新增階段就在那裡加一列，不要散在各處。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    AUTHOR_JSON, CHAPTERS, DECK_JSON, DIGEST, EVIDENCE, GUIDE_JSON, INPUT, OUTPUT,
    PAGES_JSONL, ROOT, TEMPLATE, WORK, _c, info, read_json, step, talk_slides,
)

BOOKFIGS = WORK / "08_bookfigs"
PY = ".venv/bin/python"


# --------------------------------------------------------------------------
# 各階段的完成條件
# --------------------------------------------------------------------------
def _book_file() -> Path | None:
    for pat in ("book.*", "*.pdf", "*.epub", "*.mobi", "*.txt"):
        hits = sorted(INPUT.glob(pat))
        if hits:
            return hits[0]
    return None


def _digest_done() -> tuple[int, int]:
    """(補充完成章數, 總章數)。缺 key_terms / stories 的章不算完成。"""
    chs = sorted(CHAPTERS.glob("ch*.md"))
    done = 0
    for f in sorted(DIGEST.glob("ch*.json")):
        try:
            d = read_json(f)
        except Exception:
            continue
        if d.get("key_terms") and d.get("stories") and d.get("chapter_title_en"):
            done += 1
    return done, len(chs)


def _evidence_done() -> tuple[int, int]:
    return len(list(EVIDENCE.glob("ch*.json"))), len(list(CHAPTERS.glob("ch*.md")))


def _deck_stats() -> dict:
    if not DECK_JSON.exists():
        return {}
    deck = read_json(DECK_JSON)
    slides = deck.get("slides") or []
    talk = talk_slides(slides)
    blob = json.dumps(deck, ensure_ascii=False)
    return {
        "pages": len(slides),
        "talk": len(talk),
        "todo": blob.count("【待填】"),
        "narrated": sum(1 for s in talk if (s.get("narration") or "").strip()),
        "hints": sum(1 for s in slides if s.get("image_hint")),
    }


def _outputs() -> dict:
    return {
        "pptx": sorted(OUTPUT.glob("*.pptx")),
        "pdf": sorted(OUTPUT.glob("*.pdf")),
        "docx": sorted(OUTPUT.glob("*逐字稿*.docx")),
        "imglist": (OUTPUT / "圖片建議.md").exists(),
        "qa": (OUTPUT / "qa_report.md").exists(),
    }


# 每一列：(代號, 名稱, 完成了沒, 這一步做什麼, 做完給使用者看什麼)
def stages() -> list[dict]:
    d_done, d_total = _digest_done()
    e_done, e_total = _evidence_done()
    st = _deck_stats()
    out = _outputs()
    book = _book_file()

    return [
        dict(key="0", name="環境",
             done=(ROOT / ".venv").exists() and TEMPLATE.exists(),
             detail="母片 assets/FH_template.pptx、虛擬環境 .venv",
             todo=f"make setup（第一次）或 make check",
             show="環境檢查的輸出；缺 tesseract / libreoffice-impress 只會標 SKIP，不擋流程"),
        dict(key="1", name="書檔",
             # 解析完成之後書檔可以移走（版權內容不進 repo），所以兩者其一即可
             done=book is not None or PAGES_JSONL.exists(),
             detail=f"input/{book.name}" if book else "input/ 是空的（已解析過，書檔可以不留）",
             todo="把書的電子檔放進 input/（PDF / EPUB 都可以）",
             show="書名、頁數，確認是要導讀的那一本"),
        dict(key="2", name="解析",
             done=PAGES_JSONL.exists(),
             detail=f"{PAGES_JSONL.relative_to(ROOT)}",
             todo=f"{PY} scripts/01_extract.py --input input/<書檔>",
             show="總頁數與抽出字數；掃描版會走 OCR，要他看 work/01_raw/ocr_confidence.md"),
        dict(key="3", name="拆章",
             done=len(list(CHAPTERS.glob("ch*.md"))) > 0,
             detail=f"{len(list(CHAPTERS.glob('ch*.md')))} 章",
             todo=f"{PY} scripts/02_split_chapters.py",
             show="章節清單表格。字數異常（紅字）代表拆錯，問他要不要換策略或手改 md"),
        dict(key="4a", name="作者解析",
             done=AUTHOR_JSON.exists(),
             detail="work/04_author.json（含中譯本官方章名）",
             todo=f"{PY} scripts/04_research.py --author  → Claude 用 WebSearch 查證後寫檔 → --validate-author",
             show="作者背景／生涯／評價各一句，以及查到的官方中譯章名清單"),
        dict(key="3b", name="逐章深讀",
             done=d_total > 0 and d_done >= d_total,
             detail=f"{d_done}/{d_total} 章（要含章名、原書用語、故事）",
             todo=f"{PY} scripts/03_digest.py --next  → Claude 讀提示詞寫 JSON → --validate chNN",
             show="先跑兩章就停，把 key_terms 與 stories 貼給他看品質對不對"),
        dict(key="4b", name="外部研究",
             done=e_total > 0 and e_done >= e_total,
             detail=f"{e_done}/{e_total} 章",
             todo=f"{PY} scripts/04_research.py --next  → Claude 用 WebSearch 查證 → --validate chNN",
             show="每章的 taiwan_lens 與 outdated 數據；URL 一定要是 WebSearch 真的回傳的"),
        dict(key="4c", name="書中原圖",
             done=BOOKFIGS.exists() and len(list(BOOKFIGS.glob("*.png"))) > 0,
             detail=f"{len(list(BOOKFIGS.glob('*.png'))) if BOOKFIGS.exists() else 0} 張",
             todo=f"{PY} tools/extract_book_figures.py --input input/<書檔> --out work/08_bookfigs",
             show="抽出來的圖自己先開來看過，是圖表才留，書衣與裝飾線要排除"),
        dict(key="5a", name="導讀設計",
             done=GUIDE_JSON.exists(),
             detail="work/05a_guide.json",
             todo=f"{PY} scripts/05_outline.py --guide-prompt  → Claude 寫 guide.json → --validate-guide",
             show="主線章清單（章名＋headline）與 book_claim，連著唸一遍要像一段話"),
        dict(key="5b", name="藍圖",
             done=DECK_JSON.exists(),
             detail=f"{st.get('pages', 0)} 頁（講述 {st.get('talk', 0)}）",
             todo=f"{PY} scripts/05_outline.py",
             show="頁面組成表與預估時長"),
        dict(key="5c", name="文案潤飾",
             done=bool(st) and st.get("todo", 1) == 0,
             detail=f"殘留【待填】{st.get('todo', '?')} 處",
             todo=f"Claude 依 prompts/outline.md 潤飾 work/05_deck.json（先讀 meta.tone_directive_slide）"
                  f" → {PY} scripts/08_qa.py --check-deck",
             show="幾頁有代表性的文案（卡片頁、表格頁、雙欄頁各一），這是最省時的修改點"),
        dict(key="6", name="逐字稿文字",
             done=bool(st) and st.get("talk", 0) > 0 and st.get("narrated", 0) >= st.get("talk", 1),
             detail=f"{st.get('narrated', 0)}/{st.get('talk', 0)} 頁有 narration",
             todo="Claude 依 prompts/narration.md 把逐字稿寫進 deck.json 的 narration"
                  "（每章用該章故事開場，先讀 meta.tone_directive_narration）",
             show="開場三頁與任一章的逐字稿，確認語氣對不對"),
        dict(key="7", name="產出",
             done=bool(out["pptx"]) and bool(out["pdf"]) and bool(out["docx"]),
             detail=f"pptx {len(out['pptx'])}／pdf {len(out['pdf'])}／docx {len(out['docx'])}",
             todo=f"{PY} scripts/06_build_pptx.py（自動轉 PDF）&& {PY} scripts/07_build_script.py",
             show="PDF 直接翻，PPT 換台電腦容易跑版"),
        dict(key="8a", name="圖片建議",
             done=out["imglist"],
             detail="output/圖片建議.md",
             todo=f"{PY} tools/image_suggestions.py",
             show="清單本身；章名頁籤上有虛線佔位框，他換成自己找的圖就好"),
        dict(key="8b", name="品管",
             done=out["qa"],
             detail="output/qa_report.md",
             todo=f"{PY} scripts/08_qa.py --all",
             show="FAIL 一項都不能有；WARN 要唸給他聽，讓他決定要不要改"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="判斷現在在哪一階段，印出下一步")
    ap.add_argument("--all", action="store_true", help="印完整進度表")
    args = ap.parse_args()

    rows = stages()
    step("進度")
    for r in rows:
        mark = _c("32", "●") if r["done"] else _c("31", "○")
        name = f"{r['name']}（{r['key']}）"
        print(f"  {mark} {name:<16}{r['detail']}")
        if not args.all and not r["done"]:
            break

    nxt = next((r for r in rows if not r["done"]), None)
    print()
    if nxt is None:
        print(_c("32;1", "  ✓ 全部完成。"))
        info("交付前再確認一次：qa_report.md 沒有 FAIL、PDF 頁數與 PPTX 一致、"
             "圖片建議清單給了使用者")
        info(f"打包：git archive --format=zip --prefix=autoppt/ -o autoppt.zip HEAD")
        return 0

    print(_c("36;1", f"  ▶ 下一步：{nxt['name']}"))
    print(f"     做什麼：{nxt['todo']}")
    print(f"     做完給使用者看：{nxt['show']}")
    print()
    print(_c("33;1", "  ✋ 這一步做完就停下來，等使用者確認再往下。"))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
