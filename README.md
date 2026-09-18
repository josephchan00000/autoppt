# autoppt — 復華風格「專業書分享」簡報自動化

把一本書變成一場 60 分鐘、45–60 頁、符合復華母片版型、每頁都有出處的讀書分享簡報，
外加一份 Word 逐字稿。

**核心原則：內容產出與版面產出完全分離。**
所有「想內容」的階段只輸出 JSON；所有「排版」的階段只讀 JSON、不生內容。
任何一頁不滿意，只要改 `work/05_deck.json` 重跑 build，30 秒重出整份 PPT。

---

## 快速開始

有兩種用法，設定與 Stage 1–2 可以走網頁，其餘階段一律在終端機。

### A. 網頁（推薦給不想碰 CLI 的人）

```bash
make setup           # 建 venv、裝套件、檢查環境
make web             # → http://127.0.0.1:5000
```

這頁可以設定書名講者、**預計長度**、**文案語氣**、**內頁色系（有預覽圖可挑）**、
**現場要播的影片**，存檔後直接把書檔拖進去，它會跑完 Stage 1–2 並把章節清單
攤開讓你確認（拆錯了可以在頁面上換策略重拆）。設定會寫進 `config/project.yaml`，
註解不會被洗掉。

確認章節沒問題之後回終端機接 Stage 3。

### B. 純 CLI

```bash
make setup                                  # 建 venv、裝套件、檢查環境
cp 你的書.pdf input/book.pdf                 # 支援 PDF（文字層/掃描）、EPUB
vi config/project.yaml                      # 填書名、講者、日期

make extract                                # Stage 1  解析書檔
make split                                  # Stage 2  拆章 → 停，人工確認章節表
python scripts/03_digest.py --next          # Stage 3  逐章深讀（Claude Code 驅動）
python scripts/04_research.py --next        # Stage 4  外部研究（Claude Code + WebSearch）
make check-sources                          #          URL 全檢
make outline                                # Stage 5  產藍圖 → 停，潤飾文案
make build                                  # Stage 6+7 產 PPTX + 逐字稿
make qa                                     # Stage 8  品管
```

改稿迴圈：**改 `work/05_deck.json` → `make revise`**（只重跑 Stage 6–8，不要重跑前面的階段）。

---

## 四個可調的設定（`config/project.yaml`，也可在 `make web` 頁面上改）

| 設定 | 效果 |
|---|---|
| `deck.minutes` | 預計長度。`target_slides` 與講述時間留 `null` 就依這個推算（約 0.85 頁/分鐘，總長減 5 分鐘 Q&A）。頁數超出預算時 `05_outline.py` 會自動裁掉可選頁面，不會丟一份 60 頁的稿要你自己刪 |
| `deck.layout_family` | 內頁色系。母片三組內頁的頁首色帶不同：**1 復華紅／2 米白／3 灰**。選到的當主力版型，另外兩組仍用在台灣對照與全書綜合，維持視覺變化 |
| `deck.tone` | 文案語氣：`professional` 專業嚴謹／`casual` 輕鬆口語／`storytelling` 說故事。內容寫在 `tone_presets`，會帶進 `deck.json` 的 `meta.tone_directive_*`，潤飾與逐字稿階段照著寫。要自訂語氣直接改那段文字 |
| `videos[]` | 分享會現場要播的影片。每支生成一張影片頁（標題 + QR code + 起訖時間碼），播放秒數計入總時長且不參與縮放，逐字稿只寫進場與收尾的過場詞（QA 對影片頁另有標準）。`after_ch` 指定插在哪一章之後 |

---

## Pipeline

| Stage | 腳本 | 輸入 | 輸出 | 誰執行 |
|---|---|---|---|---|
| 1 | `01_extract.py` | `input/book.*` | `work/01_raw/pages.jsonl`, `toc.json` | 程式 |
| 2 | `02_split_chapters.py` | pages.jsonl | `work/02_chapters/chNN_*.md` | 程式 → **停** |
| 3 | `03_digest.py` | 章節 md | `work/03_digest/chNN.json` | **Claude Code** |
| 4 | `04_research.py` | digest | `work/04_evidence/chNN.json` | **Claude Code + WebSearch** |
| 5 | `05_outline.py` | digest + evidence | `work/05_deck.json` | 程式 → **停** |
| 6 | `06_build_pptx.py` | deck.json + 母片 | `output/*.pptx` | 程式 |
| 7 | `07_build_script.py` | deck.json | `output/*_逐字稿.docx` | 程式 |
| 8 | `08_qa.py` | 全部 | `output/qa_report.md` | 程式 |

Stage 3 / 4 是「發題 → 模型作答 → 收題驗證」三段式，腳本本身不產內容：

```bash
python scripts/03_digest.py --next            # 印出下一章的提示詞（含章節全文）
#   …模型讀題、產 JSON、寫入 work/03_digest/ch01.json…
python scripts/03_digest.py --validate ch01   # schema + 品質底線驗證，FAIL 就重寫
python scripts/03_digest.py --status          # 看整體進度
```

---

## 目錄結構

