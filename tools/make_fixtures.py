#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生合成測試資料，讓 Stage 5→8 可以在沒有真書的情況下跑通。

    python tools/make_fixtures.py --chapters 8

會寫入 work/02_chapters/、work/03_digest/、work/04_evidence/。
所有數值都是**假的**，source_title 都標了「測試資料」，不要拿去用。
真書上線前記得 make clean-work。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _common import CHAPTERS, DIGEST, EVIDENCE, ensure_dirs, ok, step, write_json  # noqa: E402

TOPICS = [
    ("配置決定績效，選股扣成本後歸零", "資產配置"),
    ("波動不是風險，永久損失才是", "風險的定義"),
    ("分散要跨因子，不是跨檔數", "分散化的真相"),
    ("成本是唯一能事先確定的變數", "費用的複利"),
    ("再平衡賣的是情緒，不是資產", "再平衡紀律"),
    ("擇時的勝率門檻高到不值得賭", "擇時的代價"),
    ("流動性溢酬只在你不需要錢時存在", "流動性錯覺"),
    ("報酬順序風險決定退休成敗", "提領階段"),
    ("指數化不是被動，是紀律外包", "指數化"),
    ("行為缺口吃掉三分之一的報酬", "行為缺口"),
]

REAL_URLS = [
    ("主計總處《家庭收支調查》", "https://www.stat.gov.tw/cp.aspx?n=2773"),
    ("金管會證期局統計資料", "https://www.sfb.gov.tw/ch/home.jsp?id=93&parentpath=0,3"),
    ("中華民國中央銀行統計資料庫", "https://www.cbc.gov.tw/tw/lp-370-1.html"),
    ("投信投顧公會統計資料", "https://www.sitca.org.tw/ROC/Industry/IN2001.aspx"),
    ("臺灣證券交易所統計月報", "https://www.twse.com.tw/zh/statistics/statisticsList?type=07"),
    ("S&P Dow Jones Indices SPIVA Scorecard", "https://www.spglobal.com/spdji/en/research-insights/spiva/"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapters", type=int, default=8)
    ap.add_argument("--fill-narration", action="store_true",
                    help="改為把合成逐字稿填進既有的 work/05_deck.json")
    args = ap.parse_args()

    if args.fill_narration:
        return fill_narration()
    n = min(args.chapters, len(TOPICS))

    ensure_dirs()
    step(f"產生 {n} 章合成測試資料（所有數值皆為假資料）")

    for old in CHAPTERS.glob("ch*.md"):
        old.unlink()

    for i in range(1, n + 1):
        ch_id = f"ch{i:02d}"
        thesis, topic = TOPICS[i - 1]
        p0 = (i - 1) * 24 + 12

        (CHAPTERS / f"{ch_id}_{topic}.md").write_text(
            f'---\nch_id: {ch_id}\ntitle: "第{i}章 {topic}"\n'
            f"pages: [{p0}, {p0 + 23}]\nword_count: 8421\n---\n\n"
            f"（合成測試章節內容，用於驗證 pipeline，非真實書籍內容。）\n",
            encoding="utf-8")

        write_json(DIGEST / f"{ch_id}.json", {
            "ch_id": ch_id,
            "title": f"第{i}章 {topic}",
            "one_line": f"這章用實證資料說明{topic}為什麼被普遍誤解",
            "thesis": thesis + "，作者用三十年的跨市場資料支持這個主張，但取樣期間全落在利率長期下行的環境。",
            "key_points": [
                {"point": f"{topic}的常見誤解",
                 "elaboration": "多數投資人把這件事理解成一個技術問題，實際上它是一個結構問題。"
                                "作者指出，決策架構沒有改變的情況下，換工具只會把同樣的錯誤換個地方犯，"
                                "這也解釋了為什麼過去二十年的產品創新，並沒有改善散戶的實際報酬表現。",
                 "book_evidence": "作者引用 Dalbar 1994–2023 年的投資人行為研究，"
                                  "顯示股票型基金投資人年化報酬比基金本身低 3.1 個百分點",
                 "page_ref": f"p.{p0 + 3}–{p0 + 7}"},
                {"point": "制度面的放大效果",
                 "elaboration": "這個誤解之所以持續存在，是因為銷售端的誘因與投資人的長期利益不一致。"
                                "書中比較了美國 401(k) 與一般經紀帳戶的資產周轉率，前者僅為後者的四分之一，"
                                "差異幾乎完全來自制度設計而非投資人素質，這是全書最有說服力的一段論證。",
                 "book_evidence": "1998 年 LTCM 倒閉案，模型在尾端風險失效時的槓桿放大效果",
                 "page_ref": f"p.{p0 + 9}"},
                {"point": "可操作的判準",
                 "elaboration": "作者給了一組可以直接套用的檢查問題，重點不在答案而在於強迫把隱含假設寫下來。"
                                "他建議每季檢視一次，並且把當時的理由留存，半年後回頭對照，"
                                "這個做法在書中第三部分附有完整的表單範例，以及兩個實際帳戶的長期追蹤紀錄。",
                 "book_evidence": f"書中附錄 A 提供的 12 項檢查表，第 {i} 項對應本章主題",
                 "page_ref": f"p.{p0 + 15}"},
            ],
            "quotes": [{"text": f"「{thesis}。」", "page_ref": f"p.{p0 + 5}"}],
            "data_points": [
                {"claim": f"{topic}相關的長期平均值", "value": f"{3 + i}.{i}%",
                 "as_of": "2019", "page_ref": f"p.{p0 + 11}"}],
            "counterpoint": "取樣期間 1990–2020 全落在利率長期下行段，結論在升息環境是否成立，書中沒有處理。",
            "open_questions": [
                f"台灣 2020–2025 年的{topic}相關指標是多少？是否如書中所說高於美國？",
                f"金管會近三年對{topic}的相關規範有哪些調整？",
            ],
        })

        st, url = REAL_URLS[(i - 1) % len(REAL_URLS)]
        st2, url2 = REAL_URLS[i % len(REAL_URLS)]
        write_json(EVIDENCE / f"{ch_id}.json", {
            "ch_id": ch_id,
            "verified": [{
                "book_claim": f"{topic}的長期平均值為 {3 + i}.{i}%",
                "status": "outdated",
                "current_fact": f"最新值為 {4 + i}.{i}%，較書中數字高 1.0 個百分點（測試資料）",
                "as_of": "2025-12",
                "source_title": f"{st}（測試資料）",
                "source_url": url,
            }],
            "taiwan_lens": [{
                "angle": f"台灣的{topic}與美國差在制度",
                "insight": f"台灣在{topic}上的表現與書中描述的美國情境有明顯落差，"
                           "主因是稅制與銷售通路結構不同，導致同一套原則在執行面會走樣（測試資料）。",
                "supporting_data": f"台灣相關比率約 {10 + i}.{i}%，美國同期約 {20 + i}.{i}%（測試資料）",
                "source_title": f"{st2}（測試資料）",
                "source_url": url2,
            }],
            "extensions": [{
                "title": f"{topic}在退休金制度上的延伸",
                "content": "書中沒有處理確定提撥制下的行為差異，這在台灣勞退新制上特別明顯（測試資料）。",
                "source_title": f"{st}（測試資料）", "source_url": url,
            }],
            "chart_candidates": ([{
                "title": f"{topic}：台美五年對照",
                "chart_type": "bar",
                "unit": "%",
                "data": [{"label": f"20{20 + k}", "value": round(8 + i * 0.7 + k * 1.3, 1)}
                         for k in range(5)],
                "source_title": f"{st}（測試資料）", "source_url": url,
            }] if i % 2 == 1 else []),
        })

    ok(f"{n} 章 → work/02_chapters/, work/03_digest/, work/04_evidence/")
    print()
    print("  下一步：python scripts/05_outline.py --force")
    print("  用完清乾淨：make clean-work")
    return 0


# ---------------------------------------------------------------------------
def fill_narration() -> int:
    """把合成逐字稿寫進 work/05_deck.json 的 narration 欄位，
    字數依各頁 duration_sec 反推（220 字/分），用來驗證 Stage 7–8。"""
    import json
    from _common import DECK_JSON, ok, step, read_json, write_json

    if not DECK_JSON.exists():
        print("找不到 work/05_deck.json，請先跑 05_outline.py")
        return 1
    deck = read_json(DECK_JSON)
    step("填入合成逐字稿（測試用，非真實內容）")

    SENT = [
        "這邊先接著上一頁講。",
        "我自己的經驗是，這件事在實務上比書裡寫的更難執行。",
        "書上給的數字是二〇一九年的，我去查了最新的版本，差了大概一個百分點。",
        "講白一點，關鍵不在工具，而在你有沒有把當時的理由寫下來。",
        "這一點等一下那張圖會講得更清楚。",
        "[停頓]",
        "台灣的情況又不太一樣，主要是通路結構跟稅制的差異。",
        "所以下一頁我想談的是，這個原則要怎麼改寫才適用。",
    ]
    for s in deck["slides"]:
        dur = int(s.get("duration_sec", 60))
        target = dur * 220 / 60
        text, i = "", 0
        while True:
            cand = (text + SENT[i % len(SENT)])
            from _common import narration_chars
            if narration_chars(cand) > target * 1.05 and text:
                break
            text = cand
            i += 1
            if i > 200:
                break
        s["narration"] = text
    write_json(DECK_JSON, deck)
    ok(f"{len(deck['slides'])} 頁逐字稿已填入 {DECK_JSON}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
