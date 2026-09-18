#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台 —— 涵蓋 Stage 1–8 的網頁介面。

Stage 3/4（深讀與研究）需要模型逐章讀書與上網查證，不是跑腳本就有結果，
所以這頁只負責顯示逐章狀態與產生「貼到 Claude 對話視窗」的指令；
Claude 與這頁讀寫同一個 work/ 資料夾，寫完檔案這裡輪詢就看得到。

    make web                       # 預設 http://127.0.0.1:5000
    python web/app.py --port 8080
    python web/app.py --host 0.0.0.0    # 需要別台電腦連才加，預設只綁本機

設計上只做三件事：收檔、跑 Stage 1–2、把章節表攤開給你確認。
拆錯了可以直接在頁面上換拆章策略重跑，不用回終端機。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _common import (  # noqa: E402
    ASSETS, CHAPTERS, CONFIG, DECK_JSON, DIGEST, EVIDENCE, INPUT, LAYOUT_FAMILIES,
    OUTPUT, PAGES_JSONL, PROJECT_FILE, RAW, SCRIPT_JSON, TEMPLATE, chapter_files,
    format_timecode, load_project, parse_timecode, parse_chapter_file, read_json,
    target_slides,
)

from flask import Flask, jsonify, render_template, request, send_file  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402

ALLOWED_EXT = {".pdf", ".epub"}
CONVERT_HINT_EXT = {".mobi", ".azw", ".azw3"}
MAX_MB = 300

# 與 02_split_chapters.py 一致的異常判準
MIN_WORDS = 500
MAX_SHARE = 0.25

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024
# 本機工具，改完樣板不用重啟；Jinja 預設會把編譯結果快取在記憶體裡
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


def venv_python() -> str:
    """優先用專案 venv 的直譯器，沒有才退回當前直譯器。"""
    cand = ROOT / ".venv" / "bin" / "python"
    return str(cand) if cand.exists() else sys.executable


