# 給 Claude 的操作指引

這個 repo 是「把一本書變成復華風格讀書分享簡報」的 pipeline。
**使用者通常只會說「跑下一步」或「繼續」，你要自己判斷現在在哪一階段。**

## 最重要的四件事

1. **每個階段做完就停下來回報，等使用者確認再往下。** 不要一口氣跑到底。
2. **一次只處理一章。** 深讀與研究階段不要把所有章節塞進 context。
3. **不准編造資料來源。** 查不到就不要寫，這是唯一會讓使用者在會議上出事的錯誤。
4. **簡報是一個論證，不是一份讀書報告。** 先寫一句主張，再挑撐得住它的證據；
   沒撐住主張的章節進附錄，不是硬排進主線。**品質優先於時間**：時間在 QA 只是 WARN，
   不要為了塞進 60 分鐘而刪內容——移到附錄。

## 「跑下一步」要怎麼判斷

按順序檢查，第一個不成立的就是現在該做的：

```bash
python scripts/08_qa.py --check-env     # 環境有沒有問題
ls input/                                # 有沒有書檔
ls work/01_raw/pages.jsonl               # Stage 1 解析過沒
ls work/02_chapters/                     # Stage 2 拆章過沒
python scripts/03_digest.py --status     # Stage 3 進度
python scripts/04_research.py --status   # Stage 4 進度
ls work/08_bookfigs/                     # 書中原圖抽過沒
ls work/05a_thesis.json                  # Stage 5a 論證設計
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

### Stage 5a 論證設計 ← 這是你的工作，全書只跑一次
```bash
python scripts/05_outline.py --thesis-prompt
```
印出全書的**濃縮索引**（每章十幾行：主張、論點、數據、引句、反方、外部資料，每筆有編號）
加上 `prompts/thesis.md` 的規則。這是唯一一次把全書放在一起看，用的是索引不是全文。

讀完寫 `work/05a_thesis.json`：
一句主張 → 3–5 幕（每幕：主張句、論證鏈、2–8 筆證據引用、對長期投資的意涵）→ 反方 → 結語 → 附錄章。

- **幕的順序按論證走，不按目錄走。** 聽眾最想知道的放前面；歷史是證據，不是開場。
- **每一幕的 claim 是結論句**，會直接印在頁籤上。✗「利息的由來」 ✓「利息比鑄幣古老，是價格不是罪」
- **證據只能引用索引裡的編號**，validator 會逐筆核對，這是不編造的第一道關卡。
- 意涵寫給**長期投資者**（配置、折現率、風險預算、持有期間），不寫給特定公司。
- 沒被用到的章放 `appendix_ch_ids`，素材進附錄備用頁，不會丟掉。

```bash
python scripts/05_outline.py --validate-thesis
```
**停下來**：把 `book_claim` 和每一幕的 `claim` 貼給使用者看，連著唸一遍要像一段話。
方向對了再往下——這是整條流程最便宜的改動點，藍圖生成之後再改結構就貴了。

### Stage 5b 藍圖 + 文案潤飾 ← 潤飾是你的工作
```bash
python scripts/05_outline.py
```
從 thesis.json 長出 `work/05_deck.json`：
序幕（封面／執行摘要／全書地圖）→ 每幕（主張頁籤／主張頁／證據頁／意涵頁）→ 反方 → 結語 → 附錄。
每一頁都帶 `role`（在論證裡的角色）、`act`（哪一幕）、`style`（文字頁樣式）。

接著依 `prompts/outline.md` 潤飾文案，**先讀 `meta.tone_directive_slide`**。
把所有【待填】補掉——QA 對殘留的【待填】判 FAIL。

**文字頁只准三種樣式**（`style` 欄位）：`chain` 論證鏈（因為→所以→因此）、
`labeled` 標籤＋說明（機制／證據／今天）、`prose` 敘事段（有情節的案例）。
裸條列——三個彼此無關的平行事實——QA 判 FAIL。三種要混用，七成以上同一種會 WARN。

**視覺頁另外讀 `prompts/visuals.md`**，那裡有「什麼時候該放什麼圖」的判斷順序。
一句話版本：**書中原圖 > 外部機構原圖 > 流程圖／時間軸／對照表／雙欄 >
引言頁與大數字頁 > 自己畫的圖表**。自己用 matplotlib 畫折線圖是最後手段，
因為聽眾看不出那條線是哪來的。

**每一頁動筆之前先問「這頁非得文字不可嗎」。** 每頁最多 3 條、連續最多 2 頁文字、
全書視覺頁至少四成——`08_qa.py` 的「節奏」檢查會抓。

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
（**先讀 `meta.tone_directive_narration`**；附錄頁不用寫），然後：
```bash
python scripts/06_build_pptx.py
python scripts/07_build_script.py
```

### Stage 8 品管
```bash
python scripts/08_qa.py --all
```
任何一項 FAIL 就不准交付。WARN 不擋，但要看過。

會 FAIL 的：敘事結構（執行摘要在前、每幕有頁籤／主張／證據、頁籤是主張句、有反方、無【待填】）、
條列樣式（裸條列、標籤太長）、溢排、資料來源、版型純度、字型、逐字稿空白、對岸用語。
**只會 WARN 的**：頁數、總時長、每頁字數、節奏秒數、視覺頁比例。時間是指引，
超時的正確做法是把次要證據頁移到附錄（`role` 改 `appendix`、`duration_sec` 改 0、
搬到結語之後），不是刪內容。修完 `work/05_deck.json` 之後跑 `make revise`
（只重跑 6–8，不要重跑前面的階段）。

## 改稿迴圈

使用者說某一頁不滿意 → 改 `work/05_deck.json` → `make revise`。
**不要重跑 Stage 1–4**，那是白花時間。
結構不滿意（幕的順序、主張句）→ 改 `work/05a_thesis.json` → `python scripts/05_outline.py --force`
→ 重新潤飾。注意 `--force` 會蓋掉潤飾過的文案，先確認使用者要的是結構性的改動。

## 設定

`config/project.yaml`：書名講者、`deck.minutes`（長度）、`deck.tone`（語氣）、
`deck.layout_family`（內頁色系 1 紅 / 2 米白 / 3 灰）、`videos[]`（現場播放的影片）、
`limits`（文案門檻）、`pacing`（節奏指引，只 WARN）。

改設定用 `ruamel.yaml` round-trip 或手改，**不要用 yaml.safe_dump 覆寫**，
會把檔案裡的註解全部洗掉。

## 不要做的事

- 不要一次把所有章節塞進 context（Stage 5a 的索引是濃縮過的，那是例外）
- 不要照章節順序排簡報——先寫主張，再挑證據
- 不要把頁籤寫成主題名（「資產泡沫與退休金」），要寫成主張句
- 不要裸條列（三個平行事實）；文字頁三選一：chain / labeled / prose
- 不要為了時間刪內容——移到附錄
- 不要為了讓 QA 過而放寬 `config/project.yaml` 的門檻
- 不要編造 URL 或數據
- 不要動不動就用 matplotlib 畫圖（先讀 prompts/visuals.md 的優先序）
- 不要一頁接一頁的文字頁（每頁 ≤3 條、連續 ≤2 頁、視覺頁 ≥40%）
- 不要用 `yaml.safe_dump` 覆寫 project.yaml（會洗掉註解）
- 不要重跑已經完成的階段
