# autoppt — 復華風格「專業書分享」簡報自動化

把一本書變成一場讀書分享：符合復華母片版型、**論證式結構**、每頁都有出處的 PPTX，
外加一份 Word 逐字稿。

**核心原則：內容產出與版面產出完全分離。**
所有「想內容」的階段只輸出 JSON；所有「排版」的階段只讀 JSON、不生內容。
任何一頁不滿意，只要改 `work/05_deck.json` 重跑 build，30 秒重出整份 PPT。

**第二個原則：簡報是一個論證，不是一份讀書報告。**
先寫一句主張，再挑撐得住它的證據；沒撐住主張的章節進附錄。品質優先於時間，
時間在 QA 只是 WARN。

---

## 怎麼用：把 repo 交給 Claude，說「跑下一步」

這條 pipeline 是對話驅動的。任何一個 Claude session（Claude Code、Cowork）拿到這個資料夾
加上一本書的電子檔，照 `CLAUDE.md` 就能自己判斷現在在哪一階段、下一步該做什麼、
什麼時候該停下來問你。

```bash
make setup                 # 建 venv、裝套件、檢查環境
cp 你的書.pdf input/        # 支援 PDF（文字層／掃描）、EPUB
vi config/project.yaml     # 填書名、講者、日期、長度、語氣、色系
```

然後開 Claude，說「跑下一步」。每個階段結束它會停下來回報：
拆章結果、前兩章的深讀品質、論證設計（主張句）、藍圖文案、最後的 QA 報告。

要交給別人：把整個資料夾打包（`git archive` 或直接 zip，`work/` `output/` `input/`
本來就不入庫），對方放進書檔、開 Claude、說「跑下一步」。

純手動的 CLI 流程：

```bash
make extract                                 # Stage 1  解析書檔
make split                                   # Stage 2  拆章 → 停，人工確認章節表
python scripts/03_digest.py --next           # Stage 3  逐章深讀（Claude 驅動）
python scripts/04_research.py --next         # Stage 4  外部研究（Claude + WebSearch）
make check-sources                           #          URL 全檢
python tools/extract_book_figures.py --input input/book.pdf --out work/08_bookfigs
make thesis                                  # Stage 5a 論證設計提示詞 → Claude 寫 work/05a_thesis.json
python scripts/05_outline.py --validate-thesis
make outline                                 # Stage 5b 藍圖 → 停，潤飾文案
make build                                   # Stage 6+7 產 PPTX + 逐字稿
make qa                                      # Stage 8  品管
```

改稿迴圈：**改 `work/05_deck.json` → `make revise`**（只重跑 Stage 6–8）。
結構要改：改 `work/05a_thesis.json` → `python scripts/05_outline.py --force` → 重新潤飾。

---

## 簡報長什麼樣：金字塔

```
序幕   封面 → 執行摘要（主張／證據／意義）→ 全書地圖（N 個主張句）
每幕   主張頁籤（主張句）→ 主張頁（論證鏈）→ 證據頁 ×2–8 → 意涵頁（對長期投資）
反方   本書站不住的地方（取樣、因果、反例、時空）
結語   一句收束 + Q&A
附錄   沒進主線的章、沒用到的過期數據——不計時、不需逐字稿，被問到再翻
```

- **幕的順序按論證走，不按目錄走。** 聽眾最想知道的放前面，歷史是證據不是開場。
- **頁籤是主張句**，不是主題名。✗「資產泡沫與退休金」 ✓「泡沫是折現率歸零的算術」
- **文字頁只准三種樣式**（`style`）：`chain` 論證鏈（①因為→②所以→③因此）、
  `labeled` 標籤＋說明（機制／證據／今天）、`prose` 敘事段（有情節的案例）。
  裸條列 QA 判 FAIL，三種要混用。
- **視覺優先序**：書中原圖 > 外部機構原圖 > 流程圖／時間軸／對照表／雙欄 >
  引言頁與大數字頁 > 自己畫的圖表。全書視覺頁至少四成。
- 三種樣式全部畫在母片原生的內文 placeholder 裡（run 層級的紅色標籤與序號），
  不加自建 shape，版型純度不受影響。

---

## 設定（`config/project.yaml`）

| 設定 | 效果 |
|---|---|
| `deck.minutes` | 預計長度。講述時間目標依這個推算（總長減 5 分鐘 Q&A）。**只用來配速與 WARN，不裁頁** |
| `deck.layout_family` | 內頁色系。母片三組內頁的頁首色帶不同：**1 復華紅／2 米白／3 灰**。選到的當主力版型 |
| `deck.tone` | 文案語氣：`professional` 專業嚴謹／`casual` 輕鬆口語／`storytelling` 說故事。內容寫在 `tone_presets`，會帶進 `deck.json` 的 `meta.tone_directive_*` |
| `videos[]` | 分享會現場要播的影片。每支生成一張影片頁（標題 + QR code + 起訖時間碼），播放秒數計入總時長且不參與縮放。`after_ch` 指定掛在用到那一章的那一幕之後 |
| `limits` | 文案門檻：字數上限、三種樣式的規則、節奏防線 |
| `pacing` | 節奏指引（頁籤秒數、單頁停留、序幕佔比）：只 WARN |

