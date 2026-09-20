# 給 Claude 的操作指引

這個 repo 是「把一本書變成復華風格讀書分享簡報」的 pipeline。
**使用者通常只會說「跑下一步」或「繼續」，你要自己判斷現在在哪一階段。**

## 不知道現在該做什麼，先跑這個

```bash
make next          # 印出：現在在哪一步、這一步做什麼、做完要給使用者看什麼
make progress      # 印完整進度表
```

`scripts/00_next.py` 會逐項檢查檔案與進度，第一個沒過的就是現在該做的。
判斷順序寫在那支 script 的 `stages()`，要加階段就在那裡加一列。

## 最重要的五件事

1. **每個階段做完就停下來回報，等使用者確認再往下。** 不要一口氣跑到底。
   每支 script 跑完會印「✋ 停：⟨要確認什麼⟩／給他看：⟨什麼⟩」，看到就停。
2. **一次只處理一章。** 深讀與研究階段不要把所有章節塞進 context。
3. **不准編造資料來源。** 查不到就不要寫，這是唯一會讓使用者在會議上出事的錯誤。
4. **簡報是一場導讀，聽眾要聽到的是作者，不是你。** 照作者的章序走、章名當節名
   （官方中譯，找不到就用原文，**不要自己翻**）、投影片用作者的字、故事進逐字稿、
   作者先上台。
5. **文案要像人講的話，不要像 AI 寫的。** 一頁最多一條冒號句、最多一個英文原詞、
   三條不要長得一樣、每條都要有動作詞。`08_qa.py` 的「AI 味」檢查會抓。

**品質優先於時間**：時間在 QA 只是 WARN，塞不進 60 分鐘的章進附錄，不刪。

## 各階段怎麼做

每一階段都有**完成條件**（`make next` 會檢查）與**停下來要給使用者看什麼**。

### Stage 0 環境
```bash
make setup          # 第一次跑
make check          # 只檢查
```
缺 tesseract / pdftoppm 不擋流程，對應檢查會標 SKIP。
**缺 libreoffice-impress 就轉不出 PDF**，本機請裝：`sudo apt install libreoffice-impress`。

### Stage 1–2 解析與拆章
```bash
python scripts/01_extract.py --input input/<書檔>
python scripts/02_split_chapters.py
```
- **完成條件**：`work/01_raw/pages.jsonl`、`work/02_chapters/ch*.md`
- **停下來給他看**：章節清單表格。字數異常（紅字）代表拆錯了，
  問他要不要換策略（`--force-regex` / `--force-split N`）或直接手改 md。
- 掃描版 PDF 會自動走 OCR，記得提醒他看 `work/01_raw/ocr_confidence.md`。

### Stage 4a 作者解析 ← 先做，章名補充要用
```bash
python scripts/04_research.py --author            # 印提示詞
python scripts/04_research.py --validate-author   # 寫完 work/04_author.json 後驗
```
查作者的背景、生涯、著作、立場、寫這本書的動機、獎項書評、主要批評，每筆帶來源；
**順便查中譯本**：書名、出版社、譯者、年份，以及**目錄裡的官方章名**逐字抄進
`book.chapters`。簡報章名只用官方譯名或原文。雲端抓不到書店網頁時，用 WebSearch 的
摘要撈目錄，一章一章比對；抄不到的章 `title_zh` 留空，程式會自動用原文。

- **完成條件**：`work/04_author.json` 通過 `--validate-author`
- **停下來給他看**：作者背景／生涯／評價各一句，以及查到的官方中譯章名清單

### Stage 3 逐章深讀 ← 這是你的工作
```bash
python scripts/03_digest.py --next          # 印出下一章的提示詞（含章節全文）
python scripts/03_digest.py --validate chNN
```
**不通過就重寫**，錯誤訊息會告訴你哪一項不符。品質底線很嚴格，
特別是 `elaboration` 不能是 `thesis` 的改寫、`book_evidence` 不能寫空話、
`counterpoint` 不准敷衍。

