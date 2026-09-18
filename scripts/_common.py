# -*- coding: utf-8 -*-
"""共用工具：路徑、設定、JSON I/O、schema 驗證、CJK 字數估算。

所有 stage 腳本都從這裡取路徑與設定，不要在各腳本裡自己組 path。
"""
from __future__ import annotations

import json
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


def strip_code_fence(text: str) -> str:
    """模型偶爾會包 ```json 圍欄，這裡剝掉再 parse。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


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


def cjk_chars(text: str) -> int:
    """純中文字數（逐字稿字數用這個算，標點與空白不計）。"""
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def narration_chars(text: str) -> int:
    """逐字稿計字：中文字 + 英文詞，忽略標點、空白與 [舞台指示]。"""
    t = re.sub(r"\[[^\]]*\]", "", text)
    cn = sum(1 for ch in t if "一" <= ch <= "鿿")
    en = len(re.findall(r"[A-Za-z]+", t))
    return cn + en


CHARS_PER_LINE_24PT = 18  # 規劃書 §8.4：24pt 中文於 8,208,144 EMU 寬度約 18 字／行


def estimate_lines(body: list[dict], size_pt: int = 24) -> int:
    """估算內文 placeholder 佔幾行。

    body 為 [{"level": 0|1, "text": "..."}]。第二層縮排後可用寬度變窄，
    每行可容字數依字級與縮排等比縮放。
    """
    if not body:
        return 0
    lines = 0
    for item in body:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        level = int(item.get("level", 0))
        # 字級越大、每行容字越少；第二層縮排約損失 2 字寬
        per_line = CHARS_PER_LINE_24PT * (24.0 / size_pt) - (2 if level >= 1 else 0)
        per_line = max(per_line, 6)
        lines += max(1, -(-int(visual_len(text) * 100) // int(per_line * 100)))
    return lines


def body_text_total(body: list[dict]) -> float:
    return sum(visual_len((b.get("text") or "")) for b in (body or []))


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


def require(cond: bool, msg: str, errors: list[str]) -> bool:
    if not cond:
        errors.append(msg)
    return cond


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


def chapter_ids() -> list[str]:
    ids = []
    for p in chapter_files():
        m = re.match(r"(ch\d+)", p.name)
        if m:
            ids.append(m.group(1))
    return ids


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
