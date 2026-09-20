#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生合成測試資料，讓 Stage 5→8 可以在沒有真書的情況下跑通。

    python tools/make_fixtures.py --chapters 8

會寫入 work/02_chapters/、work/03_digest/、work/04_evidence/、work/05a_thesis.json。
所有數值都是**假的**，source_title 都標了「測試資料」，不要拿去用。
真書上線前記得 make clean-work。

    python tools/make_fixtures.py --fill-narration   # 把藍圖的【待填】與逐字稿填成假文案（驗 6–8 用）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _common import (  # noqa: E402
    CHAPTERS, DIGEST, EVIDENCE, THESIS_JSON, ensure_dirs, is_appendix, ok, step, write_json,
)

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

# 主張句（≤14 字、不是主題名）：合成 thesis.json 的幕與短主張用
SHORT_CLAIMS = [
    "配置決定九成績效", "波動不是風險，虧損才是", "分散要跨因子不跨檔數", "成本是唯一確定的變數",
    "再平衡賣的是情緒", "擇時的勝率門檻太高", "流動性只在不缺錢時存在", "報酬順序決定退休成敗",
    "指數化是紀律外包", "行為缺口吃掉三成報酬",
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

    write_thesis(n)
    ok(f"{n} 章 → work/02_chapters/, work/03_digest/, work/04_evidence/, work/05a_thesis.json")
    print()
    print("  下一步：python scripts/05_outline.py --force")
    print("  用完清乾淨：make clean-work")
    return 0


def write_thesis(n: int) -> None:
    """合成的論證設計：把章節分成 3–4 幕，最後一章進附錄，證據引用只指向真的存在的編號。"""
    ids = [f"ch{i:02d}" for i in range(1, n + 1)]
    main_ids = ids[:-1] if n >= 4 else ids
    appendix = ids[len(main_ids):]
    k = 4 if len(main_ids) >= 8 else 3
    size = -(-len(main_ids) // k)
    groups = [main_ids[i:i + size] for i in range(0, len(main_ids), size)]
    while len(groups) < 3:                     # 章數太少時拆到 3 幕
        big = max(groups, key=len)
        if len(big) < 2:
            break
        groups.remove(big)
        groups += [big[:len(big) // 2], big[len(big) // 2:]]

    acts = []
    for gi, chunk in enumerate(groups):
        first = chunk[0]
        i0 = int(first[2:])
        ev = [
            {"ch_id": first, "kp": 0, "use": "撐住第一步：這是常見誤解", "visual": "labeled"},
            {"ch_id": first, "data": 0, "use": "書中的數字", "visual": "stat"},
            {"ch_id": first, "taiwan": 0, "use": "台灣的對照數字", "visual": "split"},
            {"ch_id": first, "verified": 0, "use": "書中數字已過期，帶最新值", "visual": "table"},
        ]
        second = chunk[1] if len(chunk) > 1 else first
        if int(second[2:]) % 2 == 1:
            ev.append({"ch_id": second, "chart": 0, "use": "五年走勢要看形狀", "visual": "chart"})
        else:
            ev.append({"ch_id": second, "kp": 1, "use": "制度面的放大機制", "visual": "flow"})
        acts.append({
            "id": f"act{gi + 1}",
            "claim": SHORT_CLAIMS[(i0 - 1) % len(SHORT_CLAIMS)],
            "question": f"第 {gi + 1} 幕要回答的問題（測試）",
            "support": ["因為多數人把它當技術問題（測試）", "所以換工具不會改變結果（測試）",
                        "因此要改的是決策架構（測試）"],
            "evidence": ev,
            "implication": "把成本與持有期間寫回配置假設，再談選股（測試資料）",
            "ch_ids": chunk,
        })
    write_json(THESIS_JSON, {
        "book_claim": "長期報酬由配置與成本決定，選股與擇時扣除成本後貢獻歸零（測試）",
        "book_claim_short": "配置與成本決定長期報酬",
        "why_now": "升息之後每個假設都要重算",
        "implication": "把折現率、成本與持有期間寫回配置假設，再談選股",
        "acts": acts,
        "counter": {
            "claim": "資料全落在降息四十年",
            "points": [
                {"label": "取樣", "ch_id": ids[0],
                 "text": "1990–2020 全在利率下行段，升息環境未驗證（測試）"},
                {"label": "因果", "ch_id": ids[min(1, n - 1)],
                 "text": "買回增加與投資下滑同時發生，未排除共同原因（測試）"},
            ],
        },
        "closing": "先算配置，再談選股",
        "appendix_ch_ids": appendix,
    })


# ---------------------------------------------------------------------------
def _fill_todo(obj):
    """把藍圖裡的【待填】換成假文案（帶數字，過得了具體性檢查）。"""
    if isinstance(obj, str):
        return "測試文案 3.1%（假資料）" if "【待填" in obj else obj
    if isinstance(obj, list):
        return [_fill_todo(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill_todo(v) for k, v in obj.items()}
    return obj


def fill_narration() -> int:
    """把藍圖的【待填】換成假文案，再把合成逐字稿寫進 narration 欄位，
    字數依各頁 duration_sec 反推（220 字/分），用來驗證 Stage 6–8。附錄頁不填。"""
    from _common import DECK_JSON, ok, step, read_json, write_json

    if not DECK_JSON.exists():
        print("找不到 work/05_deck.json，請先跑 05_outline.py")
        return 1
    deck = read_json(DECK_JSON)
    step("填入假文案與合成逐字稿（測試用，非真實內容）")
    deck["slides"] = [_fill_todo(s) for s in deck["slides"]]

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
        if is_appendix(s):                     # 附錄不計時、不需逐字稿
            continue
        # 影片頁只要進場與收尾的過場詞（30–120 字），不照 duration 反推
        if s.get("kind") == "video":
            v = s.get("video") or {}
            s["narration"] = (
                f"這段我想直接讓你們看畫面。[停頓] 我們播 {v.get('span', '')} 這一段，"
                "看完我再講為什麼這段對我們特別重要。[看向聽眾]")
            continue
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