def run_stage(script: str, *args: str, timeout: int = 3600) -> dict:
    """跑一支 stage 腳本，回傳 {ok, cmd, output}。"""
    cmd = [venv_python(), str(ROOT / "scripts" / script), *args]
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout, env={"NO_COLOR": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    except subprocess.TimeoutExpired:
        return {"ok": False, "cmd": " ".join(cmd[1:]),
                "output": f"逾時（{timeout}s）。掃描版 PDF 的 OCR 很慢，請改用 CLI 執行。"}
    out = (p.stdout or "") + (p.stderr or "")
    return {"ok": p.returncode == 0, "cmd": " ".join(Path(c).name if i == 0 else c
                                                     for i, c in enumerate(cmd[1:])),
            "output": out.strip()}


def chapter_rows() -> list[dict]:
    """讀 work/02_chapters/*.md 的 front-matter，組成驗收表格資料。"""
    rows = []
    for p in chapter_files():
        meta, _ = parse_chapter_file(p)
        rows.append({
            "ch_id": meta.get("ch_id") or p.name.split("_")[0],
            "title": meta.get("title") or p.stem,
            "pages": meta.get("pages") or [],
            "word_count": int(meta.get("word_count") or 0),
            "file": p.name,
        })
    total = sum(r["word_count"] for r in rows) or 1
    for r in rows:
        r["share"] = r["word_count"] / total
        if r["word_count"] < MIN_WORDS:
            r["flag"] = "字數過少"
        elif r["share"] > MAX_SHARE:
            r["flag"] = "占比過高"
        else:
            r["flag"] = ""
    return rows


def current_state() -> dict:
    books = [p for p in sorted(INPUT.iterdir()) if p.is_file() and p.name != ".gitkeep"] \
        if INPUT.exists() else []
    rows = chapter_rows()
    return {
        "book": books[0].name if books else None,
        "book_size_mb": round(books[0].stat().st_size / 1e6, 1) if books else 0,
        "extracted": PAGES_JSONL.exists(),
        "chapters": rows,
        "bad": sum(1 for r in rows if r["flag"]),
        "ocr_report": (RAW / "ocr_confidence.md").exists(),
        "ch_ids": [r["ch_id"] for r in rows],
    }




# ==========================================================================
# 全流程狀態
# ==========================================================================
# 這頁與對話視窗裡的 Claude 讀寫同一個資料夾，所以 Stage 3/4 不需要複製貼上：
# Claude 把 work/03_digest/chNN.json 寫好，這裡輪詢就會看到。
def _ch_meta() -> list[dict]:
    out = []
    for p in chapter_files():
        meta, _ = parse_chapter_file(p)
        out.append({"ch_id": meta.get("ch_id") or p.name.split("_")[0],
                    "title": meta.get("title") or p.stem})
    return out


def _stage34_rows() -> list[dict]:
    """逐章的深讀／研究狀態。壞掉的（schema 不合格）也要標出來。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util

    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    try:
        d3 = _load("s03", "03_digest.py")
        d4 = _load("s04", "04_research.py")
    except Exception:                                  # noqa: BLE001
        d3 = d4 = None

    rows = []
    for c in _ch_meta():
        ch = c["ch_id"]
        dp, ep = DIGEST / f"{ch}.json", EVIDENCE / f"{ch}.json"
        row = {**c, "digest": "todo", "evidence": "todo",
               "digest_errors": 0, "evidence_errors": 0}
        if dp.exists():
            errs = d3.validate_digest(dp, ch) if d3 else []
            row["digest"] = "bad" if errs else "done"
            row["digest_errors"] = len(errs)
        if ep.exists():
            errs = d4.validate_evidence(ep, ch) if d4 else []
            row["evidence"] = "bad" if errs else "done"
            row["evidence_errors"] = len(errs)
        rows.append(row)
    return rows


def _outputs() -> list[dict]:
    out = []
    if OUTPUT.exists():
        for p in sorted(OUTPUT.iterdir()):
            if p.is_file() and p.suffix.lower() in (".pptx", ".docx", ".pdf", ".md"):
                out.append({"name": p.name, "size_mb": round(p.stat().st_size / 1e6, 2),
                            "mtime": int(p.stat().st_mtime)})
    return out


def pipeline_state() -> dict:
    chs = _ch_meta()
    rows = _stage34_rows() if chs else []
    deck = None
    if DECK_JSON.exists():
        try:
            d = read_json(DECK_JSON)
            slides = d.get("slides", [])
            todo = sum(1 for s in slides
                       if "【待填】" in (str(s.get("title", "")) + str(s.get("subtitle", ""))
                                       + str(s.get("body", ""))))
            narr = sum(1 for s in slides if (s.get("narration") or "").strip())
            total_sec = sum(int(s.get("duration_sec", 0)) for s in slides)
            lo, hi = target_slides()
            deck = {"slides": len(slides), "todo": todo, "narrated": narr,
                    "total_sec": total_sec, "target": [lo, hi],
                    "tone": d.get("meta", {}).get("tone", ""),
                    "family": d.get("meta", {}).get("layout_family_label", "")}
        except Exception:                              # noqa: BLE001
            deck = {"error": True}

    qa = None
    qa_file = OUTPUT / "qa_report.md"
    if qa_file.exists():
        txt = qa_file.read_text(encoding="utf-8")
        qa = {"markdown": txt,
              "fail": txt.count("| **FAIL** |"),
              "warn": txt.count("| **WARN** |"),
              "skip": txt.count("| **SKIP** |"),
              "pass": txt.count("| **PASS** |"),
              "mtime": int(qa_file.stat().st_mtime)}

    return {
        "chapters": rows,
        "digest_done": sum(1 for r in rows if r["digest"] == "done"),
        "evidence_done": sum(1 for r in rows if r["evidence"] == "done"),
        "deck": deck,
        "qa": qa,
        "outputs": _outputs(),
    }


# 可從網頁觸發的階段（Stage 3/4 不在此列——那是對話視窗裡的 Claude 的工作）
RUNNABLE = {
    "outline": ("05_outline.py", ["--force"]),
    "pptx": ("06_build_pptx.py", []),
    "script": ("07_build_script.py", []),
    "qa": ("08_qa.py", ["--all"]),
    "check_deck": ("08_qa.py", ["--check-deck"]),
    "check_sources": ("08_qa.py", ["--check-sources"]),
}


# ==========================================================================
# 設定讀寫
# ==========================================================================
def reload_project() -> dict:
    """project.yaml 被這頁改過之後，要讓 _common 的快取失效再重讀。"""
    import _common

    _common._project_cache = None
    return load_project()


def settings_payload() -> dict:
    cfg = reload_project()
    deck = cfg.get("deck", {})
    presets = cfg.get("tone_presets") or {}
    return {
        "book": cfg.get("book", {}),
        "presenter": cfg.get("presenter", {}),
        "minutes": int(deck.get("minutes", 60) or 60),
        "layout_family": int(deck.get("layout_family", 1) or 1),
        "tone": deck.get("tone", "professional"),
        "tones": [{"key": k, "label": v.get("label", k),
                   "audience": v.get("audience", ""),
                   "slide": (v.get("slide") or "").strip()}
                  for k, v in presets.items()],
        "families": [{"key": k, "label": v["label"], "hex": v["hex"]}
                     for k, v in LAYOUT_FAMILIES.items()],
        "videos": [{"title": v.get("title", ""), "url": v.get("url", ""),
                    "start": v.get("start", ""), "end": v.get("end", ""),
                    "after_ch": v.get("after_ch", "") or "",
                    "note": v.get("note", "")}
                   for v in (cfg.get("videos") or []) if isinstance(v, dict)],
    }


def save_settings(data: dict) -> tuple[bool, str]:
    """把表單寫回 config/project.yaml。

    用 ruamel.yaml 做 round-trip，這樣檔案裡的註解與排版都會保留——
    project.yaml 是要給人手改的，存一次就把說明洗掉會很難用。
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    cfg = yaml.load(PROJECT_FILE.read_text(encoding="utf-8")) or {}

    book = data.get("book") or {}
    for k in ("title_zh", "title_en", "author", "publisher_year"):
        if k in book:
            cfg.setdefault("book", {})[k] = Q(str(book[k] or "").strip())
    pres = data.get("presenter") or {}
    for k in ("name", "dept", "date"):
        if k in pres:
            cfg.setdefault("presenter", {})[k] = Q(str(pres[k] or "").strip())

    deck = cfg.setdefault("deck", {})
    if "minutes" in data:
        try:
            m = int(data["minutes"])
        except (TypeError, ValueError):
            return False, "預計長度必須是數字"
        if not (10 <= m <= 240):
            return False, "預計長度請填 10–240 分鐘"
        deck["minutes"] = m
        # 這兩個交給 minutes 推算（_common.target_slides / talk_minutes_range）
        deck["target_slides"] = None
        cfg.setdefault("narration", {})["total_minutes_range"] = None
    if "layout_family" in data:
        try:
            f = int(data["layout_family"])
        except (TypeError, ValueError):
            f = 1
        if f not in LAYOUT_FAMILIES:
            return False, f"內頁色系只能是 {sorted(LAYOUT_FAMILIES)}"
        deck["layout_family"] = f
    if "tone" in data:
        t = str(data["tone"])
        if t not in (cfg.get("tone_presets") or {}):
            return False, f"未知的語氣：{t}"
        deck["tone"] = t

    if "videos" in data:
        vids = []
        for i, v in enumerate(data["videos"] or [], start=1):
            url = str(v.get("url") or "").strip()
            if not url:
                continue
            if not url.startswith(("http://", "https://")):
                return False, f"第 {i} 支影片的網址要以 http:// 或 https:// 開頭"
            start, end = str(v.get("start") or "").strip(), str(v.get("end") or "").strip()
            ss, ee = parse_timecode(start), parse_timecode(end)
            if end and ee <= ss:
                return False, f"第 {i} 支影片的結束時間要大於開始時間"
            vids.append({
                "title": Q(str(v.get("title") or "").strip() or "參考影片"),
                "url": Q(url),
                # 時間碼一定要加引號：YAML 1.1 會把 1:30 當六十進位數字解析成 90，
                # 檔案雖然還讀得回來，但人看不懂
                "start": Q(start or "0:00"),
                "end": Q(end or format_timecode(ss + 180)),
                "after_ch": Q(str(v.get("after_ch") or "").strip()),
                "note": Q(str(v.get("note") or "").strip()),
            })
        cfg["videos"] = vids

    from io import StringIO

    buf = StringIO()
    yaml.dump(cfg, buf)
    PROJECT_FILE.write_text(buf.getvalue(), encoding="utf-8")
    reload_project()
    return True, "已存檔到 config/project.yaml"


# ==========================================================================
# 版面預覽圖：直接從母片抽出各版面的背景圖
# ==========================================================================
_preview_cache: dict[int, bytes] = {}


def layout_preview(family: int) -> bytes | None:
    """抽出該色系內頁的背景圖，疊上示意文字，回傳 PNG bytes。"""
    if family in _preview_cache:
        return _preview_cache[family]
    if not TEMPLATE.exists():
        return None
    from io import BytesIO

    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from PIL import Image, ImageDraw

    idx = LAYOUT_FAMILIES[family]["titled"]
    prs = Presentation(str(TEMPLATE))
    blob = None
    for shp in prs.slide_layouts[idx].shapes:
        if not shp.is_placeholder and shp.shape_type == MSO_SHAPE_TYPE.PICTURE:
            blob = shp.image.blob
            break
    if blob is None:
        return None

    W, H = 640, 480
    im = Image.open(BytesIO(blob)).convert("RGB").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im)

    # 依 spec 的 EMU 比例畫出主標／副標／內文的位置示意
    def box(x, y, w, h, fill):
        d.rectangle([x * W, y * H, (x + w) * W, (y + h) * H], fill=fill)

    box(0.059, 0.038, 0.60, 0.055, (38, 38, 39))          # 主標
    box(0.059, 0.127, 0.42, 0.036, (201, 160, 99))        # 副標
    for k in range(4):                                     # 內文四條
        box(0.051, 0.262 + k * 0.088, 0.62 - k * 0.05, 0.030, (150, 150, 153))
    box(0.051, 0.905, 0.38, 0.020, (190, 190, 193))        # 資料來源行

    buf = BytesIO()
    im.save(buf, format="PNG")
    _preview_cache[family] = buf.getvalue()
    return _preview_cache[family]


