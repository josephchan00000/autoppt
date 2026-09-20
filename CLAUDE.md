# 給 Claude 的操作指引

這個 repo 是「把一本書變成復華風格讀書分享簡報」的 pipeline。
**使用者通常只會說「跑下一步」或「繼續」，你要自己判斷現在在哪一階段。**

## 最重要的四件事

1. **每個階段做完就停下來回報，等使用者確認再往下。** 不要一口氣跑到底。
2. **一次只處理一章。** 深讀與研究階段不要把所有章節塞進 context。
3. **不准編造資料來源。** 查不到就不要寫，這是唯一會讓使用者在會議上出事的錯誤。
4. **簡報是一場導讀，聽眾要聽到的是作者，不是你。** 照作者的章序走、章名當節名
   （官方中譯，找不到就用原文，**不要自己翻**）、投影片用作者的字、故事進逐字稿、
   作者先上台。**品質優先於時間**：時間在 QA 只是 WARN，塞不進 60 分鐘的章進附錄，不刪。

## 「跑下一步」要怎麼判斷

按順序檢查，第一個不成立的就是現在該做的：

```bash
python scripts/08_qa.py --check-env     # 環境有沒有問題
ls input/                                # 有沒有書檔
ls work/01_raw/pages.jsonl               # Stage 1 解析過沒
ls work/02_chapters/                     # Stage 2 拆章過沒
python scripts/03_digest.py --status     # Stage 3 進度（◐ = 缺章名／原書用語／故事的補充）
python scripts/04_research.py --status   # Stage 4 進度（含作者解析）
ls work/08_bookfigs/                     # 書中原圖抽過沒
ls work/04_author.json                   # 作者解析 + 中譯本章名
ls work/05a_guide.json                   # Stage 5a 導讀設計
ls work/05_deck.json                     # Stage 5b 藍圖
ls output/*.pptx                         # Stage 6-7 產出
ls output/qa_report.md                   # Stage 8 品管
```

## 各階段怎麼做

### Stage 0 環境
```bash
make setup          # 第一次跑
make check          # 只檢查
```
缺 tesseract / libreoffice-impress / pdftoppm 不擋流程，對應檢查會標 SKIP。

### Stage 1–2 解析與拆章
```bash
python scripts/01_extract.py --input input/<書檔>
python scripts/02_split_chapters.py
```
**停下來**：把章節清單表格貼給使用者看。字數異常（紅字）代表拆錯了，
問他要不要換策略：`--force-regex` 或 `--force-split N`，或直接手改
`work/02_chapters/*.md`。他確認後才往下。

掃描版 PDF 會自動走 OCR，記得提醒他看 `work/01_raw/ocr_confidence.md`。

### Stage 3 逐章深讀 ← 這是你的工作
```bash
python scripts/03_digest.py --next          # 印出下一章的提示詞（含章節全文）
```
讀完提示詞，產 JSON，寫入 `work/03_digest/chNN.json`，然後：
```bash
python scripts/03_digest.py --validate chNN
```
**不通過就重寫**，錯誤訊息會告訴你哪一項不符。品質底線很嚴格，
特別是 `elaboration` 不能是 `thesis` 的改寫、`book_evidence` 不能寫空話、
`counterpoint` 不准敷衍。

每章除了論點，還要抓三樣東西：**作者的原章名**（`chapter_title_en/zh`）、
**作者自己的用語**（`key_terms`，5–10 個，他造的詞、他的比喻，不是教科書名詞；
`zh` 翻不好就留空，很爛的翻譯比原文更糟）、**書裡的故事**（`stories`，1–3 則，
有人物、時間、轉折，只用作者給的細節）。故事之後進逐字稿，用語會上投影片。

舊版 digest 缺這三樣時，`--next` 會自動改印**補充提示詞**（只補那四個欄位、其餘不動），
也可以 `--supplement chNN` 指定。

跑完 2 章先停下來，讓使用者看品質對不對，再繼續跑其餘章節。

### Stage 4 外部研究 ← 這是你的工作，要用 WebSearch
```bash
python scripts/04_research.py --next
```
用 WebSearch 查證，寫入 `work/04_evidence/chNN.json`，然後 `--validate chNN`。

