# Stage 4 — 作者解析（全書只跑一次，要用 WebSearch）

聽眾沒見過作者。簡報序幕會做 2–3 頁「作者是誰」：背景與立場、生涯與著作的時間軸、
這本書怎麼被評價與被批評。**每一句都要能對到這裡的一筆、每一筆都要有真實的 `source_url`。**
另外要順便查**中譯本**：書名、出版社、譯者、年份，以及**目錄裡的官方章名**——
簡報上的章名一律用官方譯名，找不到就用原文。

書名：{book_title_en}（{book_title_zh}）　作者：{author}

拆章時抓到的原文章名（用來對照中譯本目錄）：
{chapter_list}

## 查什麼、去哪查

| 要什麼 | 優先來源 |
|---|---|
| 教育、經歷（公司與年份）、現職 | 作者官網 About、出版社作者頁、Wikipedia（當索引，數字要對回原始出處） |
| 著作清單（年份、出版社、得獎） | 出版社頁、作者官網 |
| 學派／立場（他常引用誰、被歸為哪一派、他自己怎麼說） | 作者訪談、書評、他的專欄 |
| 為什麼寫這本書 | 作者訪談、書的前言／導讀、出版社介紹 |
| 評價（獎項、入圍、代表性書評） | 獎項官網、FT／WSJ／Economist 等書評 |
| 主要批評（誰、批評什麼） | 書評、學界回應 |
| 中譯本與官方章名 | 出版社頁、博客來、讀墨、HyRead、誠品的「目錄」段 |

## 輸出 JSON（不要 markdown 圍欄）

```json
{
  "author": {
    "name": "Edward Chancellor",
    "name_zh": "中譯本用的譯名（沒有就空字串）",
    "born": "1962-12（查得到才填，否則空字串）",
    "background": [
      {"text": "教育或經歷，一句（≤60 字）", "source_title": "", "source_url": "", "as_of": "2024-01"}
    ],
    "career": [
      {"when": "2008–2014", "what": "做什麼、在哪裡（≤40 字）", "source_url": ""}
    ],
    "works": [
      {"year": 1999, "title_en": "Devil Take the Hindmost", "title_zh": "", "note": "得獎或定位（≤40 字）", "source_url": ""}
    ],
    "stance": [
      {"text": "學派或立場，一句（≤60 字）", "source_title": "", "source_url": ""}
    ],
    "why_this_book": {"text": "作者自己說的動機（≤120 字）", "source_title": "", "source_url": ""},
    "reception": [
      {"text": "獎項／入圍／書評一句（≤60 字）", "source_title": "", "source_url": "", "as_of": "2023-06"}
    ],
    "critics": [
      {"text": "誰批評什麼（≤60 字）", "source_title": "", "source_url": ""}
    ]
  },
  "book": {
    "title_en": "The Price of Time: The Real Story of Interest",
    "year_en": 2022,
    "publisher_en": "",
    "edition_zh": {"title_zh": "", "subtitle_zh": "", "publisher": "", "year": "", "translator": "", "isbn": "", "source_url": ""},
    "chapters": [
      {"n": "1", "title_en": "Babylonian Birth", "title_zh": "官方中譯章名，逐字照抄"}
    ]
  }
}
```

數量：`background` 3–6、`career` 3–8、`works` ≥1、`stance` 1–3、`reception` 1–4、`critics` 0–3。
`edition_zh` 查不到就給 `null`；有中譯本就一定要把目錄抄進 `chapters`（沒抄到就不准說有中譯本）。

## 硬性規則

1. **每一筆都要有 `source_url`，而且是 WebSearch 實際回傳的網址**，不可以拼湊。
   查不到就少寫一筆，欄位給空陣列。
2. 引用作者的話（立場、動機）要標出處，不要把書評的說法寫成作者自己說的。
3. 章名**逐字照抄**中譯本目錄，不要「順一下」；抄不到的章 `title_zh` 給空字串。
4. `as_of` 是資料的時點（YYYY-MM），不是檢索日期。
5. 評價與批評要成對：只有掌聲沒有批評的作者頁不可信。

## 語言

繁體中文；人名、書名、機構名首次出現寫「中文（English）」，沒有通用中譯就用原文。
不使用對岸用語。

## 輸出

寫入 `work/04_author.json`，然後跑 `python scripts/04_research.py --validate-author`。