# ==========================================================================
@app.get("/")
def index():
    return render_template("index.html", state=current_state(),
                           settings=settings_payload(), pipeline=pipeline_state(),
                           max_mb=MAX_MB)


@app.get("/api/state")
def api_state():
    return jsonify(current_state())


@app.post("/api/upload")
def api_upload():
    f = request.files.get("book")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "沒有選到檔案"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext in CONVERT_HINT_EXT:
        return jsonify({"ok": False, "error":
                        f"暫不直接支援 {ext}。請先用 Calibre 轉成 EPUB："
                        f"ebook-convert 你的書{ext} 你的書.epub"}), 400
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False,
                        "error": f"只支援 {'、'.join(sorted(ALLOWED_EXT))}（收到 {ext or '無副檔名'}）"}), 400

    # 保留原始中文檔名的可讀性，但擋掉路徑字元；secure_filename 會吃掉中文，
    # 所以只在它回傳空字串時才退回 secure_filename 的結果。
    safe = Path(f.filename).name.replace("/", "_").replace("\\", "_").lstrip(".")
    if not safe or safe in (".", ".."):
        safe = secure_filename(f.filename) or "book.pdf"

    INPUT.mkdir(parents=True, exist_ok=True)
    # 一次只處理一本書：先清掉舊的
    for old in INPUT.iterdir():
        if old.is_file() and old.name != ".gitkeep":
            old.unlink()
    dest = INPUT / safe
    f.save(str(dest))

    steps = [run_stage("01_extract.py", "--input", str(dest.relative_to(ROOT)))]
    if steps[0]["ok"]:
        steps.append(run_stage("02_split_chapters.py"))

    return jsonify({"ok": all(s["ok"] for s in steps), "steps": steps,
                    "state": current_state()})


