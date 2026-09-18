# ===========================================================================
# 復華風格「專業書分享」簡報自動化 pipeline
#   make setup    建虛擬環境、裝套件、檢查母片與外部工具
#   make check    只檢查環境（不安裝）
#   make web      開控制台（設定→上傳→深讀→產出→品管）http://127.0.0.1:5000
#   make extract  Stage 1   BOOK=input/book.pdf
#   make split    Stage 2   → 停：人工確認章節清單
#   make digest   Stage 3   逐章深讀（Claude Code 驅動）
#   make research Stage 4   外部研究（Claude Code 驅動）
#   make outline  Stage 5   產藍圖 work/05_deck.json
#   make build    Stage 6+7 產 PPTX + 逐字稿 DOCX
#   make qa       Stage 8   自動品管
#   make revise   改稿迴圈：改完 deck.json 後重跑 6→8
# ===========================================================================

PY      := .venv/bin/python
PIP     := .venv/bin/pip
BOOK    ?= $(firstword $(wildcard input/book.* input/*.pdf input/*.epub input/*.mobi))

.DEFAULT_GOAL := help
.PHONY: help setup check web extract split digest research outline build pptx script qa \
        revise preview check-sources clean-work clean-output distclean

help:
	@grep -E '^#   make' Makefile | sed 's/^#   /  /'

# --- Stage 0 --------------------------------------------------------------
setup:
	@test -d .venv || python3 -m venv .venv
	@$(PIP) install --upgrade pip -q
	@$(PIP) install -q -r requirements.txt
	@mkdir -p assets config input work/01_raw work/02_chapters work/03_digest \
	          work/04_evidence output/preview output/charts
	@$(MAKE) --no-print-directory check

check:
	@$(PY) scripts/08_qa.py --check-env

# --- 控制台 --------------------------------------------------------------
PORT ?= 5000
web:
	$(PY) web/app.py --port $(PORT)

# --- Stage 1–2 ------------------------------------------------------------
extract:
	@test -n "$(BOOK)" || { echo "✗ input/ 沒有書檔。放一份 book.pdf / book.epub 進去再跑。"; exit 1; }
	$(PY) scripts/01_extract.py --input "$(BOOK)"

split:
	$(PY) scripts/02_split_chapters.py
	@echo ""
	@echo "→ 停：請人工確認上面的章節清單表格，字數異常(紅字)代表拆錯了。"

# --- Stage 3–4（Claude Code 驅動）----------------------------------------
digest:
	$(PY) scripts/03_digest.py --status

research:
	$(PY) scripts/04_research.py --status

check-sources:
	$(PY) scripts/08_qa.py --check-sources

# --- Stage 5 --------------------------------------------------------------
outline:
	$(PY) scripts/05_outline.py
	@echo ""
	@echo "→ 停：直接讀 work/05_deck.json 改字，這是最省時的修改點。"

# --- Stage 6–7 ------------------------------------------------------------
build: pptx script

pptx:
	$(PY) scripts/06_build_pptx.py

script:
	$(PY) scripts/07_build_script.py

# --- Stage 8 --------------------------------------------------------------
qa:
	$(PY) scripts/08_qa.py --all

preview:
	$(PY) scripts/08_qa.py --preview

# 改稿迴圈：改完 work/05_deck.json 之後跑這個，不要重跑前面的階段
revise: build qa

# --- 清理 -----------------------------------------------------------------
clean-work:
	rm -rf work/01_raw/* work/02_chapters/* work/03_digest/* work/04_evidence/* \
	       work/05_deck.json work/06_script.json
	@for d in work/01_raw work/02_chapters work/03_digest work/04_evidence; do touch $$d/.gitkeep; done

clean-output:
	rm -rf output/*.pptx output/*.docx output/*.pdf output/*.md output/preview/* output/charts/*
	@for d in output output/preview output/charts; do touch $$d/.gitkeep; done

distclean: clean-work clean-output
	rm -rf .venv
