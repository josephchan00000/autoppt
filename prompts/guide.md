# Stage 5a — 導讀設計（全書只跑一次）

你已經逐章讀完這本書（`work/03_digest/`）、查證過外部資料（`work/04_evidence/`）、
查過作者（`work/04_author.json`）。現在要設計一場**導讀**：照作者的章序走，
章名當節名；每一章給聽眾「作者在這章說了什麼」的大綱與重點，配一張示意圖或書中原圖，
再補一筆今天的數字。故事進逐字稿，投影片只放大綱、重點與圖。

下面是全書的濃縮索引：每章的主張、論點、作者用語、故事、數據、引句、反方、外部資料，
每一筆都有編號。**guide.json 只能引用這裡出現的編號**，`--validate-guide` 會逐筆核對；
沒有編號的東西一律不准寫進去。

書名：{book_title}（{author}）　共 {n_chapters} 章　　中譯本：{edition_zh}

{digest_summary}

## 可用的圖檔（要先自己開圖看過，確認是圖表不是書衣或裝飾線，才可以引用）

{figures}

---

## 你要交的東西：`work/05a_guide.json`

```json
{
  "book_claim": "全書一句話主張，用作者的話（≤40 字）",
  "book_claim_short": "同一句的短版，當執行摘要與封面副標（≤14 字）",
  "why_now": "為什麼現在讀這本書（≤21 字）",
  "implication_short": "全書對長期投資的一句結論（≤14 字，意涵頁主標）",
  "implications": [
    {"label": "配置", "text": "對長期投資的意義，一條一個面向（≤40 字）"}
  ],
  "main_ch_ids": ["ch01", "ch05", "ch06"],
  "chapters": {
    "ch06": {
      "headline": "這章的一句話結論，用作者的話（≤14 字）",
      "outline": ["這章的論證第一步（≤40 字）", "第二步", "第三步"],
      "points": [{"kp": 1}, {"kp": 3}],
      "visuals": [
        {"kp": 0, "visual": "table", "use": "這張圖要說什麼"},
        {"story": 0, "visual": "timeline", "use": "故事的時間軸"},
        {"figure": "work/08_bookfigs/p061.png", "use": "書中原圖"}
      ],
      "today": {"verified": 0, "visual": "table", "use": "書中值已過期，帶最新值"},
      "story": 0
    }
  },
  "counter": {
    "claim": "反方主張句（≤14 字）",
    "points": [{"label": "因果", "ch_id": "ch13", "text": "具體弱點（≤40 字）"}]
  },
  "closing": "一句收束（≤14 字）"
}
```

`visuals[]` 與 `today` 的引用鍵：`kp` `quote` `data` `figure` `taiwan` `verified` `chart`
`extension` `story`，每筆恰好一個，`use` 必填。`visual` 可填：`image` `table` `split`
`flow` `timeline` `stat` `quote` `chart` `labeled` `chain` `prose`。

---

## 設計規則

### 1. 章序照書，章名照官方

- 主線章依原書順序排。60 分鐘大約 8–14 章進主線，其餘章自動進附錄備用頁——
  沒被選的章素材不會丟。挑主線章的標準：撐住 `book_claim`、有故事、有圖。
- 章名一律用官方中譯（`work/04_author.json` 的 `book.chapters`）；沒有官方譯名就用
  原文，**不要自己翻**。這不是你決定的，程式會自動帶。

### 2. 每一章：大綱 → 示意圖 → 重點 → 今天

- `headline`：這章的一句話結論，**用作者的話**——`key_terms`、章名、引句都是素材。
  ✗「利率與投機的關係」 ✓「約翰牛忍不了 2%」
- `outline` 2–4 步：作者在這章怎麼推論，每步接上一步，用他的用語。
- `visuals` 1–3 張：**書中原圖 > 機構原圖 > 示意圖（flow／timeline／split／table）**。
  故事也能畫成時間軸或流程圖（`story` 引用＋`visual: timeline|flow`），
  這時投影片上是骨架、細節在逐字稿。
- `points` 0–3 條：大綱裝不下但值得上投影片的重點，一條一個 `kp`。
- `today`：這章有 `verified[outdated]` 或 `taiwan` 就放一筆，讓聽眾知道書寫完之後發生了什麼。
- `story`：**每一章一定選一則**，它不會變成投影片，會變成這一章逐字稿的開場。

### 3. 原書用字

投影片上的字要是作者的字。每一章的投影片至少要出現該章一個 `key_term`
（`08_qa.py` 的「原書用字」檢查會抓）。同義改寫是禁止項：能引原文就引原文，
中譯附英文原詞。

### 4. 全書意涵與反方

- `implications` 2–4 條：對長期投資者的意義（配置、折現率假設、風險預算、持有期間），
  不寫給特定公司。
- `counter.points` 2–4 條：具體弱點（取樣偏誤、因果倒置、反例、時空已變），
  優先用各章 `counterpoint` 與 Stage 4 的 `contested`／`outdated`。作者的立場
  （`04_author.json` 的 `stance`）也是合法的反方素材。

### 5. 字數（validator 會擋）

| 欄位 | 上限 |
|---|---|
| `book_claim` `implications[].text` `outline[]` `counter.points[].text` | 40 字 |
| `why_now` | 21 字 |
| `book_claim_short` `implication_short` `headline` `counter.claim` `closing` | 14 字 |
| `implications[].label` `counter.points[].label` | 5 字 |

## 語言

繁體中文，專有名詞與作者用語保留英文原文。不使用對岸用語。

## 輸出

寫入 `work/05a_guide.json`，然後：

```bash
python scripts/05_outline.py --validate-guide
python scripts/05_outline.py                  # 通過後才生成藍圖 work/05_deck.json
```