每章除了論點，還要抓三樣東西：**作者的原章名**（`chapter_title_en/zh`）、
**作者自己的用語**（`key_terms`，5–10 個，他造的詞、他的比喻，不是教科書名詞；
`zh` 翻不好就留空，很爛的翻譯比原文更糟）、**書裡的故事**（`stories`，1–3 則，
有人物、時間、轉折，只用作者給的細節）。故事之後進逐字稿，用語會上投影片，
故事的人物與地點還會變成圖片搜尋關鍵字。

舊版 digest 缺這三樣時，`--next` 會自動改印**補充提示詞**，也可以 `--supplement chNN`。

- **完成條件**：每章都有 `key_terms` `stories` `chapter_title_en` 且驗證通過
- **停下來給他看**：**先跑兩章就停**，把 `key_terms` 與 `stories` 貼給他看品質對不對

### Stage 4b 外部研究 ← 這是你的工作，要用 WebSearch
```bash
python scripts/04_research.py --next
python scripts/04_research.py --validate chNN
```
**硬性規則**：每一筆都要有真實的 `source_url`（WebSearch 實際回傳的網址，
不可以自己拼湊）。查不到就少寫一筆。每章至少 1 筆 `taiwan_lens`。
書中過期的數據一定要標 `outdated` 並附最新值。

順便每章找兩種東西：`figure_candidates`（機構原圖的**圖檔網址**，只記不抓）、
`video_candidates`（1–2 支相關影片，使用者自己挑）。

全部跑完：
```bash
python scripts/08_qa.py --check-sources             # URL 全檢
python scripts/04_research.py --videos              # 列出影片建議給使用者挑
python tools/fetch_source_figure.py --from-evidence # 批次抓機構原圖
python tools/extract_book_figures.py --input input/<書檔> --out work/08_bookfigs
```

`fetch_source_figure.py` 需要對外連線。在雲端跑會整批失敗（egress policy 擋掉機構網站），
**這不是錯誤**——叫使用者把資料夾帶回自己的電腦跑同一行就會補齊。

抽出來的書中原圖**自己開圖看過**（是圖表，不是書衣或裝飾線），下一步要引用。

- **完成條件**：每章一份 evidence、URL 全檢過、`work/08_bookfigs/` 有圖
- **停下來給他看**：每章的 `taiwan_lens` 與 `outdated` 數據

### Stage 5a 導讀設計 ← 這是你的工作，全書只跑一次
```bash
python scripts/05_outline.py --guide-prompt
python scripts/05_outline.py --validate-guide
```
印出全書的**濃縮索引**（每章十幾行，每筆有編號）加上 `prompts/guide.md` 的規則。
這是唯一一次把全書放在一起看，用的是索引不是全文。

讀完寫 `work/05a_guide.json`：全書一句主張 → 挑主線章（**照原書章序**，60 分鐘約
8–14 章，其餘自動進附錄）→ 每一章的 headline（用作者的話）、大綱 2–4 步、
示意圖 1–3 張、今天的數字、**一則故事**（進逐字稿與圖片關鍵字）→ 全書對長期投資的
意義 → 反方 → 結語。

- 章序照書、章名照官方，程式自動帶，你不用也不准改。
- headline 與大綱用作者的用語，同義改寫是禁止項。
- 引用只能用索引裡的編號，validator 逐筆核對。

- **完成條件**：`--validate-guide` 通過
- **停下來給他看**：主線章清單（章名＋headline）與 `book_claim`，
  連著唸一遍要像一段話。**方向對了再往下——這是整條流程最便宜的改動點。**

### Stage 5b 藍圖 + 文案潤飾 ← 潤飾是你的工作
```bash
python scripts/05_outline.py
```
從 guide.json 長出 `work/05_deck.json`：
序幕（封面／作者頁 2–3 頁／執行摘要／章序地圖）→ 每章（分部頁籤／章名頁籤／大綱頁／
示意圖／重點／今天的數字）→ 全書意涵 → 反方 → **結語 → 祝賀頁（業績長紅）→ 附錄**。

接著依 `prompts/outline.md` 潤飾文案，**先讀 `meta.tone_directive_slide`**。
把所有【待填】補掉——QA 對殘留的【待填】判 FAIL。

```bash
python scripts/08_qa.py --check-deck
```