**硬性規則**：每一筆都要有真實的 `source_url`（WebSearch 實際回傳的網址，
不可以自己拼湊）。查不到就少寫一筆。每章至少 1 筆 `taiwan_lens`。
書中過期的數據一定要標 `outdated` 並附最新值。

順便每章找兩種東西：
- `figure_candidates`：機構自己畫的那張圖的**圖檔網址**（不是頁面網址）。
  只記不抓——雲端環境的對外連線是白名單，機構網站幾乎全被擋。
- `video_candidates`：1–2 支相關影片（作者訪談、講座、新聞片段），使用者自己挑。

**作者解析，全書一次**（可以在逐章研究之前先做，章名補充會用到）：
```bash
python scripts/04_research.py --author            # 印提示詞
python scripts/04_research.py --validate-author   # 寫完 work/04_author.json 後驗
```
查作者的背景、生涯、著作、立場、寫這本書的動機、獎項書評、主要批評，每筆帶來源；
**順便查中譯本**：書名、出版社、譯者、年份，以及**目錄裡的官方章名**逐字抄進
`book.chapters`。簡報章名只用官方譯名或原文。雲端抓不到書店網頁時，用 WebSearch 的
摘要撈目錄，一章一章比對；抄不到的章 `title_zh` 留空，程式會自動用原文。

全部跑完：
```bash
python scripts/08_qa.py --check-sources             # URL 全檢
python scripts/04_research.py --videos              # 列出影片建議給使用者挑
python tools/fetch_source_figure.py --from-evidence # 批次抓機構原圖
python tools/extract_book_figures.py --input input/book.pdf --out work/08_bookfigs  # 抽書中原圖
```

`fetch_source_figure.py` 需要對外連線。在雲端跑會整批失敗（egress policy 擋掉機構網站），
**這不是錯誤**——叫使用者把資料夾帶回自己的電腦跑同一行就會補齊，已經抓到的不會重抓。

抽出來的書中原圖**自己開圖看過**（是圖表，不是書衣或裝飾線），下一步要引用。

### Stage 5a 導讀設計 ← 這是你的工作，全書只跑一次
```bash
python scripts/05_outline.py --guide-prompt
```
印出全書的**濃縮索引**（每章十幾行：主張、論點、作者用語、故事、數據、引句、反方、
外部資料，每筆有編號）加上 `prompts/guide.md` 的規則。這是唯一一次把全書放在一起看，
用的是索引不是全文。

讀完寫 `work/05a_guide.json`：全書一句主張 → 挑主線章（**照原書章序**，60 分鐘約 8–14 章，
其餘自動進附錄）→ 每一章的 headline（用作者的話）、大綱 2–4 步、示意圖 1–3 張、
今天的數字、**一則故事**（進逐字稿）→ 全書對長期投資的意義 → 反方 → 結語。

- **章序照書、章名照官方**，程式自動帶，你不用也不准改。
- **headline 與大綱用作者的用語**（`key_terms`、章名、引句），同義改寫是禁止項。
- **示意圖是骨架**：書中原圖 > 機構原圖 > flow／timeline／split／table；故事也能畫成時間軸。
- 引用只能用索引裡的編號，validator 逐筆核對。

```bash
python scripts/05_outline.py --validate-guide
```
**停下來**：把主線章清單（章名＋headline）和 `book_claim` 貼給使用者看。
方向對了再往下——這是整條流程最便宜的改動點。

### Stage 5b 藍圖 + 文案潤飾 ← 潤飾是你的工作
```bash
python scripts/05_outline.py
```
從 guide.json 長出 `work/05_deck.json`：
序幕（封面／作者頁 2–3 頁／執行摘要／章序地圖）→ 每章（分部頁籤／章名頁籤／大綱頁／
示意圖／重點／今天的數字）→ 全書意涵 → 反方 → 結語 → 附錄。
每一頁都帶 `role`（在導讀裡的角色）、`section`（哪一章）、`style`（文字頁樣式）；
大綱頁還帶 `story_hint`（這章選的故事，寫逐字稿用）。

接著依 `prompts/outline.md` 潤飾文案，**先讀 `meta.tone_directive_slide`**。
把所有【待填】補掉——QA 對殘留的【待填】判 FAIL。

