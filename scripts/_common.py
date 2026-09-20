# -*- coding: utf-8 -*-
"""共用工具：路徑、設定、JSON I/O、schema 驗證、CJK 字數估算。

所有 stage 腳本都從這裡取路徑與設定，不要在各腳本裡自己組 path。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent

ASSETS = ROOT / "assets"
CONFIG = ROOT / "config"
INPUT = ROOT / "input"
WORK = ROOT / "work"
PROMPTS = ROOT / "prompts"
OUTPUT = ROOT / "output"

RAW = WORK / "01_raw"
CHAPTERS = WORK / "02_chapters"
DIGEST = WORK / "03_digest"
EVIDENCE = WORK / "04_evidence"
AUTHOR_JSON = WORK / "04_author.json"    # Stage 4 作者解析（含中譯本章名）
GUIDE_JSON = WORK / "05a_guide.json"     # Stage 5a 導讀設計（作者章序）
DECK_JSON = WORK / "05_deck.json"
SCRIPT_JSON = WORK / "06_script.json"

TEMPLATE = ASSETS / "FH_template.pptx"
SPEC_FILE = CONFIG / "fh_template_spec.json"
PROJECT_FILE = CONFIG / "project.yaml"

PAGES_JSONL = RAW / "pages.jsonl"
TOC_JSON = RAW / "toc.json"

# --------------------------------------------------------------------------
# 終端輸出
# --------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOR else s


def info(msg: str) -> None:
    print(f"  {msg}")


def ok(msg: str) -> None:
    print(_c("32", f"  ✓ {msg}"))


def warn(msg: str) -> None:
    print(_c("33", f"  ! {msg}"))


def fail(msg: str) -> None:
    print(_c("31", f"  ✗ {msg}"))


def step(msg: str) -> None:
    print(_c("1;36", f"\n▶ {msg}"))


def stop(confirm: str, show: str = "", nxt: str = "") -> None:
    """每一個階段結束時印同一個樣子的停點。

    使用者的要求：「引導 AI 一步一步執行，每一步都要跟使用者確認再往下一步」。
    所以每支 script 跑完都要印這一段，AI 看到就知道該停下來問，不要一路跑到底。
    """
    print()
    print(_c("33;1", f"  ✋ 停：{confirm}"))
    if show:
        print(_c("33", f"     給他看：{show}"))
    if nxt:
        print(_c("33", f"     他說 OK 再跑：{nxt}"))
    print()


def die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    fail(msg)
    sys.exit(code)


# --------------------------------------------------------------------------
# 設定載入
# --------------------------------------------------------------------------
_spec_cache: dict | None = None
_project_cache: dict | None = None


def load_spec() -> dict:
    """版面參數 spec（唯讀，不要讓任何階段改寫它）。"""
    global _spec_cache
    if _spec_cache is None:
        if not SPEC_FILE.exists():
            die(f"找不到版面規格檔：{SPEC_FILE}")
        _spec_cache = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    return _spec_cache


def load_project() -> dict:
    """本次專案設定 config/project.yaml。"""
    global _project_cache
    if _project_cache is None:
        import yaml

        if not PROJECT_FILE.exists():
            die(f"找不到專案設定檔：{PROJECT_FILE}")
        _project_cache = yaml.safe_load(PROJECT_FILE.read_text(encoding="utf-8")) or {}
    return _project_cache


def limits() -> dict:
    return load_project().get("limits", {})


def ensure_dirs() -> None:
    for d in (RAW, CHAPTERS, DIGEST, EVIDENCE, OUTPUT, OUTPUT / "preview", OUTPUT / "charts"):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# JSON I/O
# --------------------------------------------------------------------------
def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# 中文字數／排版估算
# --------------------------------------------------------------------------
_PUNCT_NARROW = set("，。、；：！？「」『』（）〈〉《》…—－·")


def visual_len(text: str) -> float:
    """視覺寬度（以「全形字 = 1」為單位）。半形字元算 0.5。

    投影片字數限制（≤18 字主標之類）都是以全形為準，英文專有名詞
    如果用 len() 直接算會過度懲罰，所以半形折半計。
    """
    total = 0.0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("F", "W", "A"):
            total += 1.0
        elif ch.isspace():
            total += 0.5
        else:
            total += 0.5
    return total


def narration_chars(text: str) -> int:
    """逐字稿計字：中文字 + 英文詞，忽略標點、空白與 [舞台指示]。"""
    t = re.sub(r"\[[^\]]*\]", "", text)
    cn = sum(1 for ch in t if "一" <= ch <= "鿿")
    en = len(re.findall(r"[A-Za-z]+", t))
    return cn + en


CHARS_PER_LINE_24PT = 18  # 規劃書 §8.4：24pt 中文於 8,208,144 EMU 寬度約 18 字／行


# --------------------------------------------------------------------------
# 內文樣式：條列頁只准三種寫法，不准裸條列（prompts/outline.md）
#   chain    論證鏈    ① 因為 → ② 所以 → ③ 因此，每步一條
#   labeled  標籤＋說明 「機制　折現率貼近零…」，標籤 ≤ label_max_chars
#   prose    敘事段    一到兩段短文，沒有項目符號
# --------------------------------------------------------------------------
BODY_STYLES = ("chain", "labeled", "prose")
CHAIN_GLYPHS = "①②③④⑤⑥"


def body_item_text(style: str | None, item: dict, idx: int = 0) -> str:
    """一條 body 排到版面上實際會佔的文字（含標籤或序號）。估行數、算字數都用這個。"""
    text = (item.get("text") or "").strip()
    if style == "labeled":
        label = (item.get("label") or "").strip()
        return f"{label}　{text}" if label else text
    if style == "chain":
        g = CHAIN_GLYPHS[idx] if idx < len(CHAIN_GLYPHS) else "・"
        return f"{g} {text}"
    return text


def estimate_lines(body: list[dict], size_pt: int = 24, style: str | None = None) -> int:
    """估算內文 placeholder 佔幾行。

    body 為 [{"level": 0|1, "text": "..."}]（labeled 樣式另有 "label"）。
    第二層縮排後可用寬度變窄，每行可容字數依字級與縮排等比縮放。
    """
    if not body:
        return 0
    lines = 0
    for idx, item in enumerate(body):
        text = body_item_text(style, item, idx)
        if not text:
            continue
        level = int(item.get("level", 0))
        # 字級越大、每行容字越少；第二層縮排約損失 2 字寬
        per_line = CHARS_PER_LINE_24PT * (24.0 / size_pt) - (2 if level >= 1 else 0)
        per_line = max(per_line, 6)
        lines += max(1, -(-int(visual_len(text) * 100) // int(per_line * 100)))
    return lines


# --------------------------------------------------------------------------
# 卡片式內文的容量模型
#
# 06_build_pptx.draw_cards 怎麼畫，這裡就怎麼算，QA 也用同一份——以前 QA 自己
# 用「24pt placeholder 折 8 行」估，版面早就改成卡片＋自動縮字級了，於是兩邊
# 對不起來：明明排得好好的頁被判溢排，真正縮到 16pt 的頁反而沒人抓。
# 改任何一個常數，兩邊一起變。
# --------------------------------------------------------------------------
CARD_BOX = (467544, 1628800, 8208144, 4537075)   # 內文 placeholder (left, top, w, h)
CARD_GAP = 130000                                # 卡片之間的間距
CARD_H_MAX = 1900000                             # 單張卡最高 2.08 吋，再高卡片裡就只是空白
CARD_H_MIN = 620000
CARD_PAD_X = 150000                              # 卡片左右內縮
CARD_MARKER_W = {"labeled": 1220000, "chain": 700000}   # 標籤／序號佔掉的寬
CARD_TEXT_RATIO = 0.84                           # 卡片高度裡真正給文字的比例（其餘留白）
CARD_SIZES = (26, 24, 22, 20, 18, 16)            # 卡片文字由大往小試
PROSE_SIZES = (28, 26, 24, 22, 20)
PROSE_INDENT = 420000                            # prose 左側紅線＋留白
PROSE_TEXT_RATIO = 0.78
CARD_PER_PAGE = {"prose": 2}                     # 其餘樣式一頁四張，超過自動拆頁
CARD_PER_PAGE_DEFAULT = 4
CARD_COMFORT_PT = 20                             # 低於這個字級就算擠，QA 要提醒
CHARS_PER_LINE_24PT_FULL = 18.0                  # 24pt 中文在滿版寬度約 18 字／行
REF_WIDTH = 8208144                              # 上一行那個「滿版寬度」


def wrapped_lines(text: str, width_emu: int, size_pt: float) -> int:
    """這段字在指定寬度、指定字級下會折成幾行。"""
    cpl = max(4.0, CHARS_PER_LINE_24PT_FULL * (width_emu / REF_WIDTH) * (24.0 / size_pt))
    return max(1, math.ceil(visual_len(text or "") / cpl))


def line_height_emu(size_pt: float) -> int:
    """單行佔的高度（含行距）。12700 EMU = 1pt。"""
    return int(size_pt * 1.42 * 12700)


def fit_pt(texts: list[str], width_emu: int, height_emu: int,
           sizes: tuple[int, ...]) -> int:
    """這幾段字疊在一個框裡，由大到小挑第一個塞得下的字級；都塞不下就回最小的。"""
    for pt in sizes:
        need = sum(wrapped_lines(x, width_emu, pt) for x in texts) * line_height_emu(pt)
        if need <= height_emu:
            return pt
    return sizes[-1]


def card_per_page(style: str | None) -> int:
    return CARD_PER_PAGE.get(style or "", CARD_PER_PAGE_DEFAULT)


def card_fit(items: list[dict], style: str | None, box=CARD_BOX) -> dict:
    """卡片式內文實際會用的字級，以及最小字級還塞不塞得下。

    回傳 {"size_pt", "inner_w", "avail", "fits"}：
        size_pt  版面引擎會選的字級（prose 是整段，其餘是每張卡各算一格）
        fits     False = 連最小字級都爆框，這才是真的溢排
    """
    texts = [(b.get("text") or "").strip() for b in (items or [])]
    texts = [t for t in texts if t]
    if not texts:
        return {"size_pt": 0, "inner_w": 0, "avail": 0, "fits": True}

    _, _, width, height = box
    if style == "prose":
        inner_w = width - PROSE_INDENT
        avail = int(height * PROSE_TEXT_RATIO)
        sizes, measured = PROSE_SIZES, texts          # 段落是疊在同一個框裡
    else:
        n = len(texts)
        card_h = int(max(CARD_H_MIN, min(CARD_H_MAX, (height - CARD_GAP * (n - 1)) / n)))
        marker = CARD_MARKER_W.get(style or "", CARD_MARKER_W["chain"])
        inner_w = width - CARD_PAD_X * 2 - marker - 120000
        avail = int(card_h * CARD_TEXT_RATIO)
        # 每張卡各佔一格，所以只要最長的那條塞得下，整頁就塞得下
        sizes, measured = CARD_SIZES, [max(texts, key=visual_len)]

    size_pt = fit_pt(measured, inner_w, avail, sizes)
    need = sum(wrapped_lines(x, inner_w, sizes[-1]) for x in measured) * line_height_emu(sizes[-1])
    return {"size_pt": size_pt, "inner_w": inner_w, "avail": avail, "fits": need <= avail}


_CONCRETE_RE = re.compile(
    r"[0-9０-９]"                       # 阿拉伯數字（含全形）
    r"|[一二三四五六七八九十百千萬億兆]\s*[年月日%％倍成元人次]"  # 中文數量詞
    r"|[A-Z][A-Za-z]{2,}"              # 英文專有名詞 / 縮寫
)


def has_concrete(text: str) -> bool:
    """§10 具體性檢查：是否含數字／年份／專有名詞。"""
    return bool(_CONCRETE_RE.search(text or ""))


# --------------------------------------------------------------------------
# Schema 驗證（輕量，不引入 jsonschema 相依）
# --------------------------------------------------------------------------
class SchemaError(Exception):
    pass


def check_keys(obj: dict, required: Iterable[str], where: str, errors: list[str]) -> None:
    if not isinstance(obj, dict):
        errors.append(f"{where}: 應為物件，實際為 {type(obj).__name__}")
        return
    for k in required:
        if k not in obj:
            errors.append(f"{where}: 缺少必要欄位 '{k}'")


def nonempty_str(obj: dict, key: str, where: str, errors: list[str], min_len: int = 1) -> None:
    v = obj.get(key)
    if not isinstance(v, str) or len(v.strip()) < min_len:
        errors.append(f"{where}.{key}: 必須是非空字串（目前：{v!r}）")


# --------------------------------------------------------------------------
# 章節檔工具
# --------------------------------------------------------------------------
FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_chapter_file(path: Path) -> tuple[dict, str]:
    """回傳 (front_matter_dict, body_text)。"""
    import yaml

    raw = Path(path).read_text(encoding="utf-8")
    m = FRONT_MATTER_RE.match(raw)
    if not m:
        return {}, raw
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, raw[m.end():]


def chapter_files() -> list[Path]:
    return sorted(CHAPTERS.glob("ch*.md"))


_SECTION_PREFIX_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[章節]|[0-9]+|Chapter\s+[0-9]+"
    r"|Introduction|Prologue|Preface|Conclusion|Postscript|Epilogue|引言|序章|前言|結語|後記|尾聲)"
    r"\s*[:：.．\-—]?\s*", re.I)


def strip_chapter_number(title: str) -> str:
    """拆章標題「5: John Bull …」「Introduction: The Anarchist…」「第15章：焦慮的代價（The Price of Anxiety）」
    → 章名本身（中文＋括號英文時取括號裡的英文，那才是作者的原章名）。"""
    t = _SECTION_PREFIX_RE.sub("", (title or "").strip(), count=1).strip()
    m = re.search(r"[（(]([^（）()]*[A-Za-z][^（）()]*)[）)]", t)
    if m and re.search(r"[\u4e00-\u9fff]", t[:m.start()]):
        t = m.group(1).strip()
    return t


def norm_title(title: str) -> str:
    """章名比對用：小寫、去標點與章號、統一撇號。"""
    t = strip_chapter_number(title).lower().replace("’", "'")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t).strip()


def load_author() -> dict:
    """work/04_author.json（作者解析 + 中譯本資訊）；沒有就回空 dict。"""
    if not AUTHOR_JSON.exists():
        return {}
    try:
        return read_json(AUTHOR_JSON) or {}
    except Exception:  # noqa: BLE001
        return {}


def official_chapter_names() -> dict[str, str]:
    """官方中譯章名：{norm(英文章名): 中譯章名}，來自 04_author.json 的 book.chapters。"""
    out: dict[str, str] = {}
    for c in ((load_author().get("book") or {}).get("chapters") or []):
        if isinstance(c, dict) and (c.get("title_en") or "").strip() and (c.get("title_zh") or "").strip():
            out[norm_title(c["title_en"])] = c["title_zh"].strip()
    return out


def chapter_display_name(title: str, digest: dict | None = None) -> tuple[str, str]:
    """投影片上的章名：(顯示名, 英文原名)。

    優先序：官方中譯（04_author.json）> digest.chapter_title_zh（忠實翻譯）> 英文原名。
    翻不好的中文寧可不要——規則是「找不到官方譯名就用原文」。
    """
    en = strip_chapter_number((digest or {}).get("chapter_title_en") or title)
    zh = official_chapter_names().get(norm_title(en), "")
    if not zh and digest:
        zh = (digest.get("chapter_title_zh") or "").strip()
    return (zh or en), en


def safe_filename(name: str, maxlen: int = 40) -> str:
    """章節標題轉成可用檔名（保留中文，去掉路徑危險字元）。"""
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "", name or "").strip()
    name = re.sub(r"\s+", "_", name)
    return name[:maxlen] or "untitled"


# --------------------------------------------------------------------------
# 外部工具偵測（規劃書 §3：缺工具不擋 pipeline，標 SKIP）
# --------------------------------------------------------------------------
def have_cmd(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def soffice_bin() -> str | None:
    for c in ("soffice", "libreoffice"):
        if have_cmd(c):
            return c
    return None


# --------------------------------------------------------------------------
# 內頁色系（母片三組內頁的頁首色帶不同）
# --------------------------------------------------------------------------
# family → (主力版型, 次要版型, 第三版型)。主力用在核心主張與論點展開，
# 次要用在台灣對照，第三用在全書綜合，維持規劃書 §7.1 的視覺變化。
LAYOUT_FAMILIES = {
    1: {"label": "復華紅", "hex": "#B82837", "single": 3, "titled": 4},
    2: {"label": "米白", "hex": "#E9E4DA", "single": 5, "titled": 6},
    3: {"label": "灰", "hex": "#BFBFBF", "single": 7, "titled": 8},
}


def layout_family() -> int:
    f = load_project().get("deck", {}).get("layout_family", 1)
    try:
        f = int(f)
    except (TypeError, ValueError):
        f = 1
    return f if f in LAYOUT_FAMILIES else 1


def family_layouts(fam: int | None = None) -> tuple[int, int, int]:
    """回傳 (主力, 次要, 第三) 的版面 index，皆為『主標+副標』型。"""
    fam = fam or layout_family()
    order = [fam] + [k for k in (1, 2, 3) if k != fam]
    return tuple(LAYOUT_FAMILIES[k]["titled"] for k in order)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# 語氣
# --------------------------------------------------------------------------
def tone_key() -> str:
    cfg = load_project()
    t = cfg.get("deck", {}).get("tone", "professional")
    return t if t in (cfg.get("tone_presets") or {}) else "professional"


def tone_preset() -> dict:
    return (load_project().get("tone_presets") or {}).get(tone_key(), {})


def tone_directive(kind: str = "slide") -> str:
    """kind = 'slide'（文案）或 'narration'（逐字稿）。"""
    p = tone_preset()
    body = (p.get(kind) or "").strip()
    label = p.get("label", tone_key())
    aud = p.get("audience", "")
    head = f"語氣：{label}" + (f"（{aud}）" if aud else "")
    return f"{head}\n{body}" if body else head


# --------------------------------------------------------------------------
# 頁面角色（金字塔結構）：08_qa 的「敘事結構」檢查與 07 的分節都靠 role
# --------------------------------------------------------------------------
ROLE_LABELS = {
    "cover": "封面", "author": "作者頁", "summary": "執行摘要", "map": "章序地圖",
    "part": "分部頁籤", "divider": "章名頁籤", "outline": "大綱頁", "evidence": "示意圖／重點頁",
    "today": "今天的數字", "implication": "全書意涵", "counter": "反方頁", "closing": "結語",
    "wish": "祝賀頁", "appendix": "附錄", "video": "影片頁",
}


# 頁籤／主張句的最低門檻：不是名詞標籤。以這些字結尾的多半是「主題名」
TOPIC_TAILS = ("的由來", "簡史", "歷史", "篇", "章", "概述", "概論", "介紹", "背景", "現況",
               "分析", "總覽", "回顧", "與展望", "的問題", "的代價", "的影響")


def looks_like_topic(claim: str) -> str | None:
    """回傳「為什麼這不是主張句」，None 代表通過。"""
    c = (claim or "").strip()
    if visual_len(c) < 6:
        return "太短，看起來是標籤不是句子"
    if "：" in c or ":" in c:
        return "含冒號，像是「主題：副題」的標籤"
    for tail in TOPIC_TAILS:
        if c.endswith(tail):
            return f"以「{tail}」結尾，是主題名不是結論句"
    return None


def is_appendix(slide: dict) -> bool:
    """附錄頁：備用素材，不計入講述時長，也不需要逐字稿。"""
    return slide.get("role") == "appendix"


def talk_slides(slides: list[dict]) -> list[dict]:
    """真正會講到的頁面（排除附錄）。"""
    return [s for s in slides if not is_appendix(s)]


# --------------------------------------------------------------------------
# 頁數參考區間：沒指定 target_slides 就依分鐘數推算（只用來 WARN，不裁頁）
# --------------------------------------------------------------------------
PAGES_PER_MINUTE = 0.85   # 60 分鐘 → 約 51 頁，落在規劃書的 45–60 區間中段


def target_slides() -> tuple[int, int]:
    deck = load_project().get("deck", {})
    ts = deck.get("target_slides")
    if isinstance(ts, (list, tuple)) and len(ts) == 2 and all(
            isinstance(x, (int, float)) for x in ts):
        return int(ts[0]), int(ts[1])
    minutes = int(deck.get("minutes", 60) or 60)
    mid = minutes * PAGES_PER_MINUTE
    return max(5, int(mid * 0.85)), max(8, int(mid * 1.15))


# --------------------------------------------------------------------------
# 影片時間碼
# --------------------------------------------------------------------------
def parse_timecode(v: str | int | float | None) -> int:
    """'3:20' / '01:02:03' / 200 → 秒。看不懂就回 0。"""
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return max(0, int(v))
    parts = str(v).strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    sec = 0
    for n in nums:
        sec = sec * 60 + n
    return max(0, sec)


def format_timecode(sec: int) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def videos() -> list[dict]:
    """讀 config/project.yaml 的 videos[]，補好秒數欄位並濾掉沒網址的。"""
    out = []
    for v in (load_project().get("videos") or []):
        if not isinstance(v, dict) or not (v.get("url") or "").strip():
            continue
        start = parse_timecode(v.get("start"))
        end = parse_timecode(v.get("end"))
        dur = max(0, end - start)
        out.append({
            "title": (v.get("title") or "").strip() or "參考影片",
            "url": v["url"].strip(),
            "start": start,
            "end": end,
            "duration_sec": dur,
            "after_ch": (v.get("after_ch") or "").strip() or None,
            "note": (v.get("note") or "").strip(),
        })
    return out


def talk_minutes_range() -> tuple[int, int]:
    """講述時間目標區間（分鐘）。

    config 明寫 narration.total_minutes_range 就用它；否則依 deck.minutes 推算：
    上限 = 總長 - 5 分鐘 Q&A，下限 = 上限的 86%（60 分鐘 → 50–55，與規劃書一致）。
    """
    cfg = load_project()
    r = (cfg.get("narration") or {}).get("total_minutes_range")
    if isinstance(r, (list, tuple)) and len(r) == 2 and all(
            isinstance(x, (int, float)) for x in r):
        return int(r[0]), int(r[1])
    minutes = int((cfg.get("deck") or {}).get("minutes", 60) or 60)
    hi = max(5, minutes - 5)
    return max(3, int(hi * 0.86)), hi
