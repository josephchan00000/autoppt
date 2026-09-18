# Stage 4 — 外部研究擴編（台灣市場對照，每章跑一次）

**輸入**：`{digest_json}`（某一章的 Stage 3 摘要）

**任務**：把這一章的論點連結到「可查證的外部現實」與「台灣市場 / 復華投信的視角」。

## 步驟

1. 從 `open_questions` + `data_points` 生成 3–5 個檢索查詢（中英各半）。
2. 用 WebSearch 檢索，來源優先級：
   **官方統計 > 監理機關 > 學術／研究機構 > 財經媒體 > 部落格**
   台灣類優先來源：主計總處、金管會、中央銀行、投信投顧公會、證交所、TEJ、國發會、
   財政部統計處、勞動部勞保局（退休金相關）。
   國際類優先來源：IMF、OECD、World Bank、BIS、Fed / FRED、SEC、ICI、Morningstar、
   S&P Dow Jones Indices（SPIVA）。
3. **只採信能給出明確 URL 與日期的資料。**
4. 檢查書中數據是否過期：`max_source_age_years`（見 config/project.yaml，預設 3 年）
   以外的數據，一律去找最新值，並標 `outdated`。

## 輸出 JSON（不要 markdown 圍欄）

```json
{
  "ch_id": "ch01",
  "verified": [
    {
      "book_claim": "書中說法",
      "status": "confirmed|outdated|contested",
      "current_fact": "最新事實與數字",
      "as_of": "2026-03",
      "source_title": "主計總處《國民所得統計》",
      "source_url": "https://..."
    }
  ],
  "taiwan_lens": [
    {
      "angle": "台灣／復華視角的對照標題",
      "insight": "150 字內，說明這章的觀點在台灣市場會怎麼呈現／有什麼不同",
      "supporting_data": "具體數據",
      "source_title": "",
      "source_url": ""
    }
  ],
  "extensions": [
    {"title": "延伸論點", "content": "書沒講但值得補的", "source_title": "", "source_url": ""}
  ],
  "chart_candidates": [
    {
      "title": "可畫成圖表的資料",
      "data": [{"label": "2023", "value": 12.4}],
      "chart_type": "bar|line|stacked",
      "unit": "%",
      "source_title": "",
      "source_url": ""
    }
  ],
  "video_candidates": [
    {
      "title": "影片標題",
      "url": "https://www.youtube.com/watch?v=...",
      "channel": "頻道／主辦單位",
      "why": "為什麼這一段值得在分享會播（40 字內）",
      "suggested_start": "2:15",
      "suggested_end": "5:40"
    }
  ]
}
```

## 影片建議（`video_candidates`，每章 1–2 支）

順便找這一章主題相關、**適合在分享會現場播 3–5 分鐘**的影片：
作者訪談、TED／機構講座、財經媒體的專題片段、監理機關的說明影片。

- `url` 必須是實際搜到的影片頁網址，不要拼湊
- `suggested_start` / `suggested_end` 用 mm:ss，挑出真正切題的那一段，
  不要給整支兩小時的演講
- `why` 要講清楚「這段補了投影片上沒有的什麼」，不是複述影片簡介
- 找不到合適的就給空陣列，**不要為了湊數放不相關的影片**

使用者會自己從清單裡挑要不要用，挑中的才會變成簡報裡的影片頁。

## 硬性規則（違反任何一條，這一章要重跑）

1. **每一筆都必須有 `source_url`。查不到就不要寫，寧可少一筆，絕對不准編造 URL
   或推測數字。** 這是唯一會讓你在會議上出事的錯誤。
2. `source_url` 必須是你**實際從 WebSearch 結果拿到的網址**，不可以自己拼湊
   （例如把機構首頁加上猜測的路徑）。拼湊出來的網址 QA 階段一定會被 HTTP 檢查抓到。
3. 標示 `outdated` 的書中數據，**一定要放進投影片**——這是分享會最有價值的部分。
   找到最新值時，`current_fact` 要同時寫出「書中值 → 最新值」的對比。
4. **每章至少 1 筆 `taiwan_lens`。** 如果這一章的主題實在與台灣市場無關，
   就找「這個觀念在台灣的資產管理實務上怎麼被應用／為什麼不適用」的角度，
   仍然要有可查證來源。
5. `chart_candidates[].data` 的每一個數值都必須來自 `source_url` 那一份資料，
   不可以混合多個來源卻只標一個。混合來源時拆成多筆 chart_candidate。
6. `as_of` 用 `YYYY-MM`，寫的是**資料本身的時點**，不是你檢索的日期。

## 語言

繁體中文。機構名用官方全稱首次出現，之後可用簡稱。
不使用對岸用語。

## 輸出

寫入 `work/04_evidence/{ch_id}.json`。
一次只處理一章。寫完後跑 `python scripts/04_research.py --validate {ch_id}`。
全部章節跑完後：

```bash
python scripts/08_qa.py --check-sources    # URL 全檢
python scripts/04_research.py --videos     # 列出所有影片建議，讓使用者挑
```