改設定用 `ruamel.yaml` round-trip 或手改，不要用 `yaml.safe_dump` 覆寫（會洗掉註解）。

---

## Pipeline

| Stage | 腳本 | 輸入 | 輸出 | 誰執行 |
|---|---|---|---|---|
| 1 | `01_extract.py` | `input/book.*` | `work/01_raw/pages.jsonl`, `toc.json` | 程式 |
| 2 | `02_split_chapters.py` | pages.jsonl | `work/02_chapters/chNN_*.md` | 程式 → **停** |
| 3 | `03_digest.py` | 章節 md | `work/03_digest/chNN.json` | **Claude** |
| 4 | `04_research.py` | digest | `work/04_evidence/chNN.json` | **Claude + WebSearch** |
| 5a | `05_outline.py --thesis-prompt` | 全書濃縮索引 | `work/05a_thesis.json` | **Claude** → **停** |
| 5b | `05_outline.py` | thesis + digest + evidence | `work/05_deck.json` | 程式 → **Claude 潤飾** → **停** |
| 6 | `06_build_pptx.py` | deck.json + 母片 | `output/*.pptx` | 程式 |
| 7 | `07_build_script.py` | deck.json | `output/*_逐字稿.docx` | 程式 |
| 8 | `08_qa.py` | 全部 | `output/qa_report.md` | 程式 |

Stage 3 / 4 / 5a 是「發題 → 模型作答 → 收題驗證」三段式，腳本本身不產內容：

```bash
python scripts/03_digest.py --next            # 印出下一章的提示詞（含章節全文）
#   …模型讀題、產 JSON、寫入 work/03_digest/ch01.json…
python scripts/03_digest.py --validate ch01   # schema + 品質底線驗證，FAIL 就重寫
python scripts/05_outline.py --thesis-prompt  # 全書只跑一次：濃縮索引 + 論證規則
python scripts/05_outline.py --validate-thesis  # 每筆證據引用的編號都要對得上索引
```

Stage 5a 的 validator 只接受索引裡出現的編號——這是「不編造」的第一道關卡，
`08_qa.py --check-sources` 的 HTTP 全檢是第二道。

---

## 目錄結構

```
├── assets/FH_template.pptx      # 母片（4:3, 10×7.5in，11 個版面）
├── config/
│   ├── fh_template_spec.json    # 版面參數：不要讓 AI 重新猜，直接讀它
│   └── project.yaml             # 書名／講者／長度／語氣／文案門檻／節奏指引／黑名單
├── prompts/                     # digest / research / thesis / outline / visuals / narration
├── scripts/                     # 8 支 stage 腳本 + _common.py
├── tools/
│   ├── extract_book_figures.py  # 抽書中原圖
│   ├── fetch_source_figure.py   # 批次抓機構原圖（要對外連線，本機跑）
│   ├── repace_deck.py           # 改完 minutes 之後重新配速，不動文案
│   └── make_fixtures.py         # 合成測試資料，沒有真書也能驗證 pipeline
├── input/                       # 原始書檔（.gitignore，版權不入庫）
├── work/                        # 中間檔；05a_thesis.json 與 05_deck.json 是兩個修改點
└── output/                      # PPTX / DOCX / qa_report.md / preview
```

---

## 三個最容易翻車的地方

這三項都已在程式內處理並有 QA 對應檢查：

1. **母片內建 11 張示範頁沒清乾淨** → `delete_all_slides()` 必在 `add_slide` 之前，
   且要 `drop_rel`。QA「版型純度」會檢查。
2. **中文字型只設了 latin** → 在別台電腦開會變新細明體。
   所有 run 都過 `set_ea_font()` 寫入 `<a:ea>` 與 `<a:cs>`。QA「字型」逐 run 檢查。
   `<a:ea>` 與 `<a:buNone>` 在 schema 裡都有固定位置，必須用 `insert_element_before()` 插入；
   直接 `append()` 會產生不合法 XML，PowerPoint 開檔會跳「需要修復」。
3. **研究階段編造來源** → 這是唯一會讓你在會議上出事的錯誤。
   `prompts/research.md` 的「查不到就不要寫」是硬性規則，
   `04_research.py --validate` 擋掉空 URL 與拼湊網址，`05_outline.py --validate-thesis`
   擋掉索引裡沒有的引用，`08_qa.py --check-sources` 做 HTTP 全檢。三道都要留著。