**文字頁只准三種樣式**（`style` 欄位）：`chain` 論證鏈、`labeled` 標籤＋說明、
`prose` 敘事段。裸條列 QA 判 FAIL。**投影片上的字要是作者的字**：每一章至少出現
一個 `key_term`，QA「原書用字」會抓。

**視覺頁另外讀 `prompts/visuals.md`**。一句話版本：**書中原圖 > 外部機構原圖 >
流程圖／時間軸／對照表／雙欄 > 引言頁與大數字頁 > 自己畫的圖表**。

**視覺頁的版面歸屬**：`image` / `table` / `split` 走**內頁2-1**（主標副標用
母片原生 placeholder，字數上限與內容頁相同 14 / 21）；`flow` / `timeline` /
`quote` / `stat` / 自畫 `chart` 走**空白內頁**（上限 20 / 30）。

改完：
```bash
python scripts/08_qa.py --check-deck
```
**停下來**：這是最省時的修改點，讓使用者直接讀 deck.json 改字。

### Stage 6–7 產出 + 逐字稿 ← 逐字稿是你的工作
先依 `prompts/narration.md` 把逐字稿寫進 deck.json 每一頁的 `narration`
（**先讀 `meta.tone_directive_narration`**；附錄頁不用寫）。
**每一章的逐字稿用那章的故事開場**（大綱頁的 `story_hint`），場景 → 轉折 → 作者的結論；
QA「故事」會檢查逐字稿有沒有講到故事的人物。然後：
```bash
python scripts/06_build_pptx.py
python scripts/07_build_script.py
```

### Stage 8 品管
```bash
python scripts/08_qa.py --all
```
任何一項 FAIL 就不准交付。WARN 不擋，但要看過。

會 FAIL 的：敘事結構（作者頁、執行摘要、每一主線章有章名頁籤／大綱／示意圖或今天、
章名是官方譯名或原文、全書意涵、反方、無【待填】）、條列樣式、溢排、資料來源、
版型純度、字型、逐字稿空白、對岸用語。
**只會 WARN 的**：原書用字、故事、頁數、總時長、每頁字數、節奏秒數、視覺頁比例。
時間是指引，超時的正確做法是把次要的章移出主線（改 guide.json 重生成）或把證據頁
移到附錄，不是刪內容。修完 `work/05_deck.json` 之後跑 `make revise`。

## 改稿迴圈

使用者說某一頁不滿意 → 改 `work/05_deck.json` → `make revise`。
**不要重跑 Stage 1–4**，那是白花時間。
結構不滿意（主線章、headline、示意圖選擇）→ 改 `work/05a_guide.json` →
`python scripts/05_outline.py --force` → 重新潤飾。注意 `--force` 會蓋掉潤飾過的文案，
先確認使用者要的是結構性的改動。

## 設定

`config/project.yaml`：書名講者、`deck.minutes`（長度）、`deck.tone`（語氣）、
`deck.layout_family`（內頁色系 1 紅 / 2 米白 / 3 灰）、`videos[]`（現場播放的影片）、
`limits`（文案門檻）、`pacing`（節奏指引，只 WARN）。
書名 `book.title_zh` 用官方中譯本的書名（查到中譯本之後改過來）。

改設定用 `ruamel.yaml` round-trip 或手改，**不要用 yaml.safe_dump 覆寫**，
會把檔案裡的註解全部洗掉。

## 不要做的事

- 不要一次把所有章節塞進 context（Stage 5a 的索引是濃縮過的，那是例外）
- 不要重排章序、不要自己翻章名：官方中譯或原文
- 不要用同義改寫取代作者的用語；能引原文就引原文
- 不要把故事寫成投影片：故事進逐字稿，投影片放大綱、重點、示意圖
- 不要裸條列（三個平行事實）；文字頁三選一：chain / labeled / prose
- 不要為了時間刪內容——次要的章進附錄
- 不要為了讓 QA 過而放寬 `config/project.yaml` 的門檻
- 不要編造 URL 或數據；作者頁每一句都要有來源
- 不要動不動就用 matplotlib 畫圖（先讀 prompts/visuals.md 的優先序）
- 不要一頁接一頁的文字頁（每頁 ≤3 條、連續 ≤2 頁、視覺頁 ≥40%）
- 不要用 `yaml.safe_dump` 覆寫 project.yaml（會洗掉註解）
- 不要重跑已經完成的階段