@app.post("/api/resplit")
def api_resplit():
    """拆錯了就換策略重拆——章節表底下那幾顆按鈕。"""
    mode = (request.json or {}).get("mode", "auto")
    n = int((request.json or {}).get("n") or 8)
    if not PAGES_JSONL.exists():
        return jsonify({"ok": False, "error": "還沒解析過書檔，請先上傳"}), 400

    args: list[str] = []
    if mode == "regex":
        args = ["--force-regex"]
    elif mode == "split":
        args = ["--force-split", str(max(2, min(n, 40)))]

    step = run_stage("02_split_chapters.py", *args)
    return jsonify({"ok": step["ok"], "steps": [step], "state": current_state()})


@app.post("/api/reset")
def api_reset():
    """清掉書檔與中間檔，重來一次。"""
    for d in (RAW, CHAPTERS):
        if d.exists():
            for p in d.iterdir():
                if p.name != ".gitkeep":
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
    if INPUT.exists():
        for p in INPUT.iterdir():
            if p.is_file() and p.name != ".gitkeep":
                p.unlink()
    return jsonify({"ok": True, "state": current_state()})



@app.get("/api/settings")
def api_settings():
    return jsonify(settings_payload())


@app.post("/api/settings")
def api_settings_save():
    okay, msg = save_settings(request.json or {})
    return jsonify({"ok": okay, "message" if okay else "error": msg,
                    "settings": settings_payload()}), (200 if okay else 400)