```
├── assets/FH_template.pptx      # 母片（4:3, 10×7.5in，11 個版面）
├── config/
│   ├── fh_template_spec.json    # 版面參數：不要讓 AI 重新猜，直接讀它
│   └── project.yaml             # 書名／講者／頁數預算／文案門檻／對岸用語黑名單
├── input/                       # 原始書檔（.gitignore，版權不入庫）
├── work/                        # 中間檔，05_deck.json 是最重要的修改點
├── prompts/                     # digest / research / outline / narration
├── scripts/                     # 8 支 stage 腳本 + _common.py
├── web/                         # 上傳頁（Flask，只管設定與 Stage 1–2）
├── tools/make_fixtures.py       # 合成測試資料，沒有真書也能驗證 pipeline
└── output/                      # PPTX / DOCX / qa_report.md / preview
```

上傳頁只綁 `127.0.0.1`。要讓別台電腦連才加 `--host 0.0.0.0`，
但它沒有身分驗證、書檔有版權，請先確認網段安全。

---

## 三個最容易翻車的地方

這三項都已在程式內處理並有 QA 對應檢查：

1. **母片內建 11 張示範頁沒清乾淨** → `delete_all_slides()` 必在 `add_slide` 之前，
   且要 `drop_rel`。QA「版型純度」會檢查。
2. **中文字型只設了 latin** → 在別台電腦開會變新細明體。
   所有 run 都過 `set_ea_font()` 寫入 `<a:ea>` 與 `<a:cs>`。QA「字型」逐 run 檢查。
   注意 `<a:ea>` 在 schema 裡有固定位置，必須用 `insert_element_before()` 插入；
   直接 `append()` 在有 `hlinkClick`／`extLst` 的 run 上會產生不合法 XML，
   PowerPoint 開檔會跳「需要修復」。
3. **研究階段編造來源** → 這是唯一會讓你在會議上出事的錯誤。
   `prompts/research.md` 的「查不到就不要寫」是硬性規則，
   `04_research.py --validate` 會擋掉空 URL 與只有網域沒路徑的拼湊網址，
   `08_qa.py --check-sources` 的 HTTP 全檢是第二道關卡。兩道都要留著。

> 母片版面 9（空白內頁）的裝飾群組，實際上在**示範投影片**上而不是版面上，
> `delete_all_slides()` 之後就不存在了；版面 9 本身帶的是整幅背景圖，那是設計的一部分。
> `strip_group_shapes()` 仍保留，換版本母片時仍會清掉。

---

## QA 判準（`make qa`，任何一項 FAIL 就不准交付）

| 檢查 | 判準 |
|---|---|
| 頁數 | 45 ≤ total ≤ 60 |
| 溢排 | 每頁內文估算行數 ≤ 8；主標 ≤ 18 字；副標 ≤ 28 字；總字數 ≤ 160 |
| 資料來源 | 每頁（封面／頁籤／結尾除外）都有非空 sources |
| 外部連結 | 所有 url HTTP 200，死連結列出 |
| 具體性 | 每頁 body 至少含一個數字／年份／專有名詞，否則 WARN |
| 版型純度 | layout 必須在模板 11 種之內；無自建 textbox（資料來源行與圖表標題除外） |
| 字型 | 所有 run 的 `a:ea` typeface = 微軟正黑體 |
| 逐字稿 | 每頁字數 = duration_sec × 220/60 ±25%；總時長依 `deck.minutes` 推算（影片頁另計：只要 30–120 字的過場詞） |
| 對岸用語 | 黑名單掃描（見 `config/project.yaml` 的 `banned_terms`） |
| 視覺 | LibreOffice 轉 PNG 全頁截圖 → `output/preview/` |

---

## 環境需求

必要：Python 3.10+、`requirements.txt` 內的套件（`make setup` 一次裝好）。

選用（缺了不擋 pipeline，對應檢查會標 SKIP 並印出安裝指令）：

| 工具 | 用途 | 安裝 |
|---|---|---|
| `tesseract` + `chi_tra` | 掃描版 PDF 的 OCR | `apt install tesseract-ocr tesseract-ocr-chi-tra` |
| `flask` + `ruamel.yaml` | 上傳頁（純 CLI 可不裝） | 已列在 `requirements.txt` |
| `qrcode` | 影片頁的 QR code | 已列在 `requirements.txt` |
| `libreoffice-impress` | QA 預覽截圖 | `apt install libreoffice-impress` |
| `pdftoppm` | PDF 轉 PNG（沒有會改用 pymupdf） | `apt install poppler-utils` |
| 微軟正黑體／Noto CJK | 圖表中文字型 | `apt install fonts-noto-cjk` |

隨時可用 `make check` 確認目前環境狀態。注意：
`soffice` 指令存在不代表能轉檔——只裝 `libreoffice-core` 而沒裝 Impress 濾鏡時仍會失敗，
`make check` 會實際做一次最小轉檔來確認。

字型檢查：**微軟正黑體必須在執行機器上存在**，否則 LibreOffice 渲染出來的 QA 截圖會失真
（PPT 本身不受影響，但你看到的預覽會不準）。

---

## 沒有書也能驗證 pipeline

```bash
python tools/make_fixtures.py --chapters 8      # 產 8 章合成 digest + evidence
python scripts/05_outline.py --force
python tools/make_fixtures.py --fill-narration  # 依 duration_sec 產合成逐字稿
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

完整施工規格見 `docs/建置規劃書.pdf`。