> 雲端環境（Cowork、Claude Code on the web）的對外連線是白名單，機構網站幾乎全被擋。
> 這不是 bug 也不能繞。所以抓機構原圖與 URL 全檢兩件事拆成「雲端記網址、本機批次跑」。

---

## QA 判準（`make qa`）

FAIL 擋交付；WARN 不擋但要看過。

| 檢查 | 判準 | 不過時 |
|---|---|---|
| 敘事結構 | 執行摘要在前 3 頁；每幕有頁籤（主張句）／主張頁／證據頁；有反方頁；結語收尾；無殘留【待填】 | FAIL |
| 條列樣式 | 文字頁必為 chain / labeled / prose；標籤 ≤5 字；鏈 2–4 步；敘事 ≤2 段 | FAIL |
| 溢排 | 內文估算 ≤8 行；主標 ≤14 字（空白內頁視覺頁 ≤20）；副標 ≤21；總字數 ≤160 | FAIL |
| 資料來源 | 每頁（封面／頁籤／結尾除外）都有非空 sources | FAIL |
| 外部連結 | 所有 url HTTP 200；本機連不出去時 SKIP | FAIL |
| 具體性 | 每頁 body 至少含一個數字／年份／專有名詞 | WARN |
| 版型純度 | layout 必須在模板 11 種之內；無自建 textbox（視覺元件除外） | FAIL |
| 字型 | 所有 run 的 `a:ea` typeface = 微軟正黑體 | FAIL |
| 逐字稿 | 每頁都有 narration（附錄除外）；字數 ±25% 與總時長只 WARN | FAIL／WARN |
| 節奏 | 連續文字頁 ≤2（FAIL）；視覺頁 ≥40%（WARN）；頁籤／單頁秒數、序幕佔比（WARN） | 混合 |
| 對岸用語 | 黑名單掃描（`config/project.yaml` 的 `banned_terms`） | FAIL |
| 頁數 | 參考區間 | WARN |
| 視覺 | LibreOffice 轉 PNG 全頁截圖 → `output/preview/` | SKIP |

---

## 環境需求

必要：Python 3.10+、`requirements.txt` 內的套件（`make setup` 一次裝好）。

選用（缺了不擋 pipeline，對應檢查會標 SKIP 並印出安裝指令）：

| 工具 | 用途 | 安裝 |
|---|---|---|
| `tesseract` + `chi_tra` | 掃描版 PDF 的 OCR | `apt install tesseract-ocr tesseract-ocr-chi-tra` |
| `libreoffice-impress` | QA 預覽截圖 | `apt install libreoffice-impress` |
| `pdftoppm` | PDF 轉 PNG（沒有會改用 pymupdf） | `apt install poppler-utils` |
| 微軟正黑體／Noto CJK | 圖表中文字型 | `apt install fonts-noto-cjk` |

隨時可用 `make check` 確認目前環境狀態。`soffice` 指令存在不代表能轉檔——只裝
`libreoffice-core` 而沒裝 Impress 濾鏡時仍會失敗，`make check` 會實際做一次最小轉檔來確認。

---

## 沒有書也能驗證 pipeline

```bash
python tools/make_fixtures.py --chapters 8      # 產 8 章合成 digest + evidence + thesis.json
python scripts/05_outline.py --force
python tools/make_fixtures.py --fill-narration  # 把【待填】與逐字稿填成假文案
python scripts/06_build_pptx.py && python scripts/07_build_script.py
python scripts/08_qa.py --all
make clean-work                                  # 用完清乾淨
```

合成資料的數值全是假的、`source_title` 都標了「測試資料」，不要拿去用。

---

## 設計理由

| 痛點 | 根因 | 解法 |
|---|---|---|
| 內容空泛、抓不到書的重點 | 一次丟整本書，模型只能做淺層摘要 | 章節拆檔 + 每章獨立深讀，一次只處理一章，輸出結構化 JSON |
| 版型跑掉、不像復華的東西 | 每次重新生成樣式，靠模型記憶 | 版型參數固定成 spec 檔，程式只填 placeholder，不自創樣式 |
| 內容深度不夠、沒有出處 | 只有書內資訊，沒有外部佐證 | 每章強制產生研究問題 → 網路查證 → evidence.json（含 URL 與檢索日期），沒有來源的論點不准上投影片 |
| 看不懂架構、像讀書報告 | 簡報照章節順序排，主張在最後一頁 | Stage 5a 論證設計層：先寫主張、再挑證據，幕的順序按論證走；沒撐住主張的章進附錄 |
| 一頁接一頁的條列 | 條列是最省力的寫法 | 文字頁三選一（論證鏈／標籤＋說明／敘事段），裸條列 FAIL；視覺頁 ≥40% |
| 為了塞進時間刪掉好內容 | 頁數是硬門檻 | 頁數與時間只 WARN；多的移到附錄備用頁，不刪 |

完整施工規格見 `docs/建置規劃書.pdf`。