@app.get("/api/layout-preview/<int:family>")
def api_layout_preview(family: int):
    if family not in LAYOUT_FAMILIES:
        return jsonify({"ok": False, "error": "沒有這個色系"}), 404
    png = layout_preview(family)
    if png is None:
        return jsonify({"ok": False, "error": "抽不出預覽圖（母片缺背景圖？）"}), 500
    from io import BytesIO

    return send_file(BytesIO(png), mimetype="image/png",
                     download_name=f"layout{family}.png")


@app.get("/favicon.ico")
def favicon():
    # 省掉 404 雜訊；1x1 透明 PNG
    import base64
    from io import BytesIO

    px = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    return send_file(BytesIO(px), mimetype="image/png")



@app.get("/api/pipeline")
def api_pipeline():
    return jsonify(pipeline_state())


@app.post("/api/run/<stage>")
def api_run(stage: str):
    if stage not in RUNNABLE:
        return jsonify({"ok": False, "error": f"不認得的階段：{stage}"}), 400
    script, args = RUNNABLE[stage]
    step = run_stage(script, *args)
    return jsonify({"ok": step["ok"], "steps": [step], "pipeline": pipeline_state()})


@app.get("/api/download/<path:name>")
def api_download(name: str):
    # 只允許取 output/ 底下的檔案，擋掉 ../ 這種路徑
    target = (OUTPUT / name).resolve()
    if not str(target).startswith(str(OUTPUT.resolve())) or not target.is_file():
        return jsonify({"ok": False, "error": "找不到檔案"}), 404
    return send_file(str(target), as_attachment=True, download_name=target.name)


@app.get("/api/ocr-report")
def api_ocr_report():
    p = RAW / "ocr_confidence.md"
    if not p.exists():
        return jsonify({"ok": False, "error": "沒有 OCR 報告（這本書有文字層，沒走 OCR）"}), 404
    return jsonify({"ok": True, "markdown": p.read_text(encoding="utf-8")})


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="控制台（Stage 1–8）")
    ap.add_argument("--host", default="127.0.0.1",
                    help="預設只綁本機；要讓別台電腦連才改 0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        print(f"\n  ⚠  綁在 {args.host}，同網段的人都連得到。"
              "這頁沒有身分驗證，書檔有版權，請確認網段安全。\n")
    print(f"  控制台 → http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}")
    print("  深讀與研究那兩段，頁面會給你一句指令貼到 Claude 對話視窗\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