- **完成條件**：`--check-deck` 沒有 FAIL、殘留【待填】0 處
- **停下來給他看**：幾頁有代表性的文案（卡片頁、表格頁、雙欄頁各一）

### Stage 6–7 產出 + 逐字稿 ← 逐字稿是你的工作
先依 `prompts/narration.md` 把逐字稿寫進 deck.json 每一頁的 `narration`
（**先讀 `meta.tone_directive_narration`**；附錄頁不用寫）。
**每一章的逐字稿用那章的故事開場**（大綱頁的 `story_hint`），場景 → 轉折 → 作者的結論；
QA「故事」會檢查逐字稿有沒有講到故事的人物。然後：
```bash
python scripts/06_build_pptx.py      # 自動順便轉 PDF
python scripts/07_build_script.py
```

- **完成條件**：`output/` 有 pptx、pdf、逐字稿 docx
- **停下來給他看**：PDF（PPT 換台電腦容易跑版，要他看 PDF）

### Stage 8 圖片建議 + 品管
```bash
python tools/image_suggestions.py    # → output/圖片建議.md
python scripts/08_qa.py --all
```
**要補真照片**（選配，章名頁籤預設已經有場景卡，不補也交得出去）：
```bash
python tools/fetch_story_photos.py   # 抓候選圖到 work/09_photos/_candidates/<id>/，附授權.md
# 挑一張 → 複製成 work/09_photos/<頁面 id>.jpg → make revise
```
**這支要能對外連線**。雲端 session 會直接失敗（`Tunnel connection failed: 403`），
那不是錯誤，是 egress 白名單；叫使用者在自己的電腦跑同一行。
授權一定要他自己看過，不要替他判斷可不可以用。
或一次做完：`make deliver`（build + images + qa）。

任何一項 FAIL 就不准交付。WARN 不擋，但要唸給使用者聽。

- **完成條件**：`output/qa_report.md` 沒有 FAIL
- **停下來給他看**：FAIL 清單（應為空）＋ WARN 摘要 ＋ 圖片建議清單

## 版面規則（`06_build_pptx.py` 自動處理，你不用手動排版）

- **文字頁是卡片**：`labeled` 每條一張卡、標籤做成紅底白字圓角標籤；
  `chain` 每條一張卡、左側紅色圓形序號、卡與卡之間用細線串起；
  `prose` 是左側紅色粗線＋大字段落。卡片高度自動分配、整疊置中，
  所以 2 條與 4 條的頁面都是滿的。**一頁最多 4 張卡（prose 2 段），超過自動拆頁。**
- **卡片字級自己算**：由「一頁幾張卡」與「最長那條幾個字」決定，落在 18–26pt。
  一頁 4 條而且每條都逼近 40 字就會縮到 18pt，QA 會 WARN；那是叫你砍字到 34 字以內，
  不是叫你放寬門檻。容量模型在 `scripts/_common.py`「卡片式內文的容量模型」，
  版面引擎與 QA 共用同一份，改常數兩邊一起變。
- **表格自動撐滿**：列高分配可用高度、整張表垂直置中、字級隨列高放大。
- **雙欄自動撐滿**：標題列高與字級依標題長度算（不會爆框），內容依條目算高度、
  兩欄取高者、整體垂直置中。
- **中英之間不要打空格**：`tidy_deck()` 會自動刪掉。PowerPoint 本來就會補視覺間距，
  再打一個就變兩倍寬的縫。
- **章名頁籤右側會畫一張「場景卡」**：大字年份＋人物＋地點，取自該章故事的
  `image_hint`（由 `05_outline.py` 自動產生）。這不是佔位符，是成品——直接上台也不空。
  故事本身不上投影片（故事進逐字稿），卡片只把時空標出來。
  **使用者把照片放成 `work/09_photos/<頁面 id>.jpg` 就會自動換成照片**，
  裁切填滿同一個框。`make photos` 會去 Wikimedia Commons 抓候選圖附授權（要能上網）。
- **視覺頁的版面歸屬**：`image` / `table` / `split` 走**內頁2-1**（上限 14 / 21 字）；
  `flow` / `timeline` / `quote` / `stat` / 自畫 `chart` 走**空白內頁**（上限 20 / 30）。

