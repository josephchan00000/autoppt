#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改完 deck.minutes 之後，重新分配 work/05_deck.json 每一頁的 duration_sec。

為什麼不直接重跑 05_outline.py：那會從 digest/evidence 重新生成藍圖，
把已經潤飾好的文案全部洗掉。這支只動 duration_sec，其餘欄位一律不碰。

    python tools/repace_deck.py                 # 依 config 的 deck.minutes 重配
    python tools/repace_deck.py --minutes 90    # 順便把 minutes 寫回 config
    python tools/repace_deck.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _common import (  # noqa: E402
    DECK_JSON, PROJECT_FILE, die, format_timecode, info, ok, read_json, step,
    talk_minutes_range, target_slides, warn, write_json,
)


def set_minutes(m: int) -> None:
    """寫回 config/project.yaml，並把推算欄位清成 null。用 ruamel 保留註解。"""
    from io import StringIO

    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    cfg = y.load(PROJECT_FILE.read_text(encoding="utf-8")) or {}
    cfg.setdefault("deck", {})["minutes"] = m
    cfg["deck"]["target_slides"] = None
    cfg.setdefault("narration", {})["total_minutes_range"] = None
    buf = StringIO()
    y.dump(cfg, buf)
    PROJECT_FILE.write_text(buf.getvalue(), encoding="utf-8")

    import _common

    _common._project_cache = None


def main() -> int:
    ap = argparse.ArgumentParser(description="重新分配 deck.json 的 duration_sec")
    ap.add_argument("--minutes", type=int, default=0,
                    help="順便把 deck.minutes 改成這個值再重配")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DECK_JSON.exists():
        die(f"找不到 {DECK_JSON}")
    if args.minutes:
        if not (10 <= args.minutes <= 240):
            die("--minutes 請填 10–240")
        if not args.dry_run:
            set_minutes(args.minutes)

    deck = read_json(DECK_JSON)
    slides = deck.get("slides", [])
    if not slides:
        die("deck.json 沒有 slides")

    lo_m, hi_m = talk_minutes_range()
    target_sec = int(((lo_m + hi_m) / 2) * 60)

    # 影片頁的秒數是實際播放長度，不參與縮放（與 05_outline.assign_durations 同邏輯）
    fixed = [s for s in slides if s.get("kind") == "video"]
    flex = [s for s in slides if s.get("kind") != "video"]
    fixed_sec = sum(int(s.get("duration_sec", 0)) for s in fixed)
    cur_flex = sum(int(s.get("duration_sec", 0)) for s in flex)

    before = fixed_sec + cur_flex
    step(f"重新配速（{len(slides)} 頁）")
    info(f"目前 {format_timecode(before)} → 目標 {lo_m}–{hi_m} 分"
         f"（取中間值 {format_timecode(target_sec)}）")
    if fixed:
        info(f"其中影片 {format_timecode(fixed_sec)} 不參與縮放")

    budget = target_sec - fixed_sec
    if cur_flex <= 0 or not flex:
        die("沒有可調整的頁面")
    if budget < cur_flex * 0.35:
        warn("影片佔掉太多時間，剩給講述的不足。考慮減少影片或再拉長 minutes。")
        budget = int(cur_flex * 0.35)

    scale = budget / cur_flex
    for s in flex:
        s["duration_sec"] = max(20, int(round(int(s.get("duration_sec", 60)) * scale / 5) * 5))

    after = sum(int(s.get("duration_sec", 0)) for s in slides)
    lo_p, hi_p = target_slides()

    print()
    info(f"新總時長 {format_timecode(after)}（{after / len(slides):.0f} 秒/頁）")
    if lo_p <= len(slides) <= hi_p:
        ok(f"{len(slides)} 頁落在目標 {lo_p}–{hi_p} 頁區間內")
    else:
        warn(f"{len(slides)} 頁仍不在目標 {lo_p}–{hi_p} 頁區間")

    if args.dry_run:
        info("--dry-run：未寫檔")
        return 0

    write_json(DECK_JSON, deck)
    ok(f"已寫回 {DECK_JSON}")
    print()
    info("下一步：寫逐字稿（依 prompts/narration.md），再跑 06/07/08")
    return 0


if __name__ == "__main__":
    sys.exit(main())
