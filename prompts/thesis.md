# Stage 5a — 論證設計（全書只跑一次）

你已經逐章讀完這本書（`work/03_digest/`）並查證過外部資料（`work/04_evidence/`）。
現在要做的**不是把章節排成簡報**，而是替這本書設計一個論證：
聽眾聽完之後能複述一句主張、記得三到五個撐住它的證據、知道這對自己的長期投資判斷改變了什麼。

下面是全書的濃縮索引：每章的主張、論點、數據、引句、反方，以及外部查到的資料，
每一筆都有編號。**thesis.json 只能引用這裡出現的編號**，`--validate-thesis` 會逐筆核對；
沒有編號的東西一律不准寫進去（這是不編造資料的第一道關卡）。

書名：{book_title}（{author}）　共 {n_chapters} 章

{digest_summary}

## 可用的圖檔（要先自己開圖看過，確認是圖表不是書衣或裝飾線，才可以引用）

{figures}

---

## 你要交的東西：`work/05a_thesis.json`

```json
{
  "book_claim": "全書一句話主張，可被反駁（≤40 字）",
  "book_claim_short": "同一句的短版，當執行摘要與封面的主標（≤14 字）",
  "why_now": "為什麼現在讀這本書，一句（≤21 字，執行摘要副標）",
  "implication": "對長期投資者的一句總結（≤40 字）",
  "acts": [
    {
      "id": "act1",
      "claim": "這一幕的主張句（≤14 字，是結論不是主題）",
      "question": "這一幕回答的問題（≤21 字）",
      "support": ["因為……（≤40 字）", "所以……", "因此……"],
      "evidence": [
        {"ch_id": "ch13", "kp": 0, "use": "撐住第一步：折現率歸零＝估值無限", "visual": "labeled"},
        {"ch_id": "ch13", "figure": "work/08_bookfigs/p223.png", "use": "……", "visual": "image"},
        {"ch_id": "ch14", "taiwan": 1, "use": "……", "visual": "split"},
        {"ch_id": "ch14", "verified": 0, "use": "書中數字已過期，帶最新值", "visual": "table"},
        {"ch_id": "ch13", "data": 2, "use": "……", "visual": "stat"},
        {"ch_id": "ch13", "quote": 0, "use": "……", "visual": "quote"}
      ],
      "implication": "這一幕對長期投資的意義，一句（≤40 字）",
      "ch_ids": ["ch13", "ch14", "ch15"]
    }
  ],
  "counter": {
    "claim": "反方主張句（≤14 字）",
    "points": [
      {"label": "因果", "ch_id": "ch09", "text": "具體弱點（≤40 字）"},
      {"label": "反例", "ch_id": "ch16", "text": "……"}
    ]
  },
  "closing": "一句收束（≤14 字）",
  "appendix_ch_ids": ["ch02", "ch03"]
}
```

`evidence[]` 每筆**只能有一個**引用鍵：`kp`（論點編號）、`quote`（引句編號）、
`data`（數據編號）、`figure`（圖檔路徑）、`taiwan`（台灣對照編號）、
`verified`（外部查證編號，多半用 outdated 那幾筆）、`chart`（外部數列編號）、
`extension`（延伸論點編號）。`use` 必填：這筆證據撐住論證鏈的哪一步。

`visual` 可填：`image` `table` `split` `flow` `timeline` `stat` `quote` `chart`
`labeled` `chain` `prose`。判斷順序見 `prompts/visuals.md`。

---

## 設計規則

### 1. 先寫一句主張，再決定講什麼

- `book_claim` 必須是**可被反駁的句子**，不是書的簡介。
  - ✗「這本書講述利率四千年的歷史」
  - ✓「利率壓到自然利率之下，代價不在物價，在資產價格、生產力與分配」
- **不是每一章都要上台。** 一幕通常動用 2–4 章；沒被用到的章放 `appendix_ch_ids`，
  素材會進附錄備用頁，不會丟掉。硬把 21 章全部塞進主線，就是使用者說「看不懂架構」的原因。

### 2. 幕的順序按論證走，不按目錄走

- **聽眾最想知道的放最前面**：現在正在發生的事、跟自己有關的數字。
  歷史是證據，不是開場——巴比倫泥板可以在第三幕當「這件事四千年沒變過」的證據，
  不要在第一幕花五分鐘講它。
- 典型四幕：**問題是什麼 → 機制為何 → 代價在哪 → 反轉之後怎麼辦**。三到五幕都可以，
  由這本書的論證決定，不要湊數。
- 每一幕的 `claim` 是結論句，會直接印在頁籤上。
  - ✗「利息的由來」「資產泡沫、退休金與貧富差距」
  - ✓「利息比鑄幣古老，是價格不是罪」「泡沫是折現率歸零的算術」
- 幕與幕之間要接得起來：上一幕的結論是下一幕的前提。寫完四個 claim 連著唸一遍，
  唸起來要像一段話。

### 3. 每一幕：主張 → 證據 → 意涵

- `support` 是 2–4 步**論證鏈**：每一步接著上一步（因為→所以→因此），
  不是三個平行的事實。三步最好。
- `evidence` 2–8 筆，五到七筆最常見。挑證據的優先序：**書中原圖 > 機構原圖 > 書中的數據與案例 >
  外部最新數字 > 引句**。書中過期的數據一定要帶 `verified` 的最新值。
  每筆的 `use` 要寫「撐住鏈上哪一步」，寫不出來就代表這筆證據不該進主線。
- 一幕裡的證據要**混合型態**：至少一頁視覺（image / table / split / flow / timeline），
  不要六筆全是 labeled。
- `implication` 寫給**長期投資者**：配置、折現率假設、風險預算、持有期間、再平衡……
  不寫給特定公司，不寫「本公司應如何」。

### 4. 反方不是客氣話

- `counter.points` 2–4 條，每條是具體弱點：取樣偏誤、因果倒置、反例存在、時空已變。
  優先用 Stage 4 查到的 `contested` / `outdated` 證據，那是「資料打斷作者因果鏈」的地方。
- `label` ≤5 字，例如「因果」「取樣」「反例」「時空」。
- 不寫「本書仍有參考價值」這種話。

### 5. 字數（validator 會擋）

| 欄位 | 上限 |
|---|---|
| `book_claim` `implication` `act.implication` `support[]` `counter.points[].text` | 40 字 |
| `why_now` `act.question` | 21 字 |
| `book_claim_short` `act.claim` `counter.claim` `closing` | 14 字 |
| `counter.points[].label` | 5 字 |

半形字算半個字。專有名詞保留英文原文。

## 語言

繁體中文。不使用對岸用語（賦能／抓手／閉環／顆粒度／打法／復盤／落地性／用戶／信息／質量）。

## 輸出

寫入 `work/05a_thesis.json`，然後：

```bash
python scripts/05_outline.py --validate-thesis   # 欄位、字數、每筆編號都要對得上
python scripts/05_outline.py                     # 通過後才生成藍圖 work/05_deck.json
```