視覺選擇的優先序見 `prompts/visuals.md`：
**書中原圖 > 外部機構原圖 > 流程圖／時間軸／對照表／雙欄 > 引言頁與大數字頁 > 自己畫的圖表**。

## 文案規則

**文字頁只准三種樣式**（`style` 欄位）：`chain` 論證鏈、`labeled` 標籤＋說明、
`prose` 敘事段。裸條列 QA 判 FAIL。

**投影片上的字要是作者的字**：每一章至少出現一個 `key_term`，QA「原書用字」會抓。

**去 AI 味**（使用者退過一次，`prompts/outline.md` 有完整規則與正反例）：
- 一頁最多一條冒號句式，其餘改寫成有主詞有動作的句子
- 一頁最多一個英文原詞（只留作者自己造的詞）
- 三條要點不要長度／句式／結尾都一樣
- 每一條都要有動作詞，不要名詞堆疊

## 交付清單

一份完整的交付包含五樣東西，少一樣就不算做完：

| 檔案 | 來源 |
|---|---|
| `output/*.pptx` | `06_build_pptx.py` |
| `output/*.pdf` | 同上，自動轉（PPT 會跑版，PDF 是保證） |
| `output/*_逐字稿.docx` | `07_build_script.py` |
| `output/圖片建議.md` | `tools/image_suggestions.py` |
| `output/qa_report.md` | `08_qa.py --all`，不能有 FAIL |

打包給下一個視窗用：`git archive --format=zip --prefix=autoppt/ -o autoppt.zip HEAD`

## 改稿迴圈

使用者說某一頁不滿意 → 改 `work/05_deck.json` → `make revise`。
**不要重跑 Stage 1–4**，那是白花時間。
結構不滿意（主線章、headline、示意圖選擇）→ 改 `work/05a_guide.json` →
`python scripts/05_outline.py --force` → 重新潤飾。注意 `--force` 會蓋掉潤飾過的文案。

## 設定

`config/project.yaml`：書名講者、`deck.minutes`（長度）、`deck.tone`（語氣，
預設 `professional_warm` 專業但親切）、`deck.layout_family`（內頁色系 1 紅 / 2 米白 / 3 灰）、
`deck.closing_wish`（最後一頁的祝賀詞，預設「業績長紅」，留空就不放）、
`videos[]`、`limits`（文案門檻）、`pacing`（節奏指引，只 WARN）。
書名 `book.title_zh` 用官方中譯本的書名。

改設定用 `ruamel.yaml` round-trip 或手改，**不要用 yaml.safe_dump 覆寫**，會洗掉註解。

## 不要做的事

- 不要一口氣跑完所有階段：每一步做完要停下來給使用者看
- 不要一次把所有章節塞進 context（Stage 5a 的索引是濃縮過的，那是例外）
- 不要重排章序、不要自己翻章名：官方中譯或原文
- 不要用同義改寫取代作者的用語；能引原文就引原文
- 不要把故事寫成投影片：故事進逐字稿，投影片放大綱、重點、示意圖
- 不要裸條列；文字頁三選一：chain / labeled / prose
- 不要寫成「名詞：名詞」，不要一頁塞三個英文詞，不要三條等長排比
- 不要在中英文之間打空格
- 不要為了時間刪內容——次要的章進附錄
- 不要為了讓 QA 過而放寬 `config/project.yaml` 的門檻
- 不要編造 URL 或數據；作者頁每一句都要有來源
- 不要動不動就用 matplotlib 畫圖（先讀 prompts/visuals.md 的優先序）
- 不要只交 PPTX：PDF、逐字稿、圖片建議、QA 報告一起給
- 不要在雲端硬抓圖：Commons 與機構網站都被 egress 白名單擋掉，
  章名頁籤畫場景卡就好，照片讓使用者在自己的電腦用 `make photos` 補
- 不要替使用者判斷圖片授權可不可以用：把授權原文列給他，他自己決定
- 不要用 `yaml.safe_dump` 覆寫 project.yaml（會洗掉註解）
- 不要重跑已經完成的階段
