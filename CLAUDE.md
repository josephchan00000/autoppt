# 給 Claude 的操作指引

這個 repo 是「把一本書變成復華風格讀書分享簡報」的 pipeline。
**使用者通常只會說「跑下一步」或「繼續」，你要自己判斷現在在哪一階段。**

## 最重要的三件事

1. **每個階段做完就停下來回報，等使用者確認再往下。** 不要一口氣跑到底。
2. **一次只處理一章。** 深讀與研究階段不要把所有章節塞進 context。
3. **不准編造資料來源。** 查不到就不要寫，這是唯一會讓使用者在會議上出事的錯誤。

## 「跑下一步」要怎麼判斷

按順序檢查，第一個不成立的就是現在該做的：

```bash
python scripts/08_qa.py --check-env     # 環境有沒有問題
ls input/                                # 有沒有書檔
ls work/01_raw/pages.jsonl               # Stage 1 解析過沒
ls work/02_chapters/                     # Stage 2 拆章過沒
python scripts/03_digest.py --status     # Stage 3 進度
python scripts/04_research.py --status   # Stage 4 進度
ls work/05_deck.json                     # Stage 5 藍圖
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

跑完 2 章先停下來，讓使用者看品質對不對，再繼續跑其餘章節。

### Stage 4 外部研究 ← 這是你的工作，要用 WebSearch
```bash
python scripts/04_research.py --next
```
用 WebSearch 查證，寫入 `work/04_evidence/chNN.json`，然後 `--validate chNN`。

**硬性規則**：每一筆都要有真實的 `source_url`（WebSearch 實際回傳的網址，
不可以自己拼湊）。查不到就少寫一筆。每章至少 1 筆 `taiwan_lens`。
書中過期的數據一定要標 `outdated` 並附最新值。

順便每章找 1–2 支相關影片放進 `video_candidates`（作者訪談、講座、新聞片段），
使用者會自己挑要不要放進簡報。

全部跑完：
```bash
python scripts/08_qa.py --check-sources    # URL 全檢
python scripts/04_research.py --videos     # 列出所有影片建議給使用者挑
```

### Stage 5 藍圖 + 文案潤飾 ← 潤飾是你的工作
```bash
python scripts/05_outline.py
```
產出 `work/05_deck.json`。接著依 `prompts/outline.md` 潤飾文案，
**先讀 `meta.tone_directive_slide`**，那是這次選定的語氣。
把所有【待填】補掉。

**視覺頁另外讀 `prompts/visuals.md`**，那裡有「什麼時候該放什麼圖」的判斷順序。
一句話版本：**書中原圖 > 外部機構原圖 > 流程圖／時間軸／對照表／雙欄 >
引言頁與大數字頁 > 自己畫的圖表**。自己用 matplotlib 畫折線圖是最後手段，
因為聽眾看不出那條線是哪來的。

**每一頁條列之前先問「這頁非得條列不可嗎」。** 實跑一本 21 章的書，84 頁裡
有 45 頁是條列頁，每頁都沒超字數上限，但整份看下來很悶。規則：
每頁最多 3 條、連續最多 2 頁條列、全書視覺頁至少四成——
`08_qa.py` 的「節奏」檢查會抓。

**視覺頁的版面歸屬**：`image` / `table` / `split` 走**內頁2-1**（主標副標用
母片原生 placeholder，字數上限與內容頁相同 14 / 21）；`flow` / `timeline` /
`quote` / `stat` / 自畫 `chart` 走**空白內頁**（上限 20 / 30）。

開場先跑：

```bash
python tools/extract_book_figures.py --input input/book.pdf --out work/08_bookfigs
```

抽完自己開圖看過，能用書裡原圖的章節就不要自己畫。

改完：
```bash
python scripts/08_qa.py --check-deck
```
**停下來**：這是最省時的修改點，讓使用者直接讀 deck.json 改字。

### Stage 6–7 產出 + 逐字稿 ← 逐字稿是你的工作
先依 `prompts/narration.md` 把逐字稿寫進 deck.json 每一頁的 `narration`
（**先讀 `meta.tone_directive_narration`**），然後：
```bash
python scripts/06_build_pptx.py
python scripts/07_build_script.py
```

### Stage 8 品管
```bash
python scripts/08_qa.py --all
```
任何一項 FAIL 就不准交付。WARN 不擋，但要看過。

**頁數這一項是代理指標**：逐字稿寫完且總時長落在目標區間時，頁數超標只會是
WARN（視覺頁多的簡報本來就頁數多、每頁短）；逐字稿沒寫完時才是 FAIL。修完 `work/05_deck.json` 之後跑 `make revise`
（只重跑 6–8，不要重跑前面的階段）。

## 改稿迴圈

使用者說某一頁不滿意 → 改 `work/05_deck.json` → `make revise`。
**不要重跑 Stage 1–4**，那是白花時間。

## 設定

`config/project.yaml`：書名講者、`deck.minutes`（長度）、`deck.tone`（語氣）、
`deck.layout_family`（內頁色系 1 紅 / 2 米白 / 3 灰）、`videos[]`（現場播放的影片）。

改設定用 `ruamel.yaml` round-trip 或手改，**不要用 yaml.safe_dump 覆寫**，
會把檔案裡的註解全部洗掉。

## 網頁控制台

`make web` 開的頁面涵蓋整條流程，但**只有在使用者自己的電腦上跑才有意義**——
如果你在遠端容器裡（Cowork、Claude Code on the web），他的瀏覽器連不到那個 port，
不要叫他開網頁，直接用對話驅動就好。

## 不要做的事

- 不要一次把所有章節塞進 context
- 不要為了讓 QA 過而放寬 `config/project.yaml` 的門檻
- 不要編造 URL 或數據
- 不要動不動就用 matplotlib 畫圖（先讀 prompts/visuals.md 的優先序）
- 不要一頁接一頁的條列（每頁 ≤3 條、連續 ≤2 頁、視覺頁 ≥40%）
- 不要用 `yaml.safe_dump` 覆寫 project.yaml（會洗掉註解）
- 不要重跑已經完成的階段
