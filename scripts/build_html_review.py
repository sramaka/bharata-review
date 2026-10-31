import os
import re
import glob
import json
import base64
import hashlib
import argparse

PAGE_IMAGES = "page_images"
RAW_DIR = "output/raw"
# Pages saved by the scholar; when present they are shown instead of the raw OCR
VERIFIED_DIR = "output/verified"

# Deployed site: index.html at the repo root loads page scans from WEB_IMAGE_DIR on demand
SITE_HTML = "index.html"

# Words flagged for the scholar's review, keyed by PDF page ("016": [{section, match, suggest, kind, note}])
REVIEW_FLAGS_JSON = "output/review_flags.json"
WEB_IMAGE_DIR = "page_web"
WEB_IMAGE_WIDTH = 1600
WEB_JPEG_QUALITY = 80

# Optional single-file offline copy with all scans embedded (--standalone)
STANDALONE_HTML = "output/proofread_bundle.html"

# Paste your deployed Google Apps Script Web App URL here
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxrgtnxcAj0Z7skBCbaAeAEwwEpKUBXN9bzMuUq7LbdZbVOQaeEf30jL9DVUV476Bg/exec"

DEVANAGARI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")

# Printed book page = PDF page - BOOK_PAGE_OFFSET (book page 1 is PDF page 15)
BOOK_PAGE_OFFSET = 14

# Parva ranges in printed book pages, from the Contents (PDF page 13)
PARVAS = [
    (1, 18, "आदिपर्व"), (19, 29, "सभापर्व"), (30, 41, "वनपर्व"), (42, 53, "विराटपर्व"),
    (54, 69, "उद्योगपर्व"), (70, 78, "भीष्मपर्व"), (79, 94, "द्रोणपर्व"), (95, 103, "कर्णपर्व"),
    (104, 109, "शल्यपर्व"), (110, 112, "सौप्तिकपर्व"), (113, 117, "स्त्रीपर्व"), (118, 123, "शान्तिपर्व"),
    (124, 125, "अनुशासनपर्व"), (126, 129, "अश्वमेधपर्व"), (130, 132, "आश्रमवासपर्व"), (133, 135, "मौसलपर्व"),
    (136, 138, "महाप्रस्थानपर्व"), (139, 141, "स्वर्गारोहणपर्व"), (142, 143, "भगवद्दण्डकः"),
]

# Front matter by PDF page: (section label, printed page number, language)
FRONT_MATTER = {
    7: ("प्रस्तावना (Foreword)", "iii", "en"),
    8: ("प्रस्तावना (Foreword)", "iv", "en"),
    9: ("प्रस्तावना (Foreword)", "v", "en"),
    10: ("प्रस्तावना (Foreword)", "vi", "en"),
    11: ("प्रस्तावना (Foreword)", "vii", "en"),
    12: ("ग्रन्थकर्तुः कृतयः (Works)", "", "en"),
    13: ("विषयसूची (Contents)", "", "sa"),
}

def page_metadata(pdf_page):
    """Return section label, printed page number and language for a PDF page."""
    if pdf_page in FRONT_MATTER:
        section, printed, lang = FRONT_MATTER[pdf_page]
        return {"section": section, "book_page": printed, "lang": lang, "front": True}
    book_page = pdf_page - BOOK_PAGE_OFFSET
    section = next((name for lo, hi, name in PARVAS if lo <= book_page <= hi), "")
    return {"section": section, "book_page": to_devanagari_num(book_page) if book_page > 0 else "", "lang": "sa", "front": False}

def ensure_web_image(p_num):
    """Return the web JPEG path for a page, regenerating it from the 300 DPI PNG when that is newer."""
    png_path = os.path.join(PAGE_IMAGES, f"page_{p_num}.png")
    jpg_path = os.path.join(WEB_IMAGE_DIR, f"page_{p_num}.jpg")
    if os.path.exists(png_path) and (not os.path.exists(jpg_path) or os.path.getmtime(jpg_path) < os.path.getmtime(png_path)):
        import pymupdf  # only needed when (re)generating images
        pix = pymupdf.Pixmap(png_path)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.colorspace and pix.colorspace.n > 1:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
        if pix.width > WEB_IMAGE_WIDTH:
            pix = pymupdf.Pixmap(pix, WEB_IMAGE_WIDTH, round(pix.height * WEB_IMAGE_WIDTH / pix.width), None)
        os.makedirs(WEB_IMAGE_DIR, exist_ok=True)
        with open(jpg_path, "wb") as f:
            f.write(pix.tobytes("jpg", jpg_quality=WEB_JPEG_QUALITY))
        print(f"  └─ Web image: {jpg_path}")
    return jpg_path if os.path.exists(jpg_path) else None

def to_devanagari_num(num_str):
    return str(num_str).translate(DEVANAGARI_DIGITS)

def clean_inline(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.*?)`', r'<span class="apparatus-badge">\1</span>', text)
    return text

def build_table(rows):
    if len(rows) < 2:
        return ""
    table_html = ["<div class='table-responsive'><table class='scholarly-table'>"]
    header = rows[0]
    headers = [c.strip() for c in header.strip('|').split('|')]
    table_html.append("<thead><tr>" + "".join(f"<th>{clean_inline(h)}</th>" for h in headers) + "</tr></thead><tbody>")

    start_idx = 2 if re.match(r'^[|\s\-:]+$', rows[1]) else 1
    for r in rows[start_idx:]:
        cells = [c.strip() for c in r.strip('|').split('|')]
        table_html.append("<tr>" + "".join(f"<td>{clean_inline(c)}</td>" for c in cells) + "</tr>")
    table_html.append("</tbody></table></div>")
    return "\n".join(table_html)

CORRECTION_CATEGORY_BY_BADGE = {
    "🔍 OCR-दोषः": "ocr",
    "⚠️ मुद्रणदोषः": "misprint",
    "✂️ पदच्छेददोषः": "pada",
    "✏️ अन्यत्": "other",
}
CORRECTION_SECTION_BY_LABEL = {"मूलपाठः": "sec1", "पदच्छेदः": "sec2"}
PADA_STATUS_BY_LABEL = {"✔ अद्यतितः": "updated", "✔ यथावत्": "confirmed", "⚠ अद्यतनीयः": "stale"}

def parse_correction_log(md_text):
    """Rows of the '४. संशोधनलेखः (Correction Log)' table written by the portal on save."""
    lines = md_text.splitlines()
    start = next((i for i, l in enumerate(lines) if "४. संशोधनलेख" in l), None)
    if start is None:
        return []
    unescape = lambda t: "" if t.strip() == "∅" else t.strip().replace(" ↵ ", "\n")
    rows = []
    for line in lines[start + 1:]:
        s = line.strip()
        if s.startswith("## "):
            break
        if not (s.startswith("|") and s.endswith("|")) or re.match(r"^\|[\s\-:|]+\|$", s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 8 or cells[0] == "सङ्ख्या":
            continue
        rows.append({
            "n": int(cells[0].translate(str.maketrans("०१२३४५६७८९", "0123456789")) or 0),
            "section": CORRECTION_SECTION_BY_LABEL.get(cells[1], cells[1]),
            "category": CORRECTION_CATEGORY_BY_BADGE.get(cells[2], "other"),
            "before": unescape(cells[3]),
            "after": unescape(cells[4]),
            "context": cells[5],
            "source": "ai" if cells[6].startswith("AI") else "reviewer",
            "note": cells[7],
            "pada": PADA_STATUS_BY_LABEL.get(cells[8], "") if len(cells) > 8 else "",
        })
    return rows

def parse_review_marks(md_text):
    """Rows of the '५. समीक्षाचिह्नानि (Marked for Review)' table written by the portal on save."""
    lines = md_text.splitlines()
    start = next((i for i, l in enumerate(lines) if "५. समीक्षाचिह्न" in l), None)
    if start is None:
        return []
    marks = []
    for line in lines[start + 1:]:
        s = line.strip()
        if s.startswith("## "):
            break
        if not (s.startswith("|") and s.endswith("|")) or re.match(r"^\|[\s\-:|]+\|$", s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 6 or cells[0] == "सङ्ख्या":
            continue
        marks.append({
            "section": CORRECTION_SECTION_BY_LABEL.get(cells[1], cells[1]),
            "match": cells[2].replace(" ↵ ", "\n"),
            "occurrence": int(cells[3].translate(str.maketrans("०१२३४५६७८९", "0123456789")) or 1),
            "target": "askai" if cells[4].startswith("AI") else "mine",
            "note": cells[5],
        })
    return marks

def parse_sections(raw_md):
    lines = raw_md.splitlines()
    sec1_lines = []
    sec2_lines = []
    sec3_lines = []
    
    current_sec = 1
    for line in lines:
        s = line.strip()
        if "२. पदच्छेद" in s or "पदच्छेदसहित" in s:
            current_sec = 2
            continue
        elif "३. सम्पादन" in s or "सम्पादनटिप्पण्य" in s:
            current_sec = 3
            continue
        elif "४. संशोधनलेख" in s or "५. समीक्षाचिह्न" in s:
            # Correction log written by the portal on save; not part of the text
            current_sec = 4
            continue
        elif current_sec == 1 and (s.startswith("## ") or s.startswith("# ")):
            continue
        elif "१. मूलपाठ" in s:
            current_sec = 1
            continue

        if current_sec == 1:
            sec1_lines.append(line)
        elif current_sec == 2:
            sec2_lines.append(line)
        elif current_sec == 3:
            sec3_lines.append(line)

    sec1_text = "\n".join(sec1_lines).strip()
    sec2_text = "\n".join(sec2_lines).strip()
    sec3_md = "\n".join(sec3_lines).strip()

    table_rows = [l.strip() for l in sec3_lines if l.strip().startswith("|") and l.strip().endswith("|")]
    sec3_html = build_table(table_rows) if table_rows else "<p class='empty-note'><em>टिप्पणी नास्ति। (No apparatus notes)</em></p>"

    return sec1_text, sec2_text, sec3_md, sec3_html

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="sa">
<head>
<meta charset="UTF-8">
<meta name="robots" content="noindex, nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः — शोधनपुटम्</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tiro+Devanagari+Sanskrit:ital@0;1&family=Martel:wght@400;600;800&family=Sahitya:wght@400;700&family=Noto+Serif+Devanagari:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Serif:ital,wght@0,400;0,600;1,400&display=swap">
<style>
  :root {
    --font-family: 'Tiro Devanagari Sanskrit', 'Noto Serif Devanagari', serif;
    --font-size: 22px;
    --line-height: 1.75;
    --bg-header: #182232;
    --bg-header-group: #233044;
    --border-header: #334155;
    --accent-gold: #fbbf24;
    --accent-amber: #d97706;
    --accent-blue: #0284c7;
    --accent-green: #16a34a;
    --paper-bg: #faf6f0;
    --card-bg: #ffffff;
    --editor-bg: #ffffff;
    --editor-text: #0f172a;
    --panel-bg: #ffffff;
    --panel-text: #1e293b;
    --panel-muted: #64748b;
    --panel-heading: #7c2d12;
    --panel-border: #cbd5e1;
    --panel-input: #f8fafc;
    --panel-hover: #f1f5f9;
    --panel-current: #e0f2fe;
  }
  [data-theme="sepia"] {
    --paper-bg: #efe4cc;
    --card-bg: #faf3e3;
    --editor-bg: #fdf8ec;
    --editor-text: #2b2118;
    --panel-bg: #faf3e3;
    --panel-text: #3b2f22;
    --panel-muted: #7c6a55;
    --panel-heading: #7c2d12;
    --panel-border: #dccdb0;
    --panel-input: #fdf8ec;
    --panel-hover: #f1e6cf;
    --panel-current: #f3e1bd;
  }
  [data-theme="dark"] {
    --paper-bg: #111827;
    --card-bg: #1a2332;
    --editor-bg: #0f1623;
    --editor-text: #e5e7eb;
    --panel-bg: #1a2332;
    --panel-text: #e2e8f0;
    --panel-muted: #94a3b8;
    --panel-heading: #fbbf24;
    --panel-border: #334155;
    --panel-input: #0f1623;
    --panel-hover: #243045;
    --panel-current: #1e3a5f;
    color-scheme: dark;
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body {
    margin: 0;
    font-family: 'Noto Sans Devanagari', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 15px;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
    background: #0f172a;
    color: #1e293b;
  }

  /* Header & Grouped Toolbar */
  header {
    background: var(--bg-header);
    color: #f8fafc;
    padding: 8px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border-header);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
    flex-wrap: wrap;
    gap: 10px;
    z-index: 20;
  }
  .brand-area {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .app-title {
    font-family: 'Tiro Devanagari Sanskrit', 'Noto Serif Devanagari', serif;
    font-size: 19px;
    font-weight: 400;
    color: var(--accent-gold);
    letter-spacing: 0.3px;
    white-space: nowrap;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    flex: 1;
  }
  .toolbar-spacer { flex: 1; }
  .review-count {
    min-width: 92px;
    text-align: center;
    font-size: 13px;
    font-weight: 600;
    color: #fca5a5;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .review-count.done { color: #86efac; }
  @media (max-width: 1320px) { .btn-label { display: none; } }
  @media (max-width: 1240px) and (min-width: 1025px) { .brand-area { display: none; } }
  .toolbar-group {
    display: flex;
    align-items: center;
    gap: 5px;
    background: var(--bg-header-group);
    padding: 4px 6px;
    border-radius: 8px;
    border: 1px solid #334155;
    flex-wrap: wrap;
  }
  .toolbar-label {
    font-size: 13px;
    color: #94a3b8;
    padding: 0 4px;
    white-space: nowrap;
  }

  button, select, input[type="number"] {
    background: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
    padding: 6px 12px;
    min-height: 36px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    font-family: inherit;
    outline: none;
    line-height: 1.3;
  }
  button:focus-visible, select:focus-visible, input:focus-visible {
    outline: 2px solid #38bdf8;
    outline-offset: 2px;
  }
  button, select {
    cursor: pointer;
    transition: all 0.15s ease;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }
  button:hover:not(:disabled), select:hover {
    background: #475569;
    border-color: #64748b;
  }
  button:active:not(:disabled) {
    transform: translateY(1px);
  }
  button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .num-input {
    width: 60px;
    text-align: center;
    font-weight: 600;
    padding: 4px 6px;
  }

  .nav-btn { font-weight: 600; }

  .export-btn {
    background: transparent;
    border-color: #64748b;
    color: #f8fafc;
    font-weight: 600;
  }

  /* Settings drawer */
  .settings-btn { font-size: 17px; padding: 6px 10px; }
  .drawer-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.35); z-index: 90; }
  .settings-drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(380px, 100vw);
    z-index: 95;
    background: var(--panel-bg);
    color: var(--panel-text);
    border-left: 1px solid var(--panel-border);
    box-shadow: -12px 0 30px rgba(0, 0, 0, 0.3);
    display: flex;
    flex-direction: column;
  }
  .drawer-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: var(--bg-header);
    color: var(--accent-gold);
    font-weight: 600;
    font-size: 16px;
  }
  .drawer-close { background: transparent; border-color: #475569; color: #cbd5e1; }
  .drawer-body { flex: 1; overflow-y: auto; padding: 8px 16px 16px 16px; display: flex; flex-direction: column; gap: 6px; }
  .set-group { display: flex; flex-direction: column; gap: 8px; padding: 10px 0 14px 0; border-bottom: 1px solid var(--panel-border); }
  .set-group h3 { margin: 0; font-size: 14px; font-weight: 700; color: var(--panel-heading); letter-spacing: 0.2px; }
  .set-label { font-size: 13px; font-weight: 600; color: var(--panel-muted); margin-top: 4px; }
  .set-hint { font-size: 12px; color: var(--panel-muted); line-height: 1.5; }
  .set-row { display: flex; align-items: center; gap: 6px; }
  .settings-drawer select, .settings-drawer button, .settings-drawer input[type="number"] {
    background: var(--panel-input);
    color: var(--panel-text);
    border-color: var(--panel-border);
  }
  .settings-drawer button:hover:not(:disabled), .settings-drawer select:hover {
    background: var(--panel-hover);
    border-color: var(--panel-muted);
  }
  .settings-drawer .drawer-close { background: transparent; color: #cbd5e1; border-color: #475569; }
  .settings-drawer select { width: 100%; }
  .seg { display: flex; flex-wrap: wrap; gap: 0; }
  .seg button { flex: 1 1 auto; border-radius: 0; margin-left: -1px; font-size: 13px; padding: 6px 8px; }
  .seg button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
  .seg button:last-child { border-radius: 0 6px 6px 0; }
  .settings-drawer .seg button.active, .pp-filters button.active {
    background: var(--accent-blue);
    border-color: var(--accent-blue);
    color: #ffffff;
    position: relative;
  }
  .font-sample {
    font-family: var(--font-family);
    font-size: 22px;
    line-height: 1.6;
    padding: 8px 10px;
    border: 1px dashed var(--panel-border);
    border-radius: 6px;
    background: var(--editor-bg);
    color: var(--editor-text);
  }
  .set-check { display: flex; gap: 8px; align-items: flex-start; font-size: 14px; line-height: 1.5; cursor: pointer; }
  .set-check input { margin-top: 4px; }
  .menu-item { justify-content: flex-start; width: 100%; white-space: normal; text-align: left; }
  .drawer-foot { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding-top: 12px; }

  /* Page panel: pages grouped by parva */
  .page-picker { position: relative; }
  .page-btn {
    min-width: 200px;
    max-width: 300px;
    justify-content: space-between;
    gap: 8px;
    font-weight: 600;
  }
  .page-btn-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .page-btn .caret { font-size: 11px; opacity: 0.8; }
  .page-btn .pb-flags { color: #fca5a5; margin-left: 4px; }
  .page-panel {
    position: absolute;
    left: 0;
    top: calc(100% + 6px);
    z-index: 60;
    width: 420px;
    max-width: calc(100vw - 24px);
    max-height: min(72vh, 640px);
    display: flex;
    flex-direction: column;
    background: var(--panel-bg);
    color: var(--panel-text);
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    box-shadow: 0 14px 34px rgba(0, 0, 0, 0.38);
    overflow: hidden;
  }
  .pp-top { padding: 10px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--panel-border); }
  .pp-top input {
    width: 100%;
    padding: 7px 10px;
    font: inherit;
    font-size: 14px;
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    background: var(--panel-input);
    color: var(--panel-text);
  }
  .pp-filters { display: flex; gap: 6px; flex-wrap: wrap; }
  .pp-filters button {
    background: var(--panel-input);
    color: var(--panel-text);
    border-color: var(--panel-border);
    font-size: 12.5px;
    min-height: 28px;
    padding: 2px 10px;
    border-radius: 999px;
  }
  .pp-filters button:hover:not(:disabled):not(.active) { background: var(--panel-hover); }
  .pp-tree { overflow-y: auto; padding: 4px 0; flex: 1; }
  .pp-group-head, .pp-row {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    background: transparent;
    color: var(--panel-text);
    border: none;
    border-radius: 0;
    text-align: left;
    justify-content: flex-start;
    min-height: 0;
    font-weight: 400;
  }
  .pp-group-head { padding: 7px 12px; font-weight: 600; font-size: 14.5px; }
  .pp-group-head:hover:not(:disabled), .pp-row:hover:not(:disabled) { background: var(--panel-hover); border: none; }
  .pp-group-head:focus-visible, .pp-row:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: -2px; }
  .pp-group-head .pp-caret { width: 12px; font-size: 10px; color: var(--panel-muted); flex: none; }
  .pp-group-head .pp-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pp-range { font-size: 12px; font-weight: 400; color: var(--panel-muted); }
  .pp-progress { font-size: 12px; font-weight: 600; color: var(--panel-muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .pp-progress.done { color: var(--accent-green); }
  .pp-flags { font-size: 12px; font-weight: 700; color: #dc2626; white-space: nowrap; }
  .pp-bar { height: 3px; margin: -2px 12px 4px 32px; background: var(--panel-border); border-radius: 2px; overflow: hidden; }
  .pp-bar span { display: block; height: 100%; background: var(--accent-green); }
  .pp-group.empty .pp-group-head { color: var(--panel-muted); font-weight: 400; cursor: default; }
  .pp-group.empty .pp-group-head:hover { background: transparent; }
  .pp-row { padding: 5px 12px 5px 34px; font-size: 14px; }
  .pp-row .pp-status { width: 14px; flex: none; text-align: center; }
  .pp-row .pp-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pp-row .pp-pdf { font-size: 12px; color: var(--panel-muted); font-variant-numeric: tabular-nums; }
  .pp-row.saved .pp-status { color: var(--accent-green); }
  .pp-row.edited .pp-status { color: var(--accent-amber); }
  .pp-row.unreviewed .pp-status { color: var(--panel-muted); }
  .pp-row.current { background: var(--panel-current); box-shadow: inset 3px 0 0 var(--accent-blue); font-weight: 600; }
  .pp-empty { padding: 16px; color: var(--panel-muted); font-size: 14px; text-align: center; }
  .pp-foot { padding: 7px 12px; font-size: 12.5px; color: var(--panel-muted); border-top: 1px solid var(--panel-border); }

  /* Review highlights can be switched off in the settings */
  .hide-highlights mark.flag { background: transparent !important; text-decoration: none !important; }

  .save-btn {
    background: var(--accent-green);
    border-color: #15803d;
    font-weight: 600;
    color: #ffffff;
    padding: 6px 14px;
  }
  .save-btn:hover:not(:disabled) { background: #15803d; border-color: #4ade80; }

  .section-toggle {
    background: #1e293b;
    border: 1px solid #475569;
    color: #cbd5e1;
  }
  .section-toggle.active {
    background: #0369a1;
    border-color: #38bdf8;
    color: #ffffff;
    font-weight: 600;
  }

  /* Split Workspace Layout */
  .main-container {
    display: flex;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    position: relative;
  }
  .pane {
    height: 100%;
    overflow-y: auto;
    position: relative;
  }

  /* Left Scan Image Pane + Floating Zoom Controls */
  .image-pane {
    width: 48%;
    min-width: 240px;
    max-width: 82%;
    flex: 0 0 auto;
    background: #1e293b;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px;
    overflow: auto;
  }

  /* Movable Resizer Divider */
  .pane-resizer {
    width: 8px;
    flex: 0 0 8px;
    background: #0f172a;
    border-left: 1px solid #334155;
    border-right: 1px solid #cbd5e1;
    cursor: col-resize;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 15;
    user-select: none;
    transition: background 0.15s ease;
  }
  .pane-resizer:hover, .pane-resizer.dragging {
    background: #0284c7;
    border-color: #38bdf8;
  }
  .pane-resizer::after {
    content: "⋮";
    color: #94a3b8;
    font-size: 15px;
    font-weight: bold;
    line-height: 1;
    pointer-events: none;
  }
  .pane-resizer:hover::after, .pane-resizer.dragging::after {
    color: #ffffff;
  }
  body.resizing-panes {
    cursor: col-resize !important;
    user-select: none !important;
  }
  .image-controls-bar {
    position: sticky;
    top: 0;
    z-index: 10;
    background: rgba(15, 23, 42, 0.88);
    backdrop-filter: blur(6px);
    padding: 5px 12px;
    border-radius: 999px;
    border: 1px solid #334155;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  }
  .image-controls-bar button {
    padding: 3px 8px;
    font-size: 12px;
    border-radius: 999px;
    background: #1e293b;
  }
  .zoom-label {
    font-size: 12px;
    color: #cbd5e1;
    min-width: 44px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .image-wrapper {
    display: flex;
    justify-content: center;
    width: 100%;
  }
  .image-pane img {
    width: 100%;
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.55);
    transition: width 0.15s ease, max-width 0.15s ease;
    background: #ffffff;
  }

  /* Right Scholarly Text Pane */
  .text-pane {
    flex: 1 1 0%;
    min-width: 300px;
    background: var(--paper-bg);
    color: #1c1917;
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 20px 24px 40px 24px;
  }

  /* Page Action Bar inside Text Pane */
  .page-utility-bar {
    max-width: 920px;
    margin: 0 auto;
    width: 100%;
    background: #ffffff;
    border: 1px solid #e7e5e4;
    border-left: 4px solid #b45309;
    border-radius: 8px;
    padding: 10px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  }
  .page-utility-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--font-family);
    font-size: 1.2rem;
    font-weight: 400;
    color: #7c2d12;
  }
  .page-pdf-num {
    font-family: 'Noto Sans Devanagari', system-ui, sans-serif;
    font-size: 13px;
    font-weight: 500;
    color: #78716c;
  }
  .status-chip {
    font-family: 'Noto Sans Devanagari', system-ui, sans-serif;
    font-size: 13.5px;
    font-weight: 600;
    padding: 3px 12px;
    border-radius: 999px;
    border: 1px solid;
    white-space: nowrap;
  }
  .status-chip.unreviewed { color: #57534e; background: #f5f5f4; border-color: #d6d3d1; }
  .status-chip.edited { color: #92400e; background: #fffbeb; border-color: #fcd34d; }
  .status-chip.saved { color: #166534; background: #f0fdf4; border-color: #86efac; }

  .light-btn {
    background: #f8fafc;
    color: #334155;
    border: 1px solid #cbd5e1;
    padding: 6px 12px;
    font-size: 13.5px;
    font-weight: 600;
    border-radius: 6px;
  }
  .light-btn:hover:not(:disabled) {
    background: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
  }

  /* Editor Cards */
  .card-container {
    max-width: 920px;
    margin: 0 auto;
    width: 100%;
    background: var(--card-bg);
    border-radius: 10px;
    padding: 20px 24px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
    border: 1px solid #e2e8f0;
  }

  .card-header {
    font-size: 1.05em;
    font-weight: 700;
    color: #9a3412;
    border-bottom: 2px solid #fed7aa;
    padding-bottom: 8px;
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .card-header.hdr-flags { color: #991b1b; border-color: #fecaca; }
  .card-header.hdr-sec2 { color: #1e3a8a; border-color: #bfdbfe; }
  .card-header.hdr-sec3 { color: #334155; border-color: #cbd5e1; }
  .light-btn.danger-btn { color: #b91c1c; border-color: #fecaca; }
  .card-header-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .sanskrit-editor {
    width: 100%;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 16px 18px;
    font-family: var(--font-family);
    font-size: var(--font-size);
    line-height: var(--line-height);
    outline: none;
    resize: vertical;
    overflow-y: hidden;
    white-space: pre-wrap;
    background: var(--editor-bg);
    color: var(--editor-text);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .sanskrit-editor:focus {
    border-color: #0284c7;
    box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
  }

  .lang-en .sanskrit-editor { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; }
  .sanskrit-editor { overflow-wrap: break-word; }

  /* Review flags: highlights drawn on a layer behind the transparent textarea */
  .editor-wrap { position: relative; background: var(--editor-bg); border-radius: 8px; }
  .editor-wrap > textarea.sanskrit-editor { position: relative; z-index: 1; background: transparent; }
  .flag-backdrop {
    position: absolute;
    inset: 0;
    z-index: 0;
    color: transparent;
    pointer-events: none;
    overflow: hidden;
    border-color: transparent !important;
    box-shadow: none !important;
  }
  mark.flag { color: transparent; border-radius: 3px; padding: 0; text-decoration-skip-ink: none; text-underline-offset: 0.3em; }
  mark.flag-ocr { background: rgba(239, 68, 68, 0.16); text-decoration: underline wavy #dc2626; }
  mark.flag-print { background: rgba(245, 158, 11, 0.22); text-decoration: underline wavy #d97706; }
  mark.flag-mine { background: rgba(20, 184, 166, 0.16); text-decoration: underline wavy #0d9488; }
  mark.flag-askai { background: rgba(99, 102, 241, 0.15); text-decoration: underline wavy #4f46e5; }
  mark.flag-reply { background: rgba(16, 185, 129, 0.12); text-decoration: underline dotted #059669; text-decoration-thickness: 2px; }
  mark.flag-pada { background: rgba(147, 51, 234, 0.12); text-decoration: underline wavy #9333ea; }
  mark.flag-stale { background: rgba(249, 115, 22, 0.13); text-decoration: underline dashed #ea580c; text-decoration-thickness: 2px; }
  mark.flag-verify { background: rgba(59, 130, 246, 0.14); text-decoration: underline dotted #2563eb; text-decoration-thickness: 2px; }

  .flag-panel { border-left: 4px solid #dc2626; }
  .flag-legend { display: flex; gap: 10px; flex-wrap: wrap; font-size: 12.5px; font-weight: 500; color: #57534e; }
  .flag-legend span::before { content: ''; display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
  .legend-ocr::before { background: #fca5a5; }
  .legend-print::before { background: #fcd34d; }
  .legend-verify::before { background: #93c5fd; }
  .legend-pada::before { background: #d8b4fe; }
  .legend-mine::before { background: #99f6e4; }
  .legend-askai::before { background: #c7d2fe; }
  .flag-list { display: flex; flex-direction: column; gap: 8px; }
  .flag-item {
    border: 1px solid #e7e5e4;
    border-radius: 8px;
    padding: 8px 12px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px 12px;
    align-items: center;
  }
  .flag-item.resolved { opacity: 0.55; }
  .flag-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
  .flag-kind { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; white-space: nowrap; }
  .kind-ocr .flag-kind { background: #fee2e2; color: #991b1b; }
  .kind-print .flag-kind { background: #fef3c7; color: #92400e; }
  .kind-verify .flag-kind { background: #dbeafe; color: #1e40af; }
  .kind-pada .flag-kind { background: #f3e8ff; color: #6b21a8; }
  .kind-mine .flag-kind { background: #ccfbf1; color: #115e59; }
  .kind-askai .flag-kind { background: #e0e7ff; color: #3730a3; }
  .kind-reply .flag-kind { background: #d1fae5; color: #065f46; }
  .flag-item.is-mark { border-color: #99f6e4; background: #f0fdfa; }
  .flag-lost { font-size: 12px; color: #b45309; }

  /* "Mark for review" dialog */
  .mark-dialog {
    position: fixed;
    left: 50%;
    bottom: calc(24px + env(safe-area-inset-bottom, 0px));
    transform: translateX(-50%);
    z-index: 90;
    width: min(520px, calc(100vw - 32px));
    background: #ffffff;
    color: #1c1917;
    border: 1px solid #99f6e4;
    border-top: 4px solid #0d9488;
    border-radius: 10px;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.35);
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .mark-dialog-title { font-weight: 700; color: #115e59; }
  .mark-dialog-word { font-family: var(--font-family); font-size: 1.3em; color: #0f172a; }
  .mark-dialog label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 14px; }
  .mark-dialog input[type="text"] {
    min-height: 36px;
    padding: 4px 10px;
    border: 1px solid #d6d3d1;
    border-radius: 6px;
    font-family: inherit;
    font-size: 14px;
    color: #1c1917;
    background: #ffffff;
  }
  .mark-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .pada-status { width: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; }
  .pada-status.stale { color: #c2410c; }
  .pada-status.ok { color: #166534; }
  .pada-status button { min-height: 28px; padding: 2px 10px; font-size: 12.5px; }
  .flag-words { font-family: var(--font-family); font-size: 1.15em; }
  .flag-match { color: #991b1b; }
  .flag-suggest { color: #166534; }
  .flag-where { font-size: 12px; color: #78716c; }
  .flag-note { grid-column: 1 / 2; font-size: 13px; color: #44403c; line-height: 1.5; }
  .flag-actions { grid-column: 2 / 3; grid-row: 1 / span 2; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
  .flag-done { font-size: 13px; color: #166534; font-weight: 600; }

  /* Real-Time Proof Marks: sticky panel pinned to the bottom of the text pane */
  .proof-panel {
    position: sticky;
    bottom: 0;
    margin-top: auto;
    max-width: 920px;
    width: 100%;
    margin-left: auto;
    margin-right: auto;
    background: #fffbeb;
    border: 1px solid #fcd34d;
    border-top: 3px solid #d97706;
    border-radius: 10px 10px 0 0;
    box-shadow: 0 -6px 18px rgba(0, 0, 0, 0.10);
    z-index: 5;
  }
  .proof-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 8px 14px;
    font-weight: 700;
    color: #92400e;
  }
  .proof-head-actions { display: flex; gap: 6px; }
  .proof-list, .proof-full {
    max-height: 32vh;
    overflow-y: auto;
    padding: 0 14px 12px 14px;
  }
  .proof-list { display: flex; flex-direction: column; gap: 6px; }
  .change-item {
    background: #ffffff;
    border: 1px solid #fde68a;
    border-radius: 6px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .change-text {
    display: block;
    width: 100%;
    text-align: left;
    background: #ffffff;
    color: #1c1917;
    border: none;
    font-family: var(--font-family);
    font-size: calc(var(--font-size) * 0.85);
    line-height: 1.6;
    white-space: normal;
  }
  .change-text:hover:not(:disabled) { background: #fef9c3; border-color: transparent; }
  .change-text .ctx { color: #78716c; }
  .change-sec {
    font-family: 'Noto Sans Devanagari', system-ui, sans-serif;
    font-size: 12px;
    font-weight: 600;
    color: #92400e;
    margin-right: 6px;
  }
  .change-meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 0 8px 4px 8px; }
  .change-meta select, .change-meta input {
    min-height: 32px;
    padding: 3px 8px;
    font-size: 13px;
    background: #ffffff;
    color: #1c1917;
    border: 1px solid #d6d3d1;
    border-radius: 6px;
  }
  .change-meta select:hover { background: #fafaf9; border-color: #a8a29e; }
  .change-note { flex: 1; min-width: 160px; font-family: inherit; }
  .change-hint { width: 100%; font-size: 12px; color: #78716c; }
  .proof-full-label { font-size: 13px; font-weight: 600; color: #92400e; margin: 8px 0 2px 0; font-family: 'Noto Sans Devanagari', system-ui, sans-serif; white-space: normal; }
  .proof-full {
    font-family: var(--font-family);
    font-size: var(--font-size);
    line-height: var(--line-height);
    white-space: pre-wrap;
    background: #ffffff;
    margin: 0 14px 12px 14px;
    padding: 12px 14px;
    border: 1px solid #fde68a;
    border-radius: 8px;
  }
  .proof-panel ins, .proof-panel del { text-decoration: none; padding: 1px 3px; border-radius: 3px; }
  .proof-panel ins { background: #fef08a; color: #92400e; border-bottom: 2px solid #d97706; }
  .proof-panel del { background: #fee2e2; color: #991b1b; text-decoration: line-through; }

  .collapsible-section { display: none; }
  .collapsible-section.visible { display: block; }

  /* Apparatus Table Styling */
  .table-responsive {
    width: 100%;
    overflow-x: auto;
  }
  .scholarly-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 6px;
    font-size: 0.92em;
    line-height: 1.65;
    font-family: var(--font-family);
  }
  .scholarly-table th, .scholarly-table td {
    border: 1px solid #cbd5e1;
    padding: 9px 12px;
    text-align: left;
    vertical-align: top;
  }
  .scholarly-table th {
    background: #f1f5f9;
    color: #1e293b;
    font-weight: 700;
    white-space: nowrap;
  }
  .scholarly-table tr:nth-child(even) { background: #f8fafc; }
  .scholarly-table tr:hover { background: #f1f5f9; }
  .apparatus-badge {
    display: inline-block;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.88em;
    font-weight: 600;
    white-space: nowrap;
  }
  .empty-note {
    color: #64748b;
    margin: 6px 0;
  }

  /* Modal Dialog for Complete Book / Export */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.75);
    backdrop-filter: blur(4px);
    display: none;
    justify-content: center;
    align-items: center;
    z-index: 100;
    padding: 18px;
  }
  .modal-backdrop.open {
    display: flex;
  }
  .modal-card {
    background: #ffffff;
    color: #0f172a;
    width: 100%;
    max-width: 1020px;
    max-height: 92vh;
    border-radius: 12px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid #cbd5e1;
  }
  .modal-header {
    background: #1e293b;
    color: #f8fafc;
    padding: 14px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #334155;
  }
  .modal-title {
    font-size: 16px;
    font-weight: 700;
    color: #fde68a;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .modal-close {
    background: transparent;
    border: 1px solid #475569;
    color: #cbd5e1;
    font-size: 13.5px;
    padding: 5px 12px;
    border-radius: 6px;
  }
  .modal-toolbar {
    background: #f8fafc;
    padding: 12px 20px;
    border-bottom: 1px solid #e2e8f0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }
  .modal-options {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    font-size: 13.5px;
    color: #334155;
    font-weight: 500;
  }
  .modal-options label {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    cursor: pointer;
    user-select: none;
  }
  .modal-divider-v {
    width: 1px;
    height: 20px;
    background: #cbd5e1;
  }
  .modal-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .btn-copy-big {
    background: #0284c7;
    border-color: #0369a1;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 14px;
  }
  .btn-copy-big:hover {
    background: #0369a1;
  }
  .btn-export-light {
    background: #ffffff;
    border-color: #cbd5e1;
    color: #1e293b;
    font-weight: 600;
  }
  .btn-export-light:hover:not(:disabled) {
    background: #f1f5f9;
    border-color: #94a3b8;
  }
  .modal-body {
    padding: 20px 24px;
    flex: 1;
    overflow-y: auto;
    background: #faf6f0;
  }
  .book-preview-sheet {
    max-width: 840px;
    margin: 0 auto;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 32px 40px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
    font-family: var(--font-family);
    font-size: var(--font-size);
    line-height: var(--line-height);
    color: #0f172a;
  }
  .book-preview-sheet p {
    margin: 0 0 1em 0;
    text-align: justify;
    white-space: pre-wrap;
  }
  .book-toc {
    border: 1px solid #e7e5e4;
    border-radius: 8px;
    background: #fafaf9;
    padding: 12px 20px;
    margin-bottom: 24px;
    font-family: var(--font-family);
    line-height: 1.6;
  }
  .book-toc-title {
    font-weight: 400;
    font-size: 1em;
    color: #7c2d12;
    margin: 0 0 8px 0;
  }
  .toc-table { width: 100%; border-collapse: collapse; font-size: 0.8em; }
  .toc-table td { padding: 2px 0; border: none; }
  .toc-table a { color: #1e3a8a; text-decoration: none; }
  .toc-table a:hover { text-decoration: underline; }
  .toc-pages { text-align: right; white-space: nowrap; color: #78716c; }
  .toc-part td { color: #7c2d12; padding-top: 8px; }
  .book-part-heading, .book-section-heading {
    font-family: var(--font-family);
    font-weight: 400;
    text-align: center;
    color: #7c2d12;
  }
  .book-part-heading { font-size: 1.45em; margin: 36px 0 8px 0; }
  .book-section-heading {
    font-size: 1.3em;
    margin: 32px 0 16px 0;
    padding-bottom: 6px;
    border-bottom: 1px solid #fed7aa;
  }
  .book-page-divider {
    font-family: var(--font-family);
    font-size: 0.8em;
    font-weight: 400;
    color: #9a3412;
    background: #fff7ed;
    border: 1px solid #fed7aa;
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    margin: 14px 0 8px 0;
  }
  .book-en { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; line-height: 1.6; }
  .book-en p { text-align: left; }
  .book-preview-sheet .pada-para { text-align: left; }
  .reading-key {
    border: 1px solid #e7e5e4;
    border-radius: 8px;
    padding: 10px 18px 2px 18px;
    margin-bottom: 24px;
    font-size: 0.85em;
  }
  .reading-key-title { color: #7c2d12; margin-bottom: 6px; }
  .key-gloss { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; font-size: 0.85em; color: #57534e; }
  .book-notes-heading {
    font-family: var(--font-family);
    font-weight: 400;
    font-size: 1em;
    color: #7c2d12;
    margin: 32px 0 8px 0;
    padding-top: 12px;
    border-top: 1px solid #e7e5e4;
  }
  .book-notes-page {
    font-size: 0.75em;
    color: #9a3412;
    margin: 12px 0 4px 0;
  }
  .review-heading { color: #991b1b; }
  .opt-count { font-weight: 400; color: #64748b; }
  .book-preview-sheet p.corr-intro { font-size: 0.75em; line-height: 1.6; text-align: left; color: #57534e; }
  .corr-table { font-size: 0.75em; width: 100%; table-layout: fixed; }
  .corr-table td, .corr-table th { overflow-wrap: anywhere; }
  .book-preview-sheet p.review-item { font-size: 0.8em; line-height: 1.6; text-align: left; margin: 0 0 0.7em 0; }
  .review-num { color: #991b1b; }
  .review-where, .review-note { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; font-size: 0.8em; color: #57534e; }

  /* Toast Notification */
  /* ---- Sepia theme: warmer paper for the light surfaces ---- */
  [data-theme="sepia"] .page-utility-bar,
  [data-theme="sepia"] .change-item, [data-theme="sepia"] .change-text,
  [data-theme="sepia"] .proof-full, [data-theme="sepia"] .mark-dialog { background: var(--card-bg); }
  [data-theme="sepia"] .card-container { border-color: #e2d3b5; }
  [data-theme="sepia"] .light-btn { background: #fdf8ec; border-color: #dccdb0; color: #3b2f22; }
  [data-theme="sepia"] .light-btn:hover:not(:disabled) { background: #f1e6cf; }
  [data-theme="sepia"] .scholarly-table th { background: #f1e6cf; color: #3b2f22; }
  [data-theme="sepia"] .scholarly-table tr:nth-child(even) { background: #f7eedb; }
  [data-theme="sepia"] .scholarly-table th, [data-theme="sepia"] .scholarly-table td { border-color: #dccdb0; }

  /* ---- Dark theme ---- */
  [data-theme="dark"] body { color: #e2e8f0; }
  [data-theme="dark"] .text-pane { color: #e2e8f0; }
  [data-theme="dark"] .page-utility-bar { background: #1a2332; border-color: #334155; border-left-color: #d97706; }
  [data-theme="dark"] .page-utility-title { color: #fbbf24; }
  [data-theme="dark"] .page-pdf-num, [data-theme="dark"] .flag-where, [data-theme="dark"] .change-hint,
  [data-theme="dark"] .change-text .ctx, [data-theme="dark"] .flag-legend, [data-theme="dark"] .empty-note { color: #94a3b8; }
  [data-theme="dark"] .status-chip.unreviewed { color: #cbd5e1; background: #1e293b; border-color: #475569; }
  [data-theme="dark"] .status-chip.edited { color: #fcd34d; background: #3b2a0a; border-color: #92400e; }
  [data-theme="dark"] .status-chip.saved { color: #86efac; background: #0d2e1b; border-color: #166534; }
  [data-theme="dark"] .card-container { border-color: #334155; box-shadow: none; }
  [data-theme="dark"] .card-header { color: #fdba74; border-color: #7c2d12; }
  [data-theme="dark"] .card-header.hdr-flags { color: #fca5a5; border-color: #7f1d1d; }
  [data-theme="dark"] .card-header.hdr-sec2 { color: #93c5fd; border-color: #1e3a8a; }
  [data-theme="dark"] .card-header.hdr-sec3 { color: #cbd5e1; border-color: #475569; }
  [data-theme="dark"] .sanskrit-editor { border-color: #334155; }
  [data-theme="dark"] .light-btn { background: #243045; color: #e2e8f0; border-color: #3b4a63; }
  [data-theme="dark"] .light-btn:hover:not(:disabled) { background: #2d3b55; color: #ffffff; border-color: #64748b; }
  [data-theme="dark"] .light-btn.danger-btn { color: #fca5a5; border-color: #7f1d1d; }
  [data-theme="dark"] .flag-item { border-color: #334155; }
  [data-theme="dark"] .flag-item.is-mark { background: #0f2a2a; border-color: #115e59; }
  [data-theme="dark"] .flag-note { color: #cbd5e1; }
  [data-theme="dark"] .flag-match { color: #fca5a5; }
  [data-theme="dark"] .flag-suggest, [data-theme="dark"] .flag-done, [data-theme="dark"] .pada-status.ok { color: #86efac; }
  [data-theme="dark"] .pada-status.stale { color: #fdba74; }
  [data-theme="dark"] .mark-dialog { background: #1a2332; color: #e2e8f0; border-color: #115e59; }
  [data-theme="dark"] .mark-dialog-title { color: #5eead4; }
  [data-theme="dark"] .mark-dialog-word { color: #f1f5f9; }
  [data-theme="dark"] .mark-dialog input[type="text"] { background: #0f1623; color: #e2e8f0; border-color: #334155; }
  [data-theme="dark"] mark.flag-ocr { background: rgba(239, 68, 68, 0.28); }
  [data-theme="dark"] mark.flag-print { background: rgba(245, 158, 11, 0.3); }
  [data-theme="dark"] mark.flag-mine { background: rgba(20, 184, 166, 0.28); }
  [data-theme="dark"] mark.flag-askai { background: rgba(129, 140, 248, 0.3); }
  [data-theme="dark"] mark.flag-pada { background: rgba(168, 85, 247, 0.28); }
  [data-theme="dark"] mark.flag-stale { background: rgba(249, 115, 22, 0.26); }
  [data-theme="dark"] mark.flag-verify { background: rgba(59, 130, 246, 0.28); }
  [data-theme="dark"] .proof-panel { background: #221a0b; border-color: #78350f; border-top-color: #d97706; }
  [data-theme="dark"] .proof-head, [data-theme="dark"] .change-sec, [data-theme="dark"] .proof-full-label { color: #fcd34d; }
  [data-theme="dark"] .change-item { background: #1a2332; border-color: #78350f; }
  [data-theme="dark"] .change-text { background: #1a2332; color: #e2e8f0; }
  [data-theme="dark"] .change-text:hover:not(:disabled) { background: #2a2410; }
  [data-theme="dark"] .change-meta select, [data-theme="dark"] .change-meta input { background: #0f1623; color: #e2e8f0; border-color: #334155; }
  [data-theme="dark"] .proof-full { background: #0f1623; color: #e2e8f0; border-color: #78350f; }
  [data-theme="dark"] .proof-panel ins { background: #713f12; color: #fde68a; }
  [data-theme="dark"] .proof-panel del { background: #7f1d1d; color: #fecaca; }
  [data-theme="dark"] .scholarly-table th { background: #243045; color: #e2e8f0; }
  [data-theme="dark"] .scholarly-table tr:nth-child(even) { background: #172030; }
  [data-theme="dark"] .scholarly-table tr:hover { background: #243045; }
  [data-theme="dark"] .scholarly-table th, [data-theme="dark"] .scholarly-table td { border-color: #334155; }
  [data-theme="dark"] .apparatus-badge { background: #243045; border-color: #3b4a63; }
  [data-theme="dark"] .modal-toolbar { background: #1a2332; border-color: #334155; }
  [data-theme="dark"] .modal-options { color: #cbd5e1; }
  [data-theme="dark"] .btn-export-light { background: #243045; color: #e2e8f0; border-color: #3b4a63; }
  [data-theme="dark"] .btn-export-light:hover:not(:disabled) { background: #2d3b55; }
  [data-theme="dark"] .modal-card { background: #1a2332; border-color: #334155; }
  [data-theme="dark"] .modal-body { background: #111827; }

  .toast {
    position: fixed;
    bottom: 22px;
    right: 24px;
    background: #0f172a;
    color: #f8fafc;
    border: 1px solid #38bdf8;
    border-left: 4px solid #38bdf8;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 13.5px;
    font-weight: 500;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.35);
    z-index: 200;
    opacity: 0;
    transform: translateY(12px);
    pointer-events: none;
    transition: opacity 0.2s ease, transform 0.2s ease;
  }
  .toast.show {
    opacity: 1;
    transform: translateY(0);
  }

  @media (max-width: 1024px) {
    .main-container {
      flex-direction: column;
      height: auto;
      overflow-y: auto;
    }
    body { overflow: auto; height: auto; }
    .pane { height: auto; max-height: 75vh; width: 100% !important; max-width: 100% !important; }
    .pane-resizer { display: none; }
    .image-pane { border-right: none; border-bottom: 2px solid #0f172a; }
    .toolbar-spacer { display: none; }
  }
</style>
</head>
<body>

<header>
  <div class="brand-area">
    <div class="app-title" title="श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः — शोधनपुटम् (Proofreading Portal)">॥ भारतसङ्ग्रहः ॥</div>
  </div>

  <div class="toolbar">
    <!-- Navigation Group -->
    <div class="toolbar-group" title="पृष्ठ-सञ्चालनम् (Page Navigation — Alt + Left/Right)">
      <button id="prevBtn" class="nav-btn" onclick="prevPage()">‹ पूर्वम्</button>
      <div class="page-picker" id="pagePicker">
        <button id="pageBtn" class="page-btn" onclick="togglePagePanel()" aria-haspopup="dialog" aria-expanded="false" title="पृष्ठसूची (All pages — Alt + G)">
          <span id="pageBtnLabel" class="page-btn-label"></span><span class="caret">▾</span>
        </button>
        <div id="pagePanel" class="page-panel" role="dialog" aria-label="Pages" hidden>
          <div class="pp-top">
            <input id="pageSearch" type="search" autocomplete="off" oninput="renderPagePanel()"
                   placeholder="अन्विष्यतु (Find a page, PDF number or parva)">
            <div class="pp-filters">
              <button data-filter="all" onclick="setPageFilter('all')">सर्वाणि (All)</button>
              <button data-filter="review" onclick="setPageFilter('review')">⚑ समीक्ष्याणि (To review)</button>
              <button data-filter="unsaved" onclick="setPageFilter('unsaved')">अरक्षितानि (Unsaved)</button>
            </div>
          </div>
          <div id="pageTree" class="pp-tree" role="tree"></div>
          <div id="pageSummary" class="pp-foot"></div>
        </div>
      </div>
      <button id="nextBtn" class="nav-btn" onclick="nextPage()">परम् ›</button>
    </div>

    <!-- Review Navigation: previous / next word to review across the book -->
    <div class="toolbar-group review-nav" title="समीक्षणीयपद-सञ्चालनम् (Previous / next word to review — Alt + ↑/↓)">
      <button onclick="gotoReview(-1)" title="पूर्वं समीक्षणीयम् (Previous word to review — Alt + ↑)">‹ ⚑</button>
      <span id="reviewCount" class="review-count">⚑ ०</span>
      <button onclick="gotoReview(1)" title="अग्रिमं समीक्षणीयम् (Next word to review — Alt + ↓)">⚑ ›</button>
    </div>

    <!-- Section Visibility Group -->
    <div class="toolbar-group" title="विभाग-दर्शनम् (Toggle Sections)">
      <button id="toggleSec2" class="section-toggle" onclick="toggleSection('sec2Box', 'toggleSec2')"><span class="sign">+</span> पदच्छेदः</button>
      <button id="toggleSec3" class="section-toggle" onclick="toggleSection('sec3Box', 'toggleSec3')"><span class="sign">+</span> टिप्पणी</button>
    </div>

    <div class="toolbar-spacer"></div>

    <button class="export-btn" onclick="openAllPagesModal()" title="सम्पूर्णं ग्रन्थं पश्यतु, प्रतिकुरुत, Word / PDF वा अवतारयतु (View, Copy, or Download Complete Book in Word / PDF)">
      📖 <span class="btn-label">सम्पूर्णः ग्रन्थः</span>
    </button>

    <!-- Settings drawer -->
    <button id="settingsBtn" class="settings-btn" onclick="toggleSettings()" title="विन्यासाः (Settings)" aria-haspopup="dialog" aria-expanded="false">⚙</button>

    <!-- Save to Cloud / Server -->
    <button id="saveBtn" class="save-btn" onclick="saveVerifiedDirect()" title="संशोधितं पृष्ठं रक्षतु (Save verified page)">
      💾 रक्षतु (Save)
    </button>
  </div>
</header>

<div id="settingsOverlay" class="drawer-overlay" hidden onclick="toggleSettings(false)"></div>
<aside id="settingsMenu" class="settings-drawer" role="dialog" aria-labelledby="settingsTitle" hidden>
  <div class="drawer-head">
    <span id="settingsTitle">⚙ विन्यासाः (Settings)</span>
    <button class="drawer-close" onclick="toggleSettings(false)" title="पिदधातु (Close — Esc)">✕</button>
  </div>
  <div class="drawer-body">
    <section class="set-group">
      <h3>रूपम् (Appearance)</h3>
      <div class="set-label">वर्णयोजना (Theme)</div>
      <div class="seg" data-setting="theme">
        <button data-value="light">☀ प्रकाशः (Light)</button>
        <button data-value="sepia">📜 पत्रवर्णः (Sepia)</button>
        <button data-value="dark">🌙 अन्धकारः (Dark)</button>
        <button data-value="system">💻 यन्त्रानुसारम् (Device)</button>
      </div>
      <div class="set-label">अन्तरापृष्ठभाषा (Interface language)</div>
      <div class="seg" data-setting="uiLang">
        <button data-value="both" class="no-i18n">संस्कृतम् + English</button>
        <button data-value="sa" class="no-i18n">संस्कृतम्</button>
        <button data-value="en" class="no-i18n">English</button>
      </div>
      <div class="set-hint">मेनू-बटन-सूचनानां भाषा, ग्रन्थपाठस्य न (For menus, buttons and messages, not the book text)</div>
    </section>

    <section class="set-group">
      <h3>पाठः (Text)</h3>
      <div class="set-label">लिपिः (Devanagari font)</div>
      <select id="fontSelect" onchange="changeFont(this.value)">
        <option value="'Tiro Devanagari Sanskrit', serif">Tiro Devanagari Sanskrit</option>
        <option value="Martel, serif">Martel</option>
        <option value="Sahitya, serif">Sahitya</option>
        <option value="'Noto Serif Devanagari', serif">Noto Serif Devanagari</option>
        <option value="Siddhanta, serif">Siddhanta</option>
      </select>
      <div id="fontSample" class="font-sample no-i18n">धृतराष्ट्रः पाण्डुश्च विदुरश्चेति त्रयः पुत्राः ॥</div>
      <div class="set-label">अक्षराकारः (Text size)</div>
      <div class="set-row">
        <button onclick="stepFontSize(-2)" title="अक्षराकारं न्यूनीकरोतु (Smaller text)">A−</button>
        <input type="number" id="fontSizeInput" class="num-input" value="22" min="14" max="48" onchange="setFontSizeNumber(this.value)">
        <button onclick="stepFontSize(2)" title="अक्षराकारं वर्धयतु (Larger text)">A+</button>
      </div>
      <div class="set-label">पङ्क्त्यन्तरम् (Line spacing)</div>
      <div class="seg" data-setting="lineHeight">
        <button data-value="1.55">सङ्क्षिप्तम् (Compact)</button>
        <button data-value="1.75">सामान्यम् (Normal)</button>
        <button data-value="2">विस्तृतम् (Relaxed)</button>
      </div>
    </section>

    <section class="set-group">
      <h3>समीक्षा (Review)</h3>
      <label class="set-check"><input type="checkbox" id="optHighlights" onchange="setSetting('highlights', this.checked)">
        समीक्षणीयपदानि पाठे वर्णैः दर्शयतु (Highlight words to review in the text)</label>
      <label class="set-check"><input type="checkbox" id="optRememberPage" onchange="setSetting('rememberPage', this.checked)">
        अन्तिमं दृष्टं पृष्ठं पुनः उद्घाटयतु (Reopen the page I was last on)</label>
    </section>

    <section class="set-group">
      <h3>अस्य पृष्ठस्य प्रतिकृतिः (Copy this page)</h3>
      <button class="menu-item" onclick="copySectionText('sec1')">📋 मूलपाठं प्रतिकुरुत (Copy page text)</button>
      <button class="menu-item" onclick="copyCurrentPageFormatted()">📑 सम्पूर्णं पृष्ठं प्रतिकुरुत (Copy page with notes)</button>
    </section>

    <div class="drawer-foot">
      <button class="light-btn" onclick="resetSettings()">↺ मूलविन्यासाः (Reset to defaults)</button>
      <span class="set-hint">अस्मिन् ब्राउज़रे रक्ष्यन्ते (Remembered in this browser)</span>
    </div>
  </div>
</aside>

<div class="main-container">
  <!-- Left Scan Image Pane -->
  <div class="pane image-pane" id="imagePane">
    <div class="image-controls-bar">
      <button onclick="adjustImageZoom(-15)" title="Zoom Out">🔍−</button>
      <span id="zoomLabel" class="zoom-label">100%</span>
      <button onclick="adjustImageZoom(15)" title="Zoom In">🔍+</button>
      <button onclick="resetImageZoom()" title="Fit to Pane">समप्रमाणम् (Fit)</button>
    </div>
    <div class="image-wrapper">
      <img id="pageImg" src="" alt="Scan Image">
    </div>
  </div>

  <!-- Movable Divider between Left and Right Panes -->
  <div class="pane-resizer" id="paneResizer" title="कर्षतु — विभक्तं विस्तारं परिवर्तयतु (Drag to resize panes, double-click to reset)"></div>

  <!-- Right Editable Text Pane -->
  <div class="pane text-pane" id="textPane">
    <!-- Per-Page Quick Action Bar -->
    <div class="page-utility-bar">
      <div class="page-utility-title">
        <span id="currentPageHeading"></span>
        <span id="pagePdfNum" class="page-pdf-num"></span>
      </div>
      <span id="statusChip" class="status-chip unreviewed"></span>
    </div>

    <!-- Words flagged for review on this page -->
    <div id="flagPanel" class="card-container flag-panel" hidden>
      <div class="card-header hdr-flags">
        <span id="flagTitle">⚑ समीक्षणीयानि पदानि (Words to review)</span>
        <span class="flag-legend">
          <span class="legend-ocr">पाठभेदः (differs from scan)</span>
          <span class="legend-print">मुद्रणदोषः? (possible misprint)</span>
          <span class="legend-verify">परीक्षणीयम् (please verify)</span>
          <span class="legend-pada">नवः पदच्छेदः (updated padaccheda)</span>
          <span class="legend-mine">चिह्नितम् (marked for later)</span>
          <span class="legend-askai">AI-परीक्षणाय (asked the AI)</span>
        </span>
      </div>
      <div id="flagList" class="flag-list"></div>
    </div>

    <!-- Section 1: Mulapatha -->
    <div class="card-container">
      <div class="card-header">
        <span id="sec1Label">१. मूलपाठः (Devanagari OCR Text)</span>
        <div class="card-header-right">
          <button class="light-btn" onclick="openMarkDialog('sec1')" title="चितं पदं समीक्षार्थं चिह्नयतु (Mark the selected word for review — Alt + M)">⚑ चिह्नयतु (Mark)</button>
          <button class="light-btn" onclick="copySectionText('sec1')" title="Copy Mūlapāṭha text">📋 प्रतिकुरुत (Copy)</button>
          <button id="revertBtn" class="light-btn danger-btn" style="display: none;" onclick="revertCurrentPage()" title="मूलपाठं प्रत्यानयतु (Revert edits to original OCR)">↺ पूर्ववत् (Revert)</button>
        </div>
      </div>
      <div class="editor-wrap">
        <div id="sec1Backdrop" class="sanskrit-editor flag-backdrop" aria-hidden="true"></div>
        <textarea id="sec1Editor" class="sanskrit-editor" spellcheck="false" oninput="handleEdit()"></textarea>
      </div>
    </div>

    <!-- Section 2: Padaccheda -->
    <div id="sec2Box" class="card-container collapsible-section">
      <div class="card-header hdr-sec2">
        <span>२. पदच्छेदसहितः पाठः (Sandhi-split Padaccheda)</span>
        <div class="card-header-right">
          <button class="light-btn" onclick="openMarkDialog('sec2')" title="चितं पदं समीक्षार्थं चिह्नयतु (Mark the selected word for review — Alt + M)">⚑ चिह्नयतु (Mark)</button>
          <button class="light-btn" onclick="copySectionText('sec2')" title="Copy Padaccheda text">📋 प्रतिकुरुत (Copy)</button>
        </div>
      </div>
      <div class="editor-wrap">
        <div id="sec2Backdrop" class="sanskrit-editor flag-backdrop" aria-hidden="true"></div>
        <textarea id="sec2Editor" class="sanskrit-editor" spellcheck="false" oninput="handleSec2Edit()"></textarea>
      </div>
    </div>

    <!-- Section 3: Apparatus -->
    <div id="sec3Box" class="card-container collapsible-section">
      <div class="card-header hdr-sec3">
        <span>३. सम्पादनटिप्पण्यः (Apparatus & Editorial Notes)</span>
        <div class="card-header-right">
          <button class="light-btn" onclick="copySectionText('sec3')" title="Copy Apparatus Markdown Table">📋 प्रतिकुरुत (Copy)</button>
        </div>
      </div>
      <div id="sec3Content"></div>
    </div>

    <!-- Real-Time Proof Marks (pinned to the bottom of the pane while editing) -->
    <div id="proofPanel" class="proof-panel" hidden>
      <div class="proof-head">
        <span id="proofTitle">दृष्टं शोधनम्</span>
        <div class="proof-head-actions">
          <button id="proofModeBtn" class="light-btn" onclick="toggleProofMode()">पूर्णपाठे पश्यतु (Show in full text)</button>
          <button id="proofCollapseBtn" class="light-btn" onclick="toggleProofCollapse()" title="संवृणोतु / विवृणोतु (Collapse / Expand)">▾</button>
        </div>
      </div>
      <div id="proofList" class="proof-list"></div>
      <div id="proofFull" class="proof-full" hidden></div>
    </div>
  </div>
</div>

<!-- Modal for Viewing, Copying & Downloading Complete Text Across All Pages -->
<div id="allPagesModal" class="modal-backdrop" onclick="handleBackdropClick(event)">
  <div class="modal-card">
    <div class="modal-header">
      <div class="modal-title">
        <span>📖 सम्पूर्णः ग्रन्थः — एकीकृतः पाठः (Complete Text Across All Pages)</span>
      </div>
      <button class="modal-close" onclick="closeAllPagesModal()">✕ पिदधातु (Close)</button>
    </div>
    <div class="modal-toolbar">
      <div class="modal-options">
        <label title="पृष्ठान्ते खण्डितानि पदानि संयोजयतु (Automatically join words hyphenated across page breaks)">
          <input type="checkbox" id="optMergeHyphens" checked onchange="refreshCompiledView()">
          <strong>पृष्ठसन्धि-संयोजनम् (Join Split Words)</strong>
        </label>
        <label title="प्रस्तावना, कृतयः, विषयसूची च (Include the Foreword, Works and Contents before the main text)">
          <input type="checkbox" id="optFrontMatter" checked onchange="refreshCompiledView()">
          प्रस्तावनादि (Front Matter)
        </label>
        <label title="समीक्षणीयानि पदानि चिह्नयतु (Mark the words flagged for review, with a list at the end of each section)">
          <input type="checkbox" id="optReviewFlags" checked onchange="refreshCompiledView()">
          ⚑ समीक्षणीयानि (Mark Words to Review)
        </label>
        <label title="ग्रन्थान्ते संशोधनानां सूची — मुद्रणदोषाः (Appendix listing the corrections made: misprints in the book)">
          <input type="checkbox" id="optCorrections" checked onchange="syncCorrectionOptions(); refreshCompiledView()">
          ✎ संशोधनसूची (List of Corrections) <span id="corrCount" class="opt-count"></span>
        </label>
        <label title="OCR-दोषाः पदच्छेददोषाः च अपि (Also list OCR misreadings and padaccheda corrections)">
          <input type="checkbox" id="optAllCorrections" onchange="refreshCompiledView()">
          + OCR, पदच्छेदः (Include OCR &amp; Padaccheda Fixes)
        </label>
        <label title="पृष्ठसङ्ख्याः दर्शयतु (Show page number headers)">
          <input type="checkbox" id="optShowPageNums" onchange="refreshCompiledView()">
          पृष्ठसङ्ख्याः (Page Numbers)
        </label>
        <span class="modal-divider-v"></span>
        <label>
          <input type="checkbox" id="incSec1" checked onchange="refreshCompiledView()">
          १. मूलपाठः
        </label>
        <label>
          <input type="checkbox" id="incSec2" onchange="refreshCompiledView()">
          २. पदच्छेदः
        </label>
        <label>
          <input type="checkbox" id="incSec3" onchange="refreshCompiledView()">
          ३. टिप्पणी
        </label>
      </div>
      <div class="modal-actions">
        <button class="btn-copy-big" onclick="copyCompiledBook()" title="Word, Google Docs, Email आदौ स्थापयितुं पाठं प्रतिकुरुत (Copy clean text for Word, Google Docs, or Email)">
          📋 पाठं प्रतिकुरुत (Copy Text)
        </button>
        <button class="btn-export-light" onclick="downloadWordDoc()" title="Microsoft Word (.docx) सञ्चिकां अवतारयतु (Download Word Document)">
          📘 Word (.docx)
        </button>
        <button class="btn-export-light" onclick="printOrSavePdf()" title="PDF रूपेण रक्षतु अथवा मुद्रयतु (Save as PDF or Print)">
          🖨️ PDF / मुद्रणम्
        </button>
        <button class="btn-export-light" onclick="downloadCompiledMarkdown()" title="Markdown सञ्चिकां अवतारयतु (Download as a Markdown .md file)">
          ⬇ .md
        </button>
      </div>
    </div>
    <div class="modal-body">
      <div id="bookPreviewSheet" class="book-preview-sheet"></div>
    </div>
  </div>
</div>

<!-- Mark a word for review later -->
<div id="markDialog" class="mark-dialog" role="dialog" aria-labelledby="markDialogTitle" hidden>
  <div id="markDialogTitle" class="mark-dialog-title">⚑ समीक्षार्थं चिह्नयतु (Mark for review)</div>
  <div id="markWord" class="mark-dialog-word"></div>
  <label><input type="radio" name="markTarget" value="mine" checked> मया पश्चात् (Me, later)</label>
  <label><input type="radio" name="markTarget" value="askai"> AI-परीक्षणाय (Ask the AI to check)</label>
  <input id="markNote" type="text" placeholder="टिप्पणी (optional note, e.g. unsure of the conjunct)">
  <div class="mark-dialog-actions">
    <button class="light-btn" onclick="closeMarkDialog()">निवर्तताम् (Cancel)</button>
    <button class="save-btn" onclick="saveMark()">⚑ चिह्नयतु (Mark)</button>
  </div>
</div>

<!-- Toast Feedback -->
<div id="toast" class="toast"></div>

<script>
  const APPS_SCRIPT_URL = "<!-- APPS_SCRIPT_URL_PLACEHOLDER -->";
  const data = <!-- JSON_DATA_PLACEHOLDER -->;
  let currentIndex = 0;
  let currentZoom = 100;

  const PARVA_LIST = <!-- PARVAS_PLACEHOLDER -->;
  const pagePicker = document.getElementById('pagePicker');
  const pageBtn = document.getElementById('pageBtn');
  const pageBtnLabel = document.getElementById('pageBtnLabel');
  const pagePanel = document.getElementById('pagePanel');
  const pageSearch = document.getElementById('pageSearch');
  const pageTree = document.getElementById('pageTree');
  const pageSummary = document.getElementById('pageSummary');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const currentPageHeading = document.getElementById('currentPageHeading');
  const sec1Backdrop = document.getElementById('sec1Backdrop');
  const sec2Backdrop = document.getElementById('sec2Backdrop');
  const flagPanel = document.getElementById('flagPanel');
  const reviewCount = document.getElementById('reviewCount');
  const markDialog = document.getElementById('markDialog');
  const markWord = document.getElementById('markWord');
  const markNote = document.getElementById('markNote');
  const flagTitle = document.getElementById('flagTitle');
  const flagList = document.getElementById('flagList');
  const pagePdfNum = document.getElementById('pagePdfNum');
  const statusChip = document.getElementById('statusChip');
  const textPane = document.getElementById('textPane');
  const sec1Label = document.getElementById('sec1Label');
  const toggleSec2Btn = document.getElementById('toggleSec2');
  const settingsOverlay = document.getElementById('settingsOverlay');
  const fontSelect = document.getElementById('fontSelect');
  const settingsBtn = document.getElementById('settingsBtn');
  const settingsMenu = document.getElementById('settingsMenu');
  const proofPanel = document.getElementById('proofPanel');
  const proofTitle = document.getElementById('proofTitle');
  const proofList = document.getElementById('proofList');
  const proofFull = document.getElementById('proofFull');
  const proofModeBtn = document.getElementById('proofModeBtn');
  const proofCollapseBtn = document.getElementById('proofCollapseBtn');
  const sec1Editor = document.getElementById('sec1Editor');
  const sec2Editor = document.getElementById('sec2Editor');
  const sec3Content = document.getElementById('sec3Content');
  const pageImg = document.getElementById('pageImg');
  const fontSizeInput = document.getElementById('fontSizeInput');
  const revertBtn = document.getElementById('revertBtn');
  const saveBtn = document.getElementById('saveBtn');
  const zoomLabel = document.getElementById('zoomLabel');
  const allPagesModal = document.getElementById('allPagesModal');
  const bookPreviewSheet = document.getElementById('bookPreviewSheet');
  const toastEl = document.getElementById('toast');

  const DEV_DIGITS = ['०','१','२','३','४','५','६','७','८','९'];
  function toDevanagariDigits(str) {
    return String(str).replace(/[0-9]/g, d => DEV_DIGITS[parseInt(d, 10)]);
  }

  let toastTimer = null;
  function showToast(msg) {
    toastEl.innerText = msg;
    toastEl.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.classList.remove('show');
    }, msg.length > 60 ? 4500 : 2400);
  }

  function autoResize(textarea) {
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = Math.max(120, textarea.scrollHeight + 8) + 'px';
  }

  /* Page labels: "आदिपर्व · पृ. ३" for the main text, section name (+ printed numeral) for front matter */
  function pageLabel(item) {
    const parts = [];
    if (item.section) parts.push(item.section);
    if (item.book_page) parts.push(item.lang === 'en' ? item.book_page : `पृ. ${item.book_page}`);
    return parts.length ? parts.join(' · ') : `पृष्ठम् ${toDevanagariDigits(item.page)}`;
  }

  const STATUS_TEXT = {
    unreviewed: '○ अपरीक्षितम् (Not yet saved)',
    edited: '● संशोधितम्, अरक्षितम् (Edited — not saved)',
    saved: '✔ रक्षितम् (Saved)'
  };
  const STATUS_MARK = { unreviewed: '', edited: '● ', saved: '✔ ' };

  function pageStatus(item) {
    if (item.baseline === undefined) return 'unreviewed';
    const changed = item.sec1 !== item.baseline || item.sec2 !== item.sec2Baseline || (item.marks || []).length > 0;
    if (item.savedSnapshot !== undefined) {
      return buildSavedMarkdown(item).content === item.savedSnapshot ? 'saved' : 'edited';
    }
    return changed ? 'edited' : 'unreviewed';
  }

  function refreshPageOption(idx) {
    if (idx === currentIndex) updatePageButton();
    if (!pagePanel.hidden) renderPagePanel();
  }

  function updatePageButton() {
    const item = data[currentIndex];
    const open = reviewTargets(currentIndex).length;
    pageBtnLabel.innerHTML = `${STATUS_MARK[pageStatus(item)]}${escapeHtml(pageLabel(item))}` +
      (open ? `<span class="pb-flags">⚑${toDevanagariDigits(open)}</span>` : '');
  }

  /* ---------- Page panel: the book's pages grouped by parva ----------
     Front matter first, then every parva from the Contents. Parvas with no transcribed pages
     yet are shown greyed out, so the panel doubles as a map of the whole book. */
  let pageFilter = 'all';
  let openGroups = null;     // keys of expanded groups; null until the panel is first opened

  function pageGroups() {
    const idxs = data.map((_, i) => i);
    const groups = [];
    const front = idxs.filter(i => data[i].front);
    if (front.length) groups.push({ key: 'front', name: 'आमुखभागः (Front matter)', pages: front });
    const parvaNames = new Set(PARVA_LIST.map(p => p.name));
    PARVA_LIST.forEach(p => groups.push({
      key: p.name,
      name: p.name,
      range: `पृ. ${toDevanagariDigits(p.from)}–${toDevanagariDigits(p.to)}`,
      total: p.to - p.from + 1,
      pages: idxs.filter(i => !data[i].front && data[i].section === p.name)
    }));
    const rest = idxs.filter(i => !data[i].front && !parvaNames.has(data[i].section));
    if (rest.length) groups.push({ key: 'other', name: 'अन्यानि पृष्ठानि (Other pages)', pages: rest });
    return groups;
  }

  function groupKeyOf(idx) {
    const item = data[idx];
    if (item.front) return 'front';
    return PARVA_LIST.some(p => p.name === item.section) ? item.section : 'other';
  }

  function pageMatches(idx, q) {
    if (!q) return true;
    const item = data[idx];
    const hay = [pageLabel(item), item.section || '', `PDF ${item.page}`, item.page, String(parseInt(item.page, 10)),
                 item.book_page || ''].join(' ').toLowerCase();
    return hay.includes(q) || hay.includes(toDevanagariDigits(q));
  }

  function pagePassesFilter(idx) {
    if (pageFilter === 'review') return reviewTargets(idx).length > 0;
    if (pageFilter === 'unsaved') return pageStatus(data[idx]) !== 'saved';
    return true;
  }

  function setPageFilter(filter) {
    pageFilter = filter;
    renderPagePanel();
  }

  function renderPagePanel() {
    const q = pageSearch.value.trim().toLowerCase();
    const narrowed = Boolean(q) || pageFilter !== 'all';
    pagePanel.querySelectorAll('.pp-filters button').forEach(b => b.classList.toggle('active', b.dataset.filter === pageFilter));

    const html = [];
    let savedAll = 0, reviewAll = 0;
    pageGroups().forEach(g => {
      const counts = g.pages.map(i => ({ i, status: pageStatus(data[i]), review: reviewTargets(i).length }));
      const saved = counts.filter(c => c.status === 'saved').length;
      const review = counts.reduce((n, c) => n + c.review, 0);
      savedAll += saved;
      reviewAll += review;
      const shown = counts.filter(c => pageMatches(c.i, q) && pagePassesFilter(c.i));
      const nameHit = q && g.name.toLowerCase().includes(q);

      if (!g.pages.length) {
        // A parva not transcribed yet: listed for orientation only
        if (narrowed && !nameHit) return;
        html.push(`<div class="pp-group empty"><button class="pp-group-head" disabled>` +
          `<span class="pp-caret"></span><span class="pp-name">${escapeHtml(g.name)} <span class="pp-range">${g.range}</span></span>` +
          `<span class="pp-progress">अलिखितम् (not transcribed yet)</span></button></div>`);
        return;
      }
      const rows = nameHit ? counts : shown;
      if (narrowed && !rows.length) return;
      const open = narrowed || openGroups.has(g.key);
      const total = g.total || g.pages.length;
      html.push(`<div class="pp-group" role="group">` +
        `<button class="pp-group-head" data-group="${escapeHtml(g.key)}" aria-expanded="${open}" onclick="togglePageGroup(this.dataset.group)">` +
        `<span class="pp-caret">${open ? '▾' : '▸'}</span>` +
        `<span class="pp-name">${escapeHtml(g.name)}${g.range ? ` <span class="pp-range">${g.range}</span>` : ''}</span>` +
        (review ? `<span class="pp-flags">⚑${toDevanagariDigits(review)}</span>` : '') +
        `<span class="pp-progress${saved === g.pages.length ? ' done' : ''}" title="रक्षितानि / लिखितानि${g.total ? ' / सर्वाणि' : ''} (Saved / transcribed${g.total ? ' / pages in the parva' : ''})">` +
        `✔ ${toDevanagariDigits(saved)}/${toDevanagariDigits(g.pages.length)}${g.total && g.total !== g.pages.length ? ` · ${toDevanagariDigits(total)}` : ''}</span>` +
        `</button>` +
        `<div class="pp-bar"><span style="width: ${(100 * saved / total).toFixed(1)}%"></span></div>`);
      if (open) {
        rows.forEach(c => {
          const item = data[c.i];
          const label = item.front ? pageLabel(item) : (item.book_page ? `पृ. ${item.book_page}` : pageLabel(item));
          html.push(`<button class="pp-row ${c.status}${c.i === currentIndex ? ' current' : ''}" role="treeitem" data-idx="${c.i}" onclick="pickPage(${c.i})">` +
            `<span class="pp-status">${STATUS_MARK[c.status].trim() || '○'}</span>` +
            `<span class="pp-label">${escapeHtml(label)}</span>` +
            (c.review ? `<span class="pp-flags">⚑${toDevanagariDigits(c.review)}</span>` : '') +
            `<span class="pp-pdf">PDF ${item.page}</span></button>`);
        });
      }
      html.push(`</div>`);
    });
    pageTree.innerHTML = html.join('') ||
      `<div class="pp-empty">न किमपि लब्धम् (No pages match)</div>`;
    pageSummary.innerText = `रक्षितानि (Saved): ${toDevanagariDigits(savedAll)} / ${toDevanagariDigits(data.length)}` +
      ` · ⚑ ${toDevanagariDigits(reviewAll)}`;
  }

  function togglePageGroup(key) {
    if (openGroups.has(key)) openGroups.delete(key); else openGroups.add(key);
    renderPagePanel();
    const head = pageTree.querySelector(`.pp-group-head[data-group="${CSS.escape(key)}"]`);
    if (head) head.focus();
  }

  function togglePagePanel(forceOpen) {
    const open = forceOpen !== undefined ? forceOpen : pagePanel.hidden;
    pagePanel.hidden = !open;
    pageBtn.setAttribute('aria-expanded', String(open));
    if (!open) return;
    if (!openGroups) openGroups = new Set();
    openGroups.add(groupKeyOf(currentIndex));
    pageSearch.value = '';
    renderPagePanel();
    const cur = pageTree.querySelector('.pp-row.current');
    if (cur) cur.scrollIntoView({ block: 'center' });
    pageSearch.focus();
  }

  function pickPage(idx) {
    togglePagePanel(false);
    if (idx !== currentIndex) switchPage(idx);
    pageBtn.focus();
  }

  // Arrow keys move through the visible groups and pages; Left / Right fold a parva
  pagePanel.addEventListener('keydown', (e) => {
    const items = [...pageTree.querySelectorAll('.pp-group-head:not(:disabled), .pp-row')];
    const at = items.indexOf(document.activeElement);
    if (e.key === 'Escape') {
      e.stopPropagation();
      togglePagePanel(false);
      pageBtn.focus();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!items.length) return;
      const next = e.key === 'ArrowDown' ? (at === -1 ? 0 : Math.min(at + 1, items.length - 1)) : at - 1;
      if (next < 0) pageSearch.focus(); else items[next].focus();
    } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && at !== -1) {
      const el = items[at];
      const head = el.classList.contains('pp-group-head') ? el : el.closest('.pp-group').querySelector('.pp-group-head');
      const isOpen = head.getAttribute('aria-expanded') === 'true';
      e.preventDefault();
      if (e.key === 'ArrowRight' && !isOpen) togglePageGroup(head.dataset.group);
      else if (e.key === 'ArrowLeft' && el !== head) head.focus();
      else if (e.key === 'ArrowLeft' && isOpen) togglePageGroup(head.dataset.group);
    } else if (e.key === 'Enter' && document.activeElement === pageSearch) {
      // Enter in the search box opens the first matching page
      const first = pageTree.querySelector('.pp-row');
      if (first) pickPage(parseInt(first.dataset.idx, 10));
    }
  });

  document.addEventListener('click', (e) => {
    // composedPath, because re-rendering the tree may already have detached the clicked button
    if (!pagePanel.hidden && !e.composedPath().includes(pagePicker)) togglePagePanel(false);
  });

  /* ---------- Review flags ---------- */
  const FLAG_KIND_LABEL = {
    mine: 'चिह्नितम् — मया पश्चात् (Marked: me, later)',
    askai: 'चिह्नितम् — AI-परीक्षणाय (Marked: ask the AI)',
    reply: 'AI-उत्तरम् (AI reply)',
    pada: 'नवः पदच्छेदः (Updated padaccheda)',
    ocr: 'पाठभेदः (Differs from scan)',
    print: 'मुद्रणदोषः? (Possible misprint)',
    verify: 'परीक्षणीयम् (Please verify)'
  };

  // A flag is resolved once its flagged text no longer appears in its section
  function itemMarks(item) {
    return item.marks || item.saved_marks || [];
  }

  // A flag is open while its text is still there; an AI reply (no suggestion) only while the
  // reviewer's mark on the same word remains
  function isFlagOpen(item, f) {
    if (!(item[f.section] || '').includes(f.match)) return false;
    if (f.kind === 'reply') return itemMarks(item).some(m => m.section === f.section && m.match === f.match);
    return true;
  }

  function openFlagCount(item) {
    return (item.flags || []).filter(f => isFlagOpen(item, f)).length + itemMarks(item).length;
  }

  /* ---------- Reviewer marks: words marked for review later (by the reviewer or the AI) ---------- */
  // Position of the mark's n-th occurrence in its section, or null if the text has changed
  function markRange(item, m) {
    const ranges = flagRanges(item[m.section] || '', m.match);
    const r = ranges[(m.occurrence || 1) - 1] || ranges[0];
    return r ? { start: r[0], end: r[1] } : null;
  }

  let pendingMark = null;
  let lastEditorSec = 'sec1';

  function openMarkDialog(sec) {
    const editor = sec === 'sec2' ? sec2Editor : sec1Editor;
    let start = editor.selectionStart, end = editor.selectionEnd;
    const text = editor.value;
    if (start === end) {
      // No selection: take the word around the caret
      const sep = /[\s।॥,;‘’'"“”—]/;
      while (start > 0 && !sep.test(text[start - 1])) start--;
      while (end < text.length && !sep.test(text[end])) end++;
    }
    const match = text.slice(start, end).trim();
    if (!match) { showToast('पदं चिनोतु (Select a word in the text first)'); return; }
    start = text.indexOf(match, start);
    pendingMark = { section: sec, match, occurrence: flagRanges(text.slice(0, start + match.length), match).length };
    markWord.innerText = match;
    markNote.value = '';
    markDialog.hidden = false;
    markNote.focus();
  }

  function closeMarkDialog() {
    markDialog.hidden = true;
    pendingMark = null;
  }

  function saveMark() {
    if (!pendingMark) return;
    const item = data[currentIndex];
    const target = document.querySelector('input[name="markTarget"]:checked').value;
    item.marks = item.marks || [];
    item.marks.push({ ...pendingMark, target, note: markNote.value.trim() });
    showToast(`⚑ ${pendingMark.match} — चिह्नितम् (Marked; remember to save)`);
    closeMarkDialog();
    renderFlags();
    updateStatus();
  }

  function clearMark(i) {
    const item = data[currentIndex];
    item.marks.splice(i, 1);
    renderFlags();
    updateStatus();
  }

  function showMark(i) {
    const item = data[currentIndex];
    const m = item.marks[i], r = markRange(item, m);
    if (!r) return;
    if (m.section === 'sec2' && !document.getElementById('sec2Box').classList.contains('visible')) toggleSection('sec2Box', 'toggleSec2');
    jumpToChange(r.start, r.end, m.section === 'sec2' ? sec2Editor : sec1Editor);
  }

  function marksTableMarkdown(marks) {
    const target = { mine: 'संशोधकः पश्चात् (reviewer, later)', askai: 'AI-परीक्षणाय (for the AI)' };
    const rows = marks.map((m, i) =>
      `| ${toDevanagariDigits(i + 1)} | ${SEC_LABEL[m.section]} | ${mdCell(m.match)} | ${toDevanagariDigits(m.occurrence || 1)} | ${target[m.target]} | ${m.note ? mdCell(m.note) : ''} |`);
    return ['## ५. समीक्षाचिह्नानि (Marked for Review)', '',
      '| सङ्ख्या | विभागः | पदम् | आवृत्तिः | कस्मै | टिप्पणी |',
      '| :--- | :--- | :--- | :--- | :--- | :--- |', ...rows].join('\n') + '\n';
  }

  function flagRanges(text, match) {
    const ranges = [];
    for (let i = text.indexOf(match); match && i !== -1; i = text.indexOf(match, i + match.length)) {
      ranges.push([i, i + match.length]);
    }
    return ranges;
  }

  function backdropHtml(text, marks) {
    let html = '', pos = 0;
    marks.sort((a, b) => a.start - b.start).forEach(m => {
      if (m.start < pos) return;
      html += escapeHtml(text.slice(pos, m.start)) + `<mark class="flag flag-${m.kind}">${escapeHtml(text.slice(m.start, m.end))}</mark>`;
      pos = m.end;
    });
    // Trailing newline keeps the backdrop's last line in step with the textarea
    return html + escapeHtml(text.slice(pos)) + '\n';
  }

  function renderFlags() {
    const item = data[currentIndex];
    const flags = item.flags || [];
    [['sec1', sec1Backdrop], ['sec2', sec2Backdrop]].forEach(([sec, backdrop]) => {
      const text = item[sec] || '';
      const marks = [];
      flags.filter(f => f.section === sec && isFlagOpen(item, f)).forEach(f =>
        flagRanges(text, f.match).forEach(([start, end]) => marks.push({ start, end, kind: f.kind })));
      // Reviewer marks are drawn first so they win over an AI flag on the same word
      (item.marks || []).filter(m => m.section === sec).forEach(m => {
        const r = markRange(item, m);
        if (r) marks.unshift({ start: r.start, end: r.end, kind: m.target });
      });
      // Padaccheda sentences whose source was corrected but which have not been updated yet
      if (sec === 'sec2') currentStaleRanges.forEach(r => marks.push({ start: r.start, end: r.end, kind: 'stale' }));
      backdrop.innerHTML = backdropHtml(text, marks);
    });

    const userMarks = item.marks || [];
    flagPanel.hidden = !flags.length && !userMarks.length;
    if (flags.length || userMarks.length) {
      const open = openFlagCount(item);
      flagTitle.innerText = `⚑ समीक्षणीयानि पदानि (Words to review) — ${toDevanagariDigits(open)} / ${toDevanagariDigits(flags.length + userMarks.length)}`;
      const markHtml = userMarks.map((m, i) => {
        const where = m.section === 'sec2' ? '<span class="flag-where">२. पदच्छेदः</span>' : '';
        const r = markRange(item, m);
        const lost = r ? '' : '<span class="flag-lost">पाठः परिवर्तितः (text has changed)</span>';
        return `<div class="flag-item is-mark kind-${m.target}">
          <div class="flag-head"><span class="flag-kind">${FLAG_KIND_LABEL[m.target]}</span><span class="flag-words"><span class="flag-match">${escapeHtml(m.match)}</span></span>${where}${lost}</div>
          <div class="flag-actions">${r ? `<button class="light-btn" onclick="showMark(${i})">दर्शयतु (Show)</button>` : ''}<button class="light-btn" onclick="clearMark(${i})" title="चिह्नं निवारयतु (Remove the mark)">निवारयतु (Clear)</button></div>
          <div class="flag-note">${escapeHtml(m.note || '')}</div>
        </div>`;
      }).join('');
      flagList.innerHTML = markHtml + flags.map((f, i) => {
        const isOpen = isFlagOpen(item, f);
        const where = f.section === 'sec2' ? '<span class="flag-where">२. पदच्छेदः</span>' : '';
        const words = `<span class="flag-match">${escapeHtml(f.match)}</span>` +
          (f.suggest ? ` → <span class="flag-suggest">${escapeHtml(f.suggest)}</span>` : '');
        const actions = isOpen
          ? `<button class="light-btn" onclick="showFlag(${i})" title="पाठे दर्शयतु (Show in the text)">दर्शयतु (Show)</button>` +
            (f.suggest ? `<button class="light-btn" onclick="acceptFlag(${i})" title="सूचितं पाठं स्वीकरोतु (Use the suggested reading)">स्वीकरोतु (Accept)</button>` : '')
          : `<span class="flag-done">${f.kind === 'reply' ? '✔ समाहितम् (Settled)' : '✔ परिष्कृतम् (Resolved)'}</span>`;
        return `<div class="flag-item kind-${f.kind}${isOpen ? '' : ' resolved'}">
          <div class="flag-head"><span class="flag-kind">${FLAG_KIND_LABEL[f.kind] || f.kind}</span><span class="flag-words">${words}</span>${where}</div>
          <div class="flag-actions">${actions}</div>
          <div class="flag-note">${escapeHtml(f.note || '')}</div>
        </div>`;
      }).join('');
    }
    refreshPageOption(currentIndex);
    updateReviewCount();
  }

  function flagEditor(f) {
    return f.section === 'sec2' ? sec2Editor : sec1Editor;
  }

  function showFlag(i) {
    const f = data[currentIndex].flags[i];
    if (f.section === 'sec2' && !document.getElementById('sec2Box').classList.contains('visible')) {
      toggleSection('sec2Box', 'toggleSec2');
    }
    const editor = flagEditor(f);
    const start = editor.value.indexOf(f.match);
    if (start !== -1) jumpToChange(start, start + f.match.length, editor);
  }

  function acceptFlag(i) {
    const item = data[currentIndex];
    const f = item.flags[i];
    const editor = flagEditor(f);
    const start = editor.value.indexOf(f.match);
    if (start === -1 || !f.suggest) return;
    // Remembered so the resulting change is logged as an accepted AI suggestion
    (item.acceptedFlags = item.acceptedFlags || []).push(f);
    item.marks = (item.marks || []).filter(m => !(m.section === f.section && m.match === f.match));
    editor.value = editor.value.slice(0, start) + f.suggest + editor.value.slice(start + f.match.length);
    if (f.section === 'sec2') handleSec2Edit(); else handleEdit();
    showToast(`✔ ${f.suggest} — स्वीकृतम् (Accepted; remember to save)`);
  }

  function updateStatus() {
    const status = pageStatus(data[currentIndex]);
    statusChip.className = `status-chip ${status}`;
    statusChip.innerText = STATUS_TEXT[status];
    refreshPageOption(currentIndex);
  }

  function toggleSettings(forceOpen) {
    const open = forceOpen !== undefined ? forceOpen : settingsMenu.hidden;
    settingsMenu.hidden = !open;
    settingsOverlay.hidden = !open;
    settingsBtn.setAttribute('aria-expanded', String(open));
    if (open) {
      const first = settingsMenu.querySelector('.seg button.active') || settingsMenu.querySelector('button');
      if (first) first.focus();
    }
  }

  /* ---------- Settings, remembered in this browser ---------- */
  const SETTINGS_KEY = 'bharata-review-settings';
  const DEFAULT_SETTINGS = {
    theme: 'light',
    uiLang: 'both',
    font: "'Tiro Devanagari Sanskrit', serif",
    fontSize: 22,
    lineHeight: '1.75',
    highlights: true,
    rememberPage: true,
    lastPage: null
  };
  let settings = loadSettings();
  const darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function loadSettings() {
    try {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
    } catch (e) {
      return { ...DEFAULT_SETTINGS };
    }
  }

  function storeSettings() {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* storage blocked: settings last this visit */ }
  }

  function setSetting(key, value) {
    settings[key] = value;
    storeSettings();
    applySettings();
  }

  function resetSettings() {
    settings = { ...DEFAULT_SETTINGS, lastPage: settings.lastPage };
    storeSettings();
    applySettings();
    showToast('↺ मूलविन्यासाः पुनः स्थापिताः (Settings reset to defaults)');
  }

  function applySettings() {
    const root = document.documentElement;
    const theme = settings.theme === 'system' ? (darkQuery && darkQuery.matches ? 'dark' : 'light') : settings.theme;
    root.dataset.theme = theme;
    root.style.setProperty('--font-family', settings.font);
    root.style.setProperty('--font-size', settings.fontSize + 'px');
    root.style.setProperty('--line-height', settings.lineHeight);
    document.body.classList.toggle('hide-highlights', !settings.highlights);
    fontSelect.value = settings.font;
    fontSizeInput.value = settings.fontSize;
    document.getElementById('optHighlights').checked = settings.highlights;
    document.getElementById('optRememberPage').checked = settings.rememberPage;
    settingsMenu.querySelectorAll('.seg').forEach(seg => {
      seg.querySelectorAll('button').forEach(b => {
        const on = String(settings[seg.dataset.setting]) === b.dataset.value;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', String(on));
      });
    });
    if (uiLang !== settings.uiLang) {
      uiLang = settings.uiLang;
      localizeTree(document.body);
    }
    autoResize(sec1Editor);
    autoResize(sec2Editor);
  }

  settingsMenu.querySelectorAll('.seg').forEach(seg => {
    seg.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) setSetting(seg.dataset.setting, b.dataset.value);
    });
  });
  if (darkQuery) darkQuery.addEventListener('change', () => { if (settings.theme === 'system') applySettings(); });

  /* ---------- Interface language ----------
     Interface strings are written "संस्कृतम् (English)". uiText shows the Sanskrit half, the
     English half, or both, as chosen in the settings. Text is rewritten as it appears, including
     messages built later; the book's own text, notes and the export preview are left alone. */
  let uiLang = 'both';
  const UI_EN = {
    '‹ पूर्वम्': '‹ Previous',
    'परम् ›': 'Next ›',
    'पदच्छेदः': 'Padaccheda',
    'टिप्पणी': 'Notes',
    'सम्पूर्णः ग्रन्थः': 'Complete text'
  };
  // A Devanagari phrase (optionally after a Latin prefix such as "AI-") followed by "(English)".
  // The English must contain a lower-case letter, so "(PDF 015)" is never treated as a translation.
  const UI_PAIR = /((?:[A-Za-z]+-)?[\u0900-\u0965\u0970-\u097F][\u0900-\u097FA-Za-z\s,;।—–:?!·'’\-\/+]*?)\s*\(([^()]*[a-z][^()]*)\)/g;
  const UI_SKIP = 'textarea, script, style, .flag-backdrop, #sec3Content, .book-preview-sheet, .flag-words, .flag-note, ' +
    '.mark-dialog-word, .change-text, .proof-full, .no-i18n';
  const UI_ATTRS = ['title', 'placeholder', 'aria-label'];
  const uiOriginals = new WeakMap();   // node → {orig, shown} for text; element → {attr: {orig, shown}}

  function uiText(s) {
    if (uiLang === 'both' || !s) return s;
    if (uiLang === 'en') {
      const m = s.match(/^(\s*)(.*?)(\s*)$/s);
      if (UI_EN[m[2]]) return m[1] + UI_EN[m[2]] + m[3];
    }
    return s.replace(UI_PAIR, (_, sa, en) => uiLang === 'en' ? en.trim() : sa.trim());
  }

  function localizeText(node) {
    const el = node.parentElement;
    if (!el || el.closest(UI_SKIP)) return;
    const cur = node.nodeValue;
    const rec = uiOriginals.get(node);
    const orig = rec && rec.shown === cur ? rec.orig : cur;
    const shown = uiText(orig);
    uiOriginals.set(node, { orig, shown });
    if (shown !== cur) node.nodeValue = shown;
  }

  function localizeAttr(el, attr) {
    if (!el.hasAttribute(attr) || el.closest(UI_SKIP)) return;
    const cur = el.getAttribute(attr);
    const recs = uiOriginals.get(el) || {};
    const rec = recs[attr];
    const orig = rec && rec.shown === cur ? rec.orig : cur;
    const shown = uiText(orig);
    recs[attr] = { orig, shown };
    uiOriginals.set(el, recs);
    if (shown !== cur) el.setAttribute(attr, shown);
  }

  function localizeTree(root) {
    if (root.nodeType === Node.TEXT_NODE) { localizeText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    UI_ATTRS.forEach(a => localizeAttr(root, a));
    root.querySelectorAll('[title], [placeholder], [aria-label]').forEach(el => UI_ATTRS.forEach(a => localizeAttr(el, a)));
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) localizeText(n);
  }

  new MutationObserver(records => {
    if (uiLang === 'both') return;
    records.forEach(r => {
      if (r.type === 'childList') r.addedNodes.forEach(localizeTree);
      else if (r.type === 'characterData') localizeText(r.target);
      else if (r.type === 'attributes') localizeAttr(r.target, r.attributeName);
    });
  }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: UI_ATTRS });

  const nativeAlert = window.alert.bind(window);
  window.alert = msg => nativeAlert(uiText(String(msg)));

  function ensureBaseline(item) {
    if (item.baseline !== undefined) return;
    item.baseline = item.orig_sec1 !== undefined ? item.orig_sec1 : item.sec1;
    item.sec2Baseline = item.orig_sec2 !== undefined ? item.orig_sec2 : item.sec2;
    if (item.marks === undefined) item.marks = (item.saved_marks || []).map(m => ({ ...m }));
    // A page the scholar already saved opens as saved (its tags come back from the saved log)
    if (item.verified) item.savedSnapshot = buildSavedMarkdown(item).content;
  }

  /* ---------- Navigation through words to review ----------
     Targets are open review flags and padaccheda sentences whose source was corrected but
     which still need updating, in book order: page, then मूलपाठः before पदच्छेदः, then position. */
  let reviewCursor = null;

  function reviewTargets(idx) {
    const item = data[idx];
    ensureBaseline(item);
    const targets = [];
    (item.flags || []).forEach(f => {
      if (!isFlagOpen(item, f)) return;
      const at = (item[f.section] || '').indexOf(f.match);
      if (at !== -1) targets.push({ idx, sec: f.section, start: at, end: at + f.match.length });
    });
    (item.marks || []).forEach(m => {
      const r = markRange(item, m);
      if (r) targets.push({ idx, sec: m.section, start: r.start, end: r.end });
    });
    if (item.sec1 !== item.baseline) {
      pageChanges(item).staleRanges.forEach(r => targets.push({ idx, sec: 'sec2', start: r.start, end: r.end }));
    }
    const rank = t => [t.idx, t.sec === 'sec1' ? 0 : 1, t.start];
    const seen = new Set();
    return targets.filter(t => { const k = `${t.sec}|${t.start}`; if (seen.has(k)) return false; seen.add(k); return true; })
      .sort((a, b) => compareRank(rank(a), rank(b)));
  }

  function compareRank(a, b) {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
    return 0;
  }

  function allReviewTargets() {
    return data.flatMap((_, idx) => reviewTargets(idx));
  }

  function updateReviewCount() {
    const all = allReviewTargets();
    let label = `⚑ ${toDevanagariDigits(all.length)}`;
    if (reviewCursor && all.length) {
      const pos = all.findIndex(t => t.idx === reviewCursor.idx && t.sec === reviewCursor.sec && t.start === reviewCursor.start);
      if (pos !== -1) label = `⚑ ${toDevanagariDigits(pos + 1)} / ${toDevanagariDigits(all.length)}`;
    }
    reviewCount.innerText = all.length ? label : '✔ ०';
    reviewCount.classList.toggle('done', !all.length);
    reviewCount.title = all.length
      ? `${all.length} word(s) or padaccheda sentence(s) still to review in the book`
      : 'समीक्षणीयं नास्ति (Nothing left to review)';
  }

  function gotoReview(dir) {
    const all = allReviewTargets();
    if (!all.length) {
      showToast('✔ समीक्षणीयं नास्ति (Nothing left to review)');
      updateReviewCount();
      return;
    }
    const rank = t => [t.idx, t.sec === 'sec1' ? 0 : 1, t.start];
    // Without a cursor, start from the top (next) or bottom (previous) of the current page
    const cur = reviewCursor ? rank(reviewCursor) : (dir > 0 ? [currentIndex, -1, -1] : [currentIndex, 2, Infinity]);
    let target = dir > 0
      ? all.find(t => compareRank(rank(t), cur) > 0)
      : [...all].reverse().find(t => compareRank(rank(t), cur) < 0);
    if (!target) target = dir > 0 ? all[0] : all[all.length - 1];   // wrap around the book

    if (target.idx !== currentIndex) switchPage(target.idx);
    reviewCursor = target;
    if (target.sec === 'sec2' && !document.getElementById('sec2Box').classList.contains('visible')) {
      toggleSection('sec2Box', 'toggleSec2');
    }
    jumpToChange(target.start, target.end, target.sec === 'sec2' ? sec2Editor : sec1Editor);
    updateReviewCount();
  }

  function switchPage(idx) {
    currentIndex = parseInt(idx, 10);
    const item = data[currentIndex];
    if (settings.lastPage !== item.page) setLastPage(item.page);

    ensureBaseline(item);
    if (reviewCursor && reviewCursor.idx !== currentIndex) reviewCursor = null;

    pageImg.src = item.img;
    // Warm the cache for the next scan so page turns feel instant
    if (data[currentIndex + 1]) new Image().src = data[currentIndex + 1].img;
    sec1Editor.value = item.sec1;
    sec2Editor.value = item.sec2;
    sec3Content.innerHTML = item.sec3_html;

    currentPageHeading.innerText = pageLabel(item);
    if (saveResetTimer) { clearTimeout(saveResetTimer); saveResetTimer = null; }
    resetSaveButton();
    pagePdfNum.innerText = `PDF ${item.page}`;

    // English front matter: Latin font, no padaccheda section
    const isEnglish = item.lang === 'en';
    textPane.classList.toggle('lang-en', isEnglish);
    toggleSec2Btn.hidden = isEnglish;
    sec1Label.innerText = isEnglish ? '१. मूलपाठः (Original Text — English)' : '१. मूलपाठः (Devanagari OCR Text)';
    textPane.scrollTop = 0;

    prevBtn.disabled = (currentIndex <= 0);
    nextBtn.disabled = (currentIndex >= data.length - 1);

    autoResize(sec1Editor);
    autoResize(sec2Editor);

    handleEdit();
  }

  function setLastPage(page) {
    settings.lastPage = page;
    storeSettings();
  }

  function prevPage() {
    if (currentIndex > 0) switchPage(currentIndex - 1);
  }

  function nextPage() {
    if (currentIndex < data.length - 1) switchPage(currentIndex + 1);
  }

  function adjustImageZoom(delta) {
    currentZoom = Math.max(50, Math.min(220, currentZoom + delta));
    applyImageZoom();
  }

  function resetImageZoom() {
    currentZoom = 100;
    applyImageZoom();
  }

  function applyImageZoom() {
    zoomLabel.innerText = currentZoom + '%';
    pageImg.style.width = currentZoom + '%';
    pageImg.style.maxWidth = currentZoom + '%';
  }

  function setFontSizeNumber(val) {
    let num = parseInt(val, 10);
    if (isNaN(num)) num = 22;
    num = Math.max(14, Math.min(48, num));
    fontSizeInput.value = num;
    setSetting('fontSize', num);
  }

  function stepFontSize(delta) {
    let cur = parseInt(fontSizeInput.value, 10) || 22;
    setFontSizeNumber(cur + delta);
  }

  function changeFont(fontFamily) {
    setSetting('font', fontFamily);
  }

  function toggleSection(elementId, btnId) {
    const el = document.getElementById(elementId);
    const btn = document.getElementById(btnId);
    const isVisible = el.classList.contains('visible');

    if (isVisible) {
      el.classList.remove('visible');
      btn.classList.remove('active');
      btn.querySelector('.sign').textContent = '+';
    } else {
      el.classList.add('visible');
      btn.classList.add('active');
      btn.querySelector('.sign').textContent = '−';
      if (elementId === 'sec2Box') autoResize(sec2Editor);
    }
  }

  function handleSec2Edit() {
    autoResize(sec2Editor);
    data[currentIndex].sec2 = sec2Editor.value;
    refreshProofPanel();
    updateStatus();
    renderFlags();
  }

  function revertCurrentPage() {
    const item = data[currentIndex];
    if (item.baseline !== undefined) {
      sec1Editor.value = item.baseline;
      handleEdit();
      showToast('↺ मूलपाठः पूर्ववत् स्थापितः (Reverted to original scan text)');
    }
  }

  /* Real-Time Proof Marks: token-level diff of Section 1 against the original OCR */
  let proofShowFull = false;
  let proofCollapsed = false;

  function handleEdit() {
    autoResize(sec1Editor);
    const item = data[currentIndex];
    const currentText = sec1Editor.value;
    item.sec1 = currentText;

    revertBtn.style.display = currentText !== item.baseline ? 'inline-flex' : 'none';
    refreshProofPanel();
    updateStatus();
    renderFlags();
  }

  function tokenize(str) {
    return str.split(/([\s।॥,.\-—]+)/).filter(t => t.length > 0);
  }

  // Longest-common-subsequence diff over tokens; returns [op, token] with op in '=', '-', '+'
  function diffTokens(a, b) {
    let start = 0;
    while (start < a.length && start < b.length && a[start] === b[start]) start++;
    let endA = a.length, endB = b.length;
    while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; }

    const ops = [];
    for (let i = 0; i < start; i++) ops.push(['=', a[i]]);
    const A = a.slice(start, endA), B = b.slice(start, endB);
    const n = A.length, m = B.length;
    if (n * m > 4000000) {
      A.forEach(t => ops.push(['-', t]));
      B.forEach(t => ops.push(['+', t]));
    } else {
      const w = m + 1;
      const L = new Uint16Array((n + 1) * w);
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          L[i * w + j] = A[i] === B[j] ? L[(i + 1) * w + j + 1] + 1 : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
        }
      }
      let i = 0, j = 0;
      while (i < n && j < m) {
        if (A[i] === B[j]) { ops.push(['=', A[i]]); i++; j++; }
        else if (L[(i + 1) * w + j] >= L[i * w + j + 1]) { ops.push(['-', A[i]]); i++; }
        else { ops.push(['+', B[j]]); j++; }
      }
      while (i < n) ops.push(['-', A[i++]]);
      while (j < m) ops.push(['+', B[j++]]);
    }
    for (let i = endA; i < a.length; i++) ops.push(['=', a[i]]);
    return ops;
  }

  // Make whitespace-only insertions/deletions visible
  function visibleToken(t) {
    return t.trim() === '' ? t.replace(/\n/g, '↵').replace(/[^\S\n]+/g, '␣') : t;
  }

  function contextText(ops, from, step) {
    const parts = [];
    for (let k = from; k >= 0 && k < ops.length && parts.length < 3; k += step) {
      if (ops[k][0] === '-') continue;
      if (ops[k][0] === '+') break;
      parts.push(ops[k][1]);
    }
    if (step < 0) parts.reverse();
    return parts.join('').replace(/\s+/g, ' ');
  }

  /* ---------- Changes and the correction log ----------
     Every difference from the original OCR (Section 1) or AI padaccheda (Section 2) is a change.
     The reviewer tags each one; the tags drive the log saved with the page. */
  const CHANGE_CATEGORIES = {
    ocr: { label: 'OCR-दोषः (OCR misread the scan)', badge: '🔍 OCR-दोषः', secs: ['sec1'] },
    misprint: { label: 'मुद्रणदोषः (misprint in the book)', badge: '⚠️ मुद्रणदोषः', secs: ['sec1'] },
    pada: { label: 'पदच्छेददोषः (AI padaccheda error)', badge: '✂️ पदच्छेददोषः', secs: ['sec2'] },
    other: { label: 'अन्यत् (other)', badge: '✏️ अन्यत्', secs: ['sec1', 'sec2'] }
  };
  const SEC_LABEL = { sec1: 'मूलपाठः', sec2: 'पदच्छेदः' };
  const SOURCE_LABEL = { reviewer: 'संशोधकः (reviewer)', ai: 'AI-सूचना स्वीकृता (AI flag accepted)' };
  let currentChanges = [];

  // Group consecutive changed tokens into hunks; hunkOf[k] is the hunk index of op k
  function computeHunks(ops) {
    // start/end are offsets in the edited text, baseStart/baseEnd in the original
    const hunks = [], hunkOf = [];
    let pos = 0, basePos = 0, hunk = null;
    ops.forEach(([op, tok], k) => {
      if (op === '=') { hunk = null; pos += tok.length; basePos += tok.length; return; }
      if (!hunk) { hunk = { first: k, last: k, del: '', ins: '', start: pos, end: pos, baseStart: basePos, baseEnd: basePos }; hunks.push(hunk); }
      hunkOf[k] = hunks.length - 1;
      hunk.last = k;
      if (op === '-') { hunk.del += tok; basePos += tok.length; hunk.baseEnd = basePos; }
      else { hunk.ins += tok; pos += tok.length; hunk.end = pos; }
    });
    return { hunks, hunkOf };
  }

  function acceptedFlagFor(item, sec, h) {
    const del = h.del.trim(), ins = h.ins.trim();
    return (item.acceptedFlags || []).find(f => f.section === sec &&
      (!del || f.match.includes(del)) && (!ins || (f.suggest || '').includes(ins)));
  }

  function defaultCategory(sec, h, flag) {
    if (flag) return flag.kind === 'print' ? 'misprint' : (sec === 'sec2' ? 'pada' : 'ocr');
    if (!h.del.trim() && !h.ins.trim()) return 'other';   // spacing / line breaks only
    return sec === 'sec2' ? 'pada' : 'ocr';
  }

  // Sentence spans (ending in a danda) with offsets; source and padaccheda have matching dandas
  function sentenceSpans(text) {
    const spans = [], re = /[^।॥]*[।॥]+[’'"”]*\s*|[^।॥]+$/g;
    let m;
    while ((m = re.exec(text || '')) && m[0].length) spans.push({ start: m.index, end: m.index + m[0].length });
    return spans;
  }

  function sameText(a, b) {
    return normalizeSpace(a) === normalizeSpace(b);
  }

  // Tag, note, source and padaccheda status recorded for a change the last time the page was saved
  function savedLogEntry(item, sec, h) {
    return (item.saved_log || []).find(e => e.section === sec && sameText(e.before, h.del) && sameText(e.after, h.ins));
  }

  function pageChanges(item) {
    const result = {};
    item.changeTags = item.changeTags || {};
    item.changeNotes = item.changeNotes || {};
    item.padaConfirmed = item.padaConfirmed || {};
    [['sec1', 'baseline'], ['sec2', 'sec2Baseline']].forEach(([sec, baseKey]) => {
      const base = item[baseKey], text = item[sec] || '';
      if (base === undefined || base === text) { result[sec] = { ops: [], hunks: [], hunkOf: [], changes: [] }; return; }
      const ops = diffTokens(tokenize(base), tokenize(text));
      const { hunks, hunkOf } = computeHunks(ops);
      const seen = {};
      const changes = hunks.map((h, hi) => {
        const id = `${sec}|${h.del}|${h.ins}`;
        seen[id] = (seen[id] || 0) + 1;
        const key = `${id}|${seen[id]}`;
        const flag = acceptedFlagFor(item, sec, h);
        const saved = savedLogEntry(item, sec, h);
        const tag = item.changeTags[key] || (saved && saved.category);
        if (saved && saved.pada === 'confirmed' && item.padaConfirmed[key] === undefined) item.padaConfirmed[key] = true;
        return {
          sec, key, hunk: h, hunkIndex: hi,
          category: tag && CHANGE_CATEGORIES[tag] && CHANGE_CATEGORIES[tag].secs.includes(sec) ? tag : defaultCategory(sec, h, flag),
          source: flag || (saved && saved.source === 'ai') ? 'ai' : 'reviewer',
          // An accepted AI suggestion starts with the AI's reason as its note; the reviewer may edit it
          note: item.changeNotes[key] !== undefined ? item.changeNotes[key] : (saved ? saved.note : (flag && flag.note) || ''),
          before: contextText(ops, h.first - 1, -1),
          after: contextText(ops, h.last + 1, 1)
        };
      });
      result[sec] = { ops, hunks, hunkOf, changes };
    });
    markPadacchedaStatus(item, result);
    return result;
  }

  // For each source change, find the padaccheda sentence(s) it belongs to (by danda count) and
  // decide whether that padaccheda was updated, confirmed as still correct, or still needs updating
  function markPadacchedaStatus(item, result) {
    result.staleRanges = [];
    if (!item.sec2Baseline) return;
    const srcSpans = sentenceSpans(item.baseline);
    const padaBase = sentenceSpans(item.sec2Baseline), padaCur = sentenceSpans(item.sec2 || '');
    const aligned = srcSpans.length === padaBase.length;
    const curAligned = aligned && padaCur.length === padaBase.length;
    result.sec1.changes.forEach(c => {
      const h = c.hunk;
      if (!h.del.trim() && !h.ins.trim()) { c.pada = null; return; }   // spacing only
      if (!aligned) {
        c.pada = { status: item.padaConfirmed[c.key] ? 'confirmed' : 'unknown', ranges: [] };
        return;
      }
      const end = Math.max(h.baseEnd, h.baseStart + 1);
      const idx = srcSpans.map((s, i) => (s.start < end && s.end > h.baseStart) ? i : -1).filter(i => i !== -1);
      if (!idx.length) idx.push(srcSpans.length - 1);
      let updated;
      if (curAligned) {
        updated = idx.some(i => !sameText(item.sec2Baseline.slice(padaBase[i].start, padaBase[i].end),
                                         item.sec2.slice(padaCur[i].start, padaCur[i].end)));
      } else {
        updated = (item.sec2 || '') !== item.sec2Baseline;
      }
      const ranges = curAligned ? idx.map(i => ({ start: padaCur[i].start, end: padaCur[i].end })) : [];
      const status = updated ? 'updated' : (item.padaConfirmed[c.key] ? 'confirmed' : (curAligned ? 'stale' : 'unknown'));
      c.pada = { status, ranges };
      if (status === 'stale') result.staleRanges.push(...ranges);
    });
  }

  let currentStaleRanges = [];

  function padaStatusHtml(c, i) {
    if (!c.pada) return '';
    if (c.pada.status === 'updated') return '<span class="pada-status ok">✔ पदच्छेदः अद्यतितः (padaccheda updated)</span>';
    if (c.pada.status === 'confirmed') return `<span class="pada-status ok">✔ पदच्छेदः यथावत् (padaccheda confirmed) <button class="light-btn" onclick="confirmPada(${i}, false)">↺</button></span>`;
    const show = c.pada.ranges.length ? `<button class="light-btn" onclick="jumpToPada(${i})">दर्शयतु (Show)</button>` : '';
    return `<span class="pada-status stale">⚠ पदच्छेदः अद्यतनीयः (padaccheda may need updating) ${show}<button class="light-btn" onclick="confirmPada(${i}, true)">यथावत् (Still correct)</button></span>`;
  }

  function refreshProofPanel() {
    const item = data[currentIndex];
    const pc = pageChanges(item);
    currentChanges = [...pc.sec1.changes, ...pc.sec2.changes];
    currentStaleRanges = pc.staleRanges;
    proofPanel.hidden = !currentChanges.length;
    if (!currentChanges.length) return;

    const n = currentChanges.length;
    const stale = currentChanges.filter(c => c.pada && (c.pada.status === 'stale' || c.pada.status === 'unknown')).length;
    proofTitle.innerText = `दृष्टं शोधनम् — ${toDevanagariDigits(n)} परिवर्तन${n === 1 ? 'म्' : 'ानि'} (${n} change${n === 1 ? '' : 's'})` +
      (stale ? ` · ⚠ ${toDevanagariDigits(stale)} पदच्छेदः अद्यतनीयः` : '');

    proofList.innerHTML = currentChanges.map((c, i) => {
      const h = c.hunk;
      const del = h.del ? `<del>${escapeHtml(visibleToken(h.del))}</del>` : '';
      const ins = h.ins ? `<ins>${escapeHtml(visibleToken(h.ins))}</ins>` : '';
      const options = Object.entries(CHANGE_CATEGORIES).filter(([, v]) => v.secs.includes(c.sec))
        .map(([k, v]) => `<option value="${k}"${k === c.category ? ' selected' : ''}>${v.label}</option>`).join('');
      const hint = c.category === 'misprint'
        ? '<span class="change-hint">रक्षणे मुद्रितः पाठः मूलपाठे रक्ष्यते, शोधनं टिप्पण्यां लिख्यते (On save, the printed reading stays in मूलपाठः and the correction goes into the notes)</span>' : '';
      const source = c.source === 'ai' ? ' · ⚑ AI' : '';
      return `<div class="change-item">
        <button class="change-text" onclick="jumpToChangeIn(${i})" title="पाठे दर्शयतु (Show in editor)"><span class="change-sec">${SEC_LABEL[c.sec]}${source}</span><span class="ctx">…${escapeHtml(c.before)}</span>${del}${del && ins ? ' → ' : ''}${ins}<span class="ctx">${escapeHtml(c.after)}…</span></button>
        <div class="change-meta">
          <select onchange="setChangeTag(${i}, this.value)" title="दोषप्रकारः (Kind of error)">${options}</select>
          <input class="change-note" type="text" value="${escapeHtml(c.note).replace(/"/g, '&quot;')}" placeholder="टिप्पणी (optional note, e.g. ञ्च read as श्च)" oninput="setChangeNote(${i}, this.value)">
          ${hint}
          ${padaStatusHtml(c, i)}
        </div>
      </div>`;
    }).join('');

    const fullHtml = ops => ops.map(([op, tok]) => {
      if (op === '=') return escapeHtml(tok);
      return op === '-' ? `<del>${escapeHtml(visibleToken(tok))}</del>` : `<ins>${escapeHtml(tok)}</ins>`;
    }).join('');
    proofFull.innerHTML = [['sec1', '१. मूलपाठः'], ['sec2', '२. पदच्छेदः']]
      .filter(([sec]) => pc[sec].changes.length)
      .map(([sec, label]) => `<div class="proof-full-label">${label}</div>${fullHtml(pc[sec].ops)}`).join('\n');

    applyProofView();
  }

  function confirmPada(i, confirmed) {
    const c = currentChanges[i];
    data[currentIndex].padaConfirmed[c.key] = confirmed;
    refreshProofPanel();
    renderFlags();
    updateStatus();
  }

  function jumpToPada(i) {
    const r = currentChanges[i].pada.ranges[0];
    if (!r) return;
    if (!document.getElementById('sec2Box').classList.contains('visible')) toggleSection('sec2Box', 'toggleSec2');
    jumpToChange(r.start, r.end, sec2Editor);
  }

  function setChangeTag(i, value) {
    const c = currentChanges[i];
    data[currentIndex].changeTags[c.key] = value;
    refreshProofPanel();
    updateStatus();
  }

  function setChangeNote(i, value) {
    const c = currentChanges[i];
    data[currentIndex].changeNotes[c.key] = value;
    updateStatus();
  }

  function jumpToChangeIn(i) {
    const c = currentChanges[i];
    if (c.sec === 'sec2') {
      if (!document.getElementById('sec2Box').classList.contains('visible')) toggleSection('sec2Box', 'toggleSec2');
      jumpToChange(c.hunk.start, c.hunk.end, sec2Editor);
    } else {
      jumpToChange(c.hunk.start, c.hunk.end, sec1Editor);
    }
  }

  // Edited text with the hunks in keepPrinted reverted to the original reading
  function textKeepingPrinted(ops, hunkOf, keepPrinted) {
    return ops.map(([op, tok], k) => {
      if (op === '=') return tok;
      const keepOriginal = keepPrinted.has(hunkOf[k]);
      return (op === '-') === keepOriginal ? tok : '';
    }).join('');
  }

  function mdCell(text) {
    const t = (text || '').replace(/\|/g, '¦').replace(/\s*\n\s*/g, ' ↵ ').trim();
    return t || '∅';
  }

  // Misprints are recorded in the apparatus table rather than silently emended in मूलपाठः
  function appendApparatusRows(sec3, misprints) {
    const lines = sec3 ? sec3.split('\n') : [];
    const isRow = l => /^\s*\|/.test(l) && !/^\s*\|[\s\-:|]+\|\s*$/.test(l);
    let rowCount = Math.max(0, lines.filter(isRow).length - 1);
    if (!lines.some(isRow)) {
      lines.push('| सङ्ख्या | स्थानम् | मूलपाठः | शोधितः पाठः | प्रकारः | विवरणम् |', '| :--- | :--- | :--- | :--- | :--- | :--- |');
    }
    misprints.forEach(c => {
      rowCount += 1;
      const note = 'संशोधकेन निर्दिष्टः मुद्रणदोषः (misprint reported by reviewer)' + (c.note ? `; ${c.note}` : '');
      lines.push(`| ${toDevanagariDigits(rowCount)} | …${mdCell(c.before)}… | ${mdCell(c.hunk.del)} | ${mdCell(c.hunk.ins)} | ⚠️ मुद्रणदोषः | ${mdCell(note)} |`);
    });
    return lines.join('\n');
  }

  function changeLogEntries(pc, item) {
    const entries = [...pc.sec1.changes, ...pc.sec2.changes].map(c => ({
      section: c.sec,
      category: c.category,
      before: c.hunk.del,
      after: c.hunk.ins,
      context_before: c.before,
      context_after: c.after,
      source: c.source,
      note: c.note,
      pada: c.pada ? (c.pada.status === 'unknown' ? 'stale' : c.pada.status) : ''
    }));
    // Misprints saved earlier keep the printed reading, so they no longer show up as changes:
    // carry their log entries forward from the saved log
    (item.saved_log || []).filter(e => e.category === 'misprint' &&
      !pc.sec1.changes.some(c => sameText(c.hunk.del, e.before) && sameText(c.hunk.ins, e.after)))
      .forEach(e => {
        const m = (e.context || '').match(/^…(.*?) \[.*\] (.*?)…$/);
        entries.push({ section: 'sec1', category: 'misprint', before: e.before, after: e.after,
          context_before: m ? m[1] : '', context_after: m ? m[2] : '', source: e.source, note: e.note, pada: e.pada || '' });
      });
    return entries.map((e, i) => ({ n: i + 1, ...e }));
  }

  const PADA_STATUS_LABEL = { updated: '✔ अद्यतितः', confirmed: '✔ यथावत्', stale: '⚠ अद्यतनीयः' };

  function logTableMarkdown(entries) {
    const rows = entries.map(e =>
      `| ${toDevanagariDigits(e.n)} | ${SEC_LABEL[e.section]} | ${CHANGE_CATEGORIES[e.category].badge} | ${mdCell(e.before)} | ${mdCell(e.after)} | …${mdCell(e.context_before)} [${mdCell(e.before)} → ${mdCell(e.after)}] ${mdCell(e.context_after)}… | ${SOURCE_LABEL[e.source]} | ${e.note ? mdCell(e.note) : ''} | ${PADA_STATUS_LABEL[e.pada] || ''} |`);
    return ['## ४. संशोधनलेखः (Correction Log)', '',
      '| सङ्ख्या | विभागः | प्रकारः | पूर्वपाठः | संशोधितः पाठः | सन्दर्भः | स्रोतः | टिप्पणी | पदच्छेदः |',
      '| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |', ...rows].join('\n') + '\n';
  }

  // The page as saved: misprints kept as printed (and noted in Section 3), plus the correction log
  function buildSavedMarkdown(item) {
    const pc = pageChanges(item);
    const misprints = pc.sec1.changes.filter(c => c.category === 'misprint');
    let sec1 = item.sec1, sec3 = (item.sec3_md || '').trim();
    if (misprints.length) {
      sec1 = textKeepingPrinted(pc.sec1.ops, pc.sec1.hunkOf, new Set(misprints.map(c => c.hunkIndex)));
      sec3 = appendApparatusRows(sec3, misprints);
    }
    const md = buildPageMarkdown({ ...item, sec1, sec3_md: sec3 });
    const log = changeLogEntries(pc, item);
    let content = log.length ? md + '\n' + logTableMarkdown(log) : md;
    if ((item.marks || []).length) content += '\n' + marksTableMarkdown(item.marks);
    return { content, log };
  }

  function applyProofView() {
    proofList.hidden = proofCollapsed || proofShowFull;
    proofFull.hidden = proofCollapsed || !proofShowFull;
    proofModeBtn.hidden = proofCollapsed;
    proofModeBtn.innerText = proofShowFull ? 'सूच्यां पश्यतु (Show as list)' : 'पूर्णपाठे पश्यतु (Show in full text)';
    proofCollapseBtn.innerText = proofCollapsed ? '▴' : '▾';
  }

  function toggleProofMode() {
    proofShowFull = !proofShowFull;
    applyProofView();
    if (proofShowFull) {
      const firstMark = proofFull.querySelector('ins, del');
      if (firstMark) proofFull.scrollTop = Math.max(0, firstMark.offsetTop - proofFull.offsetTop - 40);
    }
  }
  function toggleProofCollapse() { proofCollapsed = !proofCollapsed; applyProofView(); }

  // Measure the vertical offset of a character position inside the auto-sized textarea
  let caretMirror = null;
  function caretOffsetTop(textarea, pos) {
    if (!caretMirror) {
      caretMirror = document.createElement('div');
      caretMirror.style.cssText = 'position:absolute; visibility:hidden; top:0; left:-9999px; white-space:pre-wrap; overflow-wrap:break-word;';
      document.body.appendChild(caretMirror);
    }
    const cs = getComputedStyle(textarea);
    ['fontFamily', 'fontSize', 'lineHeight', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
     'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth', 'boxSizing', 'letterSpacing']
      .forEach(p => { caretMirror.style[p] = cs[p]; });
    caretMirror.style.borderStyle = 'solid';
    caretMirror.style.width = textarea.offsetWidth + 'px';
    caretMirror.textContent = textarea.value.slice(0, pos);
    const marker = document.createElement('span');
    marker.textContent = '\u200b';
    caretMirror.appendChild(marker);
    return marker.offsetTop;
  }

  function jumpToChange(start, end, editor = sec1Editor) {
    editor.focus({ preventScroll: true });
    editor.setSelectionRange(start, Math.max(start, end));
    const paneRect = textPane.getBoundingClientRect();
    const editorTop = editor.getBoundingClientRect().top - paneRect.top + textPane.scrollTop;
    const target = editorTop + caretOffsetTop(editor, start) - paneRect.height / 3;
    textPane.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
  }

  function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* Formatting Page Markdown */
  function buildPageMarkdown(item, opts = { sec1: true, sec2: true, sec3: true }) {
    const devNum = toDevanagariDigits(item.page);
    let parts = [`# पृष्ठम् ${devNum}`];
    if (opts.sec1) {
      parts.push(`## १. मूलपाठः\n\n${(item.sec1 || '').trim()}`);
    }
    if (opts.sec2) {
      parts.push(`## २. पदच्छेदसहितः पाठः\n\n${(item.sec2 || '').trim()}`);
    }
    if (opts.sec3) {
      const sec3Text = (item.sec3_md || '').trim() || '(टिप्पणी नास्ति)';
      parts.push(`## ३. सम्पादनटिप्पण्यः\n\n${sec3Text}`);
    }
    return parts.join('\n\n') + '\n';
  }

  async function copyToClipboard(text, successMessage, htmlContent = null) {
    try {
      if (htmlContent && navigator.clipboard && window.ClipboardItem) {
        const itemData = {
          'text/plain': new Blob([text], { type: 'text/plain' }),
          'text/html': new Blob([htmlContent], { type: 'text/html' })
        };
        await navigator.clipboard.write([new ClipboardItem(itemData)]);
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const temp = document.createElement('textarea');
        temp.value = text;
        document.body.appendChild(temp);
        temp.select();
        document.execCommand('copy');
        document.body.removeChild(temp);
      }
      showToast(successMessage);
    } catch (err) {
      // Fallback to plain text if ClipboardItem fails
      try {
        await navigator.clipboard.writeText(text);
        showToast(successMessage);
      } catch (e2) {
        alert('प्रतिकरणे दोषः (Copy failed): ' + e2.message);
      }
    }
  }

  // The text font chosen in the settings menu, with fallbacks, for copied and exported documents
  function textFontStack() {
    const chosen = getComputedStyle(document.documentElement).getPropertyValue('--font-family').trim()
      .replace(/,\s*serif\s*$/, '');
    return `${chosen}, 'Tiro Devanagari Sanskrit', 'Noto Serif Devanagari', 'Nirmala UI', 'Mangal', serif`.replace(/"/g, "'");
  }

  function copySectionText(secKey) {
    const item = data[currentIndex];
    item.sec1 = sec1Editor.value;
    item.sec2 = sec2Editor.value;
    const devNum = toDevanagariDigits(item.page);

    if (secKey === 'sec1') {
      const html = `<div style="font-family: ${textFontStack()}; font-size: 16pt; line-height: 1.9;">${escapeHtml(item.sec1).replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>')}</div>`;
      copyToClipboard(item.sec1, `✔ पृष्ठम् ${devNum} — मूलपाठः प्रतिकृतः (Copied Sanskrit Text!)`, html);
    } else if (secKey === 'sec2') {
      const html = `<div style="font-family: ${textFontStack()}; font-size: 15pt; line-height: 1.9;">${escapeHtml(item.sec2).replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>')}</div>`;
      copyToClipboard(item.sec2, `✔ पृष्ठम् ${devNum} — पदच्छेदः प्रतिकृतः (Copied Padaccheda!)`, html);
    } else if (secKey === 'sec3') {
      copyToClipboard(item.sec3_md || '', `✔ पृष्ठम् ${devNum} — टिप्पणी प्रतिकृता (Copied Apparatus!)`, item.sec3_html || null);
    }
  }

  function copyCurrentPageFormatted() {
    const item = data[currentIndex];
    item.sec1 = sec1Editor.value;
    item.sec2 = sec2Editor.value;
    const devNum = toDevanagariDigits(item.page);

    const plainParts = [
      `पृष्ठम् ${devNum}`,
      `१. मूलपाठः\n${(item.sec1 || '').trim()}`,
      `२. पदच्छेदसहितः पाठः\n${(item.sec2 || '').trim()}`
    ];
    if (item.sec3_md) {
      plainParts.push(`३. सम्पादनटिप्पण्यः\n${item.sec3_md.trim()}`);
    }
    const plainText = plainParts.join('\n\n');

    const htmlParts = [
      `<div style="font-family: ${textFontStack()}; font-size: 15pt; line-height: 1.9; color: #111;">`,
      `<h2 style="color: #7c2d12; border-bottom: 1px solid #fed7aa;">पृष्ठम् ${devNum}</h2>`,
      `<h3 style="color: #9a3412;">१. मूलपाठः</h3>`,
      `<p style="white-space: pre-wrap;">${escapeHtml((item.sec1 || '').trim())}</p>`,
      `<h3 style="color: #1e3a8a;">२. पदच्छेदसहितः पाठः</h3>`,
      `<p style="white-space: pre-wrap;">${escapeHtml((item.sec2 || '').trim())}</p>`,
      `<h3 style="color: #334155;">३. सम्पादनटिप्पण्यः</h3>`,
      item.sec3_html || '',
      `</div>`
    ];
    copyToClipboard(plainText, `✔ पृष्ठम् ${devNum} — सम्पूर्णं पृष्ठं प्रतिकृतम् (Copied formatted page!)`, htmlParts.join('\n'));
  }

  function triggerFileDownload(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /* Complete Book / All-Pages Compilation (Reader-Friendly) */
  function getModalOptions() {
    return {
      mergeHyphens: document.getElementById('optMergeHyphens').checked,
      showPageNums: document.getElementById('optShowPageNums').checked,
      frontMatter: document.getElementById('optFrontMatter').checked,
      reviewFlags: document.getElementById('optReviewFlags').checked,
      sec1: document.getElementById('incSec1').checked,
      sec2: document.getElementById('incSec2').checked,
      sec3: document.getElementById('incSec3').checked,
      corrections: document.getElementById('optCorrections').checked,
      allCorrections: document.getElementById('optAllCorrections').checked
    };
  }

  function syncCorrectionOptions() {
    document.getElementById('optAllCorrections').disabled = !document.getElementById('optCorrections').checked;
  }

  function splitParagraphs(text) {
    return (text || '').split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  }

  // Source text: a word hyphenated at the page end (e.g. पाण्डुरित्ये-) joins the next page's first word
  function joinSourceAcrossPages(a, b) {
    if (!a) return b;
    if (!b) return a;
    return /[-‐‑–—]\s*$/.test(a) ? a.replace(/[-‐‑–—]\s*$/, '') + b : a + ' ' + b;
  }

  // Padaccheda: a page that continues a split word restates its head in parentheses, e.g.
  // "… सः अपि पाण्डुः इति ए-" + "(पाण्डुः इति ए)व अभ्यधायि" → "… सः अपि पाण्डुः इति एव अभ्यधायि".
  // Without a restated head, a trailing hyphen is a compound joint and the pages join directly.
  function joinPadacchedaAcrossPages(a, b) {
    if (!a) return b;
    if (!b) return a;
    if (!/-\s*$/.test(a)) return a + ' ' + b;
    const m = b.match(/^\(([^)]*)\)/);
    if (!m) return a.replace(/\s+$/, '') + b;
    const head = m[1].trim();
    const k = head.split(/\s+/).length;
    const prefix = a.replace(new RegExp(`(\\s*\\S+){${k}}\\s*$`), '');
    return (prefix ? prefix + ' ' : '') + head + b.slice(m[0].length);
  }

  // Paragraph pairs [source, padaccheda] for one page; if the paragraph counts differ the
  // whole page becomes a single pair so nothing is mismatched
  function pageParagraphPairs(item) {
    const src = splitParagraphs(item.sec1), pada = splitParagraphs(item.sec2);
    if (src.length === pada.length) return src.map((s, i) => [s, pada[i]]);
    return [[src.join('\n\n'), pada.join('\n\n')]];
  }

  // Escape for HTML and keep each danda on the line of the word before it
  function typesetHtml(text) {
    return escapeHtml(text).replace(/ +([।॥])/g, ' $1');
  }

  function isVerseOrShort(text) {
    const t = (text || '').trim();
    return t.includes('\n') || t.length < 40;
  }

  function normalizeSpace(text) {
    return (text || '').replace(/\s+/g, ' ').trim();
  }

  // Sentences ending in a danda (with any closing quote), plus any unterminated tail
  function splitSentences(text) {
    return (text || '').match(/[^।॥]*[।॥]+[’'"”]*\s*|[^।॥]+$/g) || [];
  }

  // Cut a long source/padaccheda paragraph pair into aligned chunks of a few sentences each.
  // Source and padaccheda have the same dandas, so chunk boundaries fall at the same sentence;
  // if the counts ever differ the pair is kept whole.
  const CHUNK_TARGET_CHARS = 320;
  function chunkParagraphPair(src, pada) {
    const ss = splitSentences(src), ps = splitSentences(pada);
    if (!pada || ss.length !== ps.length || ss.length < 2) return [[src, pada]];
    const chunks = [];
    let cs = '', cp = '';
    ss.forEach((sentence, i) => {
      cs += sentence; cp += ps[i];
      const isLast = i === ss.length - 1;
      if (isLast || cs.trim().length >= CHUNK_TARGET_CHARS) {
        chunks.push([cs.trim(), cp.trim()]);
        cs = ''; cp = '';
      }
    });
    // Fold a very short final chunk into the previous one
    if (chunks.length > 1 && chunks[chunks.length - 1][0].length < CHUNK_TARGET_CHARS / 3) {
      const [ls, lp] = chunks.pop();
      const prev = chunks[chunks.length - 1];
      prev[0] += ' ' + ls; prev[1] += ' ' + lp;
    }
    return chunks;
  }

  // Inline styles so the layout survives copy-paste into Word / Docs as well as export
  const SRC_PARA_STYLE = 'margin: 0 0 0.3em 0;';
  const PADA_CENTRED_STYLE = 'font-size: 0.84em; line-height: 1.75; color: #3b4a6b; text-align: center; text-indent: 0; margin: 0 0 0.9em 0;';
  const PADA_PARA_STYLE = 'font-size: 0.84em; line-height: 1.75; color: #3b4a6b; text-align: left; text-indent: 0; margin: 0 0 0.9em 1.2em; padding-left: 0.8em; border-left: 2px solid #c7d2fe;';

  // Pages included in the compiled book: front matter only when asked for
  function compiledPages(opts) {
    return data.filter(d => opts.frontMatter || !d.front);
  }

  // Consecutive pages sharing a section (Foreword, a parva, ...) are compiled together,
  // so text never runs on from one section into the next
  function groupBySection(pages) {
    const groups = [];
    pages.forEach(p => {
      const last = groups[groups.length - 1];
      if (last && last[0].section === p.section && last[0].front === p.front) last.push(p);
      else groups.push([p]);
    });
    return groups;
  }

  function buildCompiledBookData() {
    const compiled = compileBookBody();
    const opts = getModalOptions();
    const entries = correctionEntries(opts);
    document.getElementById('corrCount').innerText = `(${toDevanagariDigits(entries.length)})`;
    if (!opts.corrections || !entries.length || !compiled.toc.length) return compiled;
    const appendix = correctionsAppendix(entries, opts);
    return {
      plain: `${compiled.plain.trimEnd()}\n\n${appendix.plain}\n`,
      html: `${compiled.html}\n${appendix.html}`,
      toc: [...compiled.toc, { id: 'bk-corrections', label: CORRECTIONS_TITLE, range: '', appendix: true }]
    };
  }

  /* ---------- Corrections appendix ----------
     Every change the reviewer made, from the same log that is saved with each page. Misprints
     in the book are always listed (they are the edition's emendations); OCR misreadings and
     padaccheda corrections only when asked for. */
  const CORRECTIONS_TITLE = 'परिशिष्टम् — संशोधनसूची (Appendix: List of Corrections)';
  const CORRECTION_SECTIONS = [
    { category: 'misprint', title: '⚠️ मुद्रणदोषाः (Misprints in the Book)',
      intro: 'मुद्रितः पाठः मूलपाठे यथावत् रक्षितः; शुद्धः पाठः अत्र दीयते (The printed reading is kept in the text; the correct reading is given here).',
      before: 'मुद्रितः पाठः (Printed)', after: 'शुद्धः पाठः (Correct)' },
    { category: 'ocr', title: '🔍 OCR-दोषाः (OCR Misreadings Corrected)',
      intro: 'यन्त्रेण अशुद्धं पठितम्, संशोधकेन स्कैन्-अनुसारं शोधितम् (Words the OCR misread, corrected against the scan).',
      before: 'OCR-पाठः (OCR read)', after: 'शोधितः (Corrected)' },
    { category: 'pada', title: '✂️ पदच्छेदसंशोधनानि (Padaccheda Corrections)',
      intro: 'AI-कृते पदच्छेदे संशोधनानि (Corrections to the AI\'s sandhi and compound splitting).',
      before: 'AI-पदच्छेदः (AI split)', after: 'शोधितः (Corrected)' },
    { category: 'other', title: '✏️ अन्यानि संशोधनानि (Other Edits)',
      intro: '', before: 'पूर्वपाठः (Before)', after: 'शोधितः (After)' }
  ];

  function correctionEntries(opts) {
    const entries = [];
    compiledPages(opts).forEach(item => {
      ensureBaseline(item);
      changeLogEntries(pageChanges(item), item).forEach(e => {
        if (e.category !== 'misprint' && !opts.allCorrections) return;
        if (e.section === 'sec2' && !opts.sec2) return;   // padaccheda not in this export
        if ((e.before || '').trim() === (e.after || '').trim()) return;   // spacing only
        entries.push({ ...e, item });
      });
    });
    return entries;
  }

  function correctionsAppendix(entries, opts) {
    const html = [`<h1 class="book-part-heading" id="bk-corrections"><a name="bk-corrections"></a>${CORRECTIONS_TITLE}</h1>`];
    const plain = [CORRECTIONS_TITLE];
    const shown = w => w ? escapeHtml(w) : '∅';
    CORRECTION_SECTIONS.forEach(s => {
      const rows = entries.filter(e => e.category === s.category);
      if (!rows.length) return;
      html.push(`<h3 class="book-notes-heading">${s.title}</h3>`);
      plain.push('', s.title);
      if (s.intro) {
        html.push(`<p class="corr-intro">${escapeHtml(s.intro)}</p>`);
        plain.push(s.intro);
      }
      html.push(`<table class="scholarly-table corr-table"><thead><tr><th>क्रमः (No.)</th><th>स्थानम् (Page)</th>` +
        `<th>${s.before}</th><th>${s.after}</th><th>सन्दर्भः (Context)</th><th>टिप्पणी (Note)</th></tr></thead><tbody>`);
      rows.forEach((e, i) => {
        const where = `${pageLabel(e.item)} (PDF ${e.item.page})${e.section === 'sec2' ? ' · पदच्छेदः' : ''}`;
        const context = `…${escapeHtml(e.context_before)} [${shown(e.before)} → ${shown(e.after)}] ${escapeHtml(e.context_after)}…`;
        const note = [e.note, e.source === 'ai' ? 'AI-सूचना स्वीकृता (AI suggestion accepted)' : ''].filter(Boolean).join('; ');
        html.push(`<tr><td>${toDevanagariDigits(i + 1)}</td><td>${escapeHtml(where)}</td><td>${shown(e.before)}</td>` +
          `<td>${shown(e.after)}</td><td>${context}</td><td>${escapeHtml(note)}</td></tr>`);
        plain.push(`${i + 1}. ${where}: ${e.before || '∅'} → ${e.after || '∅'}  (…${e.context_before} [${e.before || '∅'} → ${e.after || '∅'}] ${e.context_after}…)${note ? '  — ' + note : ''}`);
      });
      html.push('</tbody></table>');
    });
    return { html: html.join('\n'), plain: plain.join('\n') };
  }

  function compileBookBody() {
    if (data[currentIndex]) {
      data[currentIndex].sec1 = sec1Editor.value;
      data[currentIndex].sec2 = sec2Editor.value;
    }
    const opts = getModalOptions();
    if (!opts.sec1 && !opts.sec2 && !opts.sec3) {
      return {
        plain: 'कृपया न्यूनातिन्यूनम् एकं विभागं चिनोतु (Please select at least one section above).',
        html: '<p class="empty-note">कृपया न्यूनातिन्यूनम् एकं विभागं चिनोतु (Please select at least one section above).</p>',
        toc: []
      };
    }

    // Each section (Foreword, a parva, ...) gets a heading and a TOC entry with its printed page range
    const pages = compiledPages(opts);
    const parts = { front: [], main: [] };
    const toc = [];
    groupBySection(pages).forEach((group, k) => {
      const part = compileSectionGroup(group, opts);
      if (group[0].lang === 'en') part.html = `<div class="book-en" lang="en">${part.html}</div>`;
      const id = `bk-sec-${k + 1}`;
      const label = group[0].section || pageLabel(group[0]);
      part.html = `<h2 class="book-section-heading" id="${id}"><a name="${id}"></a>${escapeHtml(label)}</h2>\n${part.html}`;
      part.plain = `॥ ${label} ॥\n\n${part.plain}`;
      toc.push({ id, label, range: sectionPageRange(group), front: group[0].front });
      parts[group[0].front ? 'front' : 'main'].push(part);
    });

    const joinParts = list => ({
      plain: list.map(p => p.plain.trim()).join('\n\n'),
      html: list.map(p => p.html).join('\n')
    });
    const front = joinParts(parts.front), main = joinParts(parts.main);
    if (!parts.front.length) return { plain: main.plain + '\n', html: main.html, toc };
    const partHeading = (id, title) => `<h1 class="book-part-heading" id="${id}"><a name="${id}"></a>${title}</h1>`;
    return {
      plain: `${PART_TITLES.front}\n\n${front.plain}\n\n${PART_TITLES.main}\n\n${main.plain}\n`,
      html: [partHeading('bk-part-front', PART_TITLES.front), front.html,
             partHeading('bk-part-main', PART_TITLES.main), main.html].join('\n'),
      toc
    };
  }

  const PART_TITLES = { front: 'प्रस्तावनादि (Front Matter)', main: 'मूलग्रन्थः (Main Text)' };

  // Printed page range covered by a section: "पृ. १–१८" for the main text, "iii–vii" for front matter
  function sectionPageRange(group) {
    const nums = group.map(p => p.book_page).filter(Boolean);
    if (!nums.length) return '';
    const first = nums[0], last = nums[nums.length - 1];
    const range = first === last ? first : `${first}–${last}`;
    return group[0].lang === 'en' ? range : `पृ. ${range}`;
  }

  // Linked table of contents (works as hyperlinks in Word and as internal links in the PDF)
  function buildTocHtml(toc) {
    if (!toc.length) return '';
    const hasFront = toc.some(t => t.front);
    const rows = [];
    let lastPart = null;
    toc.forEach(t => {
      if (t.appendix) {
        rows.push(`<tr class="toc-part"><td colspan="2"><a href="#${t.id}">${escapeHtml(t.label)}</a></td></tr>`);
        return;
      }
      if (hasFront && t.front !== lastPart) {
        const partId = t.front ? 'bk-part-front' : 'bk-part-main';
        rows.push(`<tr class="toc-part"><td colspan="2"><a href="#${partId}">${t.front ? PART_TITLES.front : PART_TITLES.main}</a></td></tr>`);
        lastPart = t.front;
      }
      rows.push(`<tr><td class="toc-label"><a href="#${t.id}">${escapeHtml(t.label)}</a></td><td class="toc-pages">${escapeHtml(t.range)}</td></tr>`);
    });
    return `<div class="book-toc"><h2 class="book-toc-title" id="bk-toc"><a name="bk-toc"></a>अनुक्रमणिका (Table of Contents)</h2>
<table class="toc-table">${rows.join('\n')}</table></div>`;
  }

  function buildTitlePageHtml(opts) {
    const pages = compiledPages(opts);
    const included = [opts.sec1 && 'मूलपाठः', opts.sec2 && 'पदच्छेदः', opts.sec3 && 'सम्पादनटिप्पण्यः'].filter(Boolean).join(' · ');
    const range = pages.length ? `PDF ${pages[0].page}–${pages[pages.length - 1].page}` : '';
    const date = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
    return `<div class="title-page">
<p class="tp-shri">॥ श्रीः ॥</p>
<p class="tp-author">महामहोपाध्याय-श्रीमल्लक्ष्मणसूरिविरचितः</p>
<h1 class="tp-title">भारतसङ्ग्रहः</h1>
<p class="tp-latin">Bhārata Saṅgraha<br>by Mahāmahopādhyāya M. Lakshmana Suri</p>
<p class="tp-meta">${included}<br>${range} · शोधनप्रतिः (Proofreading draft) · ${date}</p>
</div>`;
  }

  /* Review flags in exports: open flags are wrapped in private-use sentinel characters before
     compiling, so they survive page joins and chunking, then become marks with a ⚑n reference */
  const FLAG_SENTINEL = /([a-z]+)(\d+)([\s\S]*?)/g;
  const REVIEW_MARK_STYLE = {
    ocr: 'background: #fee2e2; border-bottom: 2px solid #dc2626;',
    print: 'background: #fef3c7; border-bottom: 2px solid #d97706;',
    verify: 'background: #dbeafe; border-bottom: 2px dotted #2563eb;',
    pada: 'background: #f3e8ff; border-bottom: 2px solid #9333ea;',
    mine: 'background: #ccfbf1; border-bottom: 2px solid #0d9488;',
    askai: 'background: #e0e7ff; border-bottom: 2px solid #4f46e5;',
    reply: 'background: #d1fae5; border-bottom: 2px dotted #059669;'
  };

  function markFlagsForExport(item, opts, review) {
    const marked = { ...item };
    const markFlags = itemMarks(item).map(m => ({ section: m.section, match: m.match, kind: m.target, note: m.note }));
    [...markFlags, ...(item.flags || [])].forEach(f => {
      if (!opts[f.section] || !isFlagOpen(item, f)) return;
      const text = marked[f.section];
      const at = text.indexOf(f.match);
      if (at === -1) return;
      const n = review.length + 1;
      review.push({ n, item, f });
      marked[f.section] = text.slice(0, at) + `${f.kind}${n}${f.match}` + text.slice(at + f.match.length);
    });
    return marked;
  }

  function reviewMarksHtml(html) {
    return html.replace(FLAG_SENTINEL, (_, kind, n, word) =>
      `<mark class="review-flag" data-kind="${kind}" style="${REVIEW_MARK_STYLE[kind] || ''} color: inherit;">${word}</mark><sup class="review-ref" style="color: #991b1b; font-size: 0.6em;">⚑${toDevanagariDigits(n)}</sup>`);
  }

  function reviewMarksPlain(text) {
    return text.replace(FLAG_SENTINEL, (_, kind, n, word) => `${word}[⚑${n}]`);
  }

  // "Words to review" list closing a section: number, page, word → suggestion, kind and note
  function reviewListBlocks(review) {
    const html = [`<h3 class="book-notes-heading review-heading">⚑ समीक्षणीयानि पदानि (Words to Review)</h3>`];
    const plain = ['⚑ समीक्षणीयानि पदानि (Words to Review)'];
    review.forEach(({ n, item, f }) => {
      const where = `${pageLabel(item)} (PDF ${item.page})${f.section === 'sec2' ? ' · पदच्छेदः' : ''}`;
      const words = `<mark class="review-flag" data-kind="${f.kind}" style="${REVIEW_MARK_STYLE[f.kind] || ''} color: inherit;">${escapeHtml(f.match)}</mark>` +
        (f.suggest ? ` → ${escapeHtml(f.suggest)}` : '');
      html.push(`<p class="review-item"><span class="review-num">⚑${toDevanagariDigits(n)}</span> ${words} <span class="review-where">— ${escapeHtml(where)} · ${escapeHtml(FLAG_KIND_LABEL[f.kind] || f.kind)}</span><br><span class="review-note">${escapeHtml(f.note || '')}</span></p>`);
      plain.push(`⚑${n} ${f.match}${f.suggest ? ' → ' + f.suggest : ''} — ${where} · ${FLAG_KIND_LABEL[f.kind] || f.kind}\n    ${f.note || ''}`);
    });
    return { html, plain };
  }

  function compileSectionGroup(pages, opts) {
    // Continuous flow (paragraphs joined across page breaks) unless page numbers are shown or joining is off
    const continuous = opts.mergeHyphens && !opts.showPageNums;
    const plainBlocks = [], htmlBlocks = [];
    const review = [];
    if (opts.reviewFlags) pages = pages.map(item => markFlagsForExport(item, opts, review));
    const fmt = p => reviewMarksHtml(typesetHtml(p));

    const renderPairs = pairs => {
      pairs.forEach(([s, d]) => {
        const html = [], plain = [];
        const chunks = (opts.sec1 && opts.sec2) ? chunkParagraphPair(s, d) : [[s, d]];
        // Verses and short lines (invocations, headings) are centred as in the printed book;
        // prose paragraphs get a first-line indent
        const centred = isVerseOrShort(s);
        chunks.forEach(([cs, cd], ci) => {
          if (opts.sec1) {
            splitParagraphs(cs).forEach(p => {
              const layout = centred ? 'text-align: center; ' : (ci === 0 ? 'text-indent: 1.5em; ' : '');
              html.push(`<p class="src-para" style="${layout}${opts.sec2 ? SRC_PARA_STYLE : ''}">${fmt(p)}</p>`);
              plain.push(reviewMarksPlain(p));
            });
          }
          // Skip the padaccheda where it repeats the source verbatim (e.g. श्रीः)
          if (opts.sec2 && !(opts.sec1 && normalizeSpace(cd) === normalizeSpace(cs))) {
            splitParagraphs(cd).forEach(p => {
              const style = centred ? PADA_CENTRED_STYLE : PADA_PARA_STYLE;
              html.push(opts.sec1 ? `<p class="pada-para" style="${style}">${fmt(p)}</p>` : `<p style="${centred ? 'text-align: center;' : ''}">${fmt(p)}</p>`);
              const pp = reviewMarksPlain(p);
              plain.push(opts.sec1 ? pp.split('\n').map(line => '    ' + line).join('\n') : pp);
            });
          }
        });
        if (html.length) {
          htmlBlocks.push(`<div class="para-pair" style="margin-bottom: 1.6em;">${html.join('\n')}</div>`);
          plainBlocks.push(plain.join('\n'));
        }
      });
    };

    const notesTable = item => (item.sec3_md || '').trim() ? (item.sec3_html || '') : '';

    if (continuous) {
      if (opts.sec1 || opts.sec2) {
        const pairs = [];
        pages.forEach(item => {
          const pagePairs = pageParagraphPairs(item);
          if (pairs.length && pagePairs.length) {
            const last = pairs[pairs.length - 1], first = pagePairs.shift();
            last[0] = joinSourceAcrossPages(last[0], first[0]);
            last[1] = joinPadacchedaAcrossPages(last[1], first[1]);
          }
          pairs.push(...pagePairs);
        });
        renderPairs(pairs);
      }
      // Editorial notes gathered at the end of the section, labelled by page
      if (opts.sec3) {
        const noted = pages.filter(notesTable);
        if (noted.length) {
          htmlBlocks.push(`<h3 class="book-notes-heading">सम्पादनटिप्पण्यः (Editorial Notes)</h3>`);
          plainBlocks.push('सम्पादनटिप्पण्यः (Editorial Notes)');
          noted.forEach(item => {
            htmlBlocks.push(`<div class="book-notes-page">${escapeHtml(pageLabel(item))} (PDF ${item.page})</div>\n${notesTable(item)}`);
            plainBlocks.push(`[${pageLabel(item)}]\n${item.sec3_md.trim()}`);
          });
        }
      }
    } else {
      pages.forEach(item => {
        if (opts.showPageNums) {
          plainBlocks.push(`[${pageLabel(item)}]`);
          htmlBlocks.push(`<h3 class="book-page-divider">${escapeHtml(pageLabel(item))} (PDF ${item.page})</h3>`);
        }
        if (opts.sec1 || opts.sec2) renderPairs(pageParagraphPairs(item));
        if (opts.sec3 && notesTable(item)) {
          htmlBlocks.push(`<div class="book-notes-page">सम्पादनटिप्पण्यः</div>\n${notesTable(item)}`);
          plainBlocks.push(`सम्पादनटिप्पण्यः\n${item.sec3_md.trim()}`);
        }
      });
    }

    if (review.length) {
      const list = reviewListBlocks(review);
      htmlBlocks.push(...list.html);
      plainBlocks.push(list.plain.join('\n'));
    }

    return {
      plain: plainBlocks.join('\n\n') + '\n',
      html: htmlBlocks.join('\n')
    };
  }

  // Key to the two text styles, shown when source and padaccheda are interleaved
  function buildReadingKeyHtml(opts) {
    if (!(opts.sec1 && opts.sec2)) return '';
    return `<div class="reading-key">
<div class="reading-key-title">पठनसङ्केतः (How to read)</div>
<p class="src-para" style="${SRC_PARA_STYLE}">मूलपाठः — <span class="key-gloss">the original text, as printed.</span></p>
<p class="pada-para" style="${PADA_PARA_STYLE}">पदच्छेदः — <span class="key-gloss">the same paragraph with sandhi and compounds separated, set beneath it.</span></p>
</div>`;
  }

  function refreshCompiledView() {
    const compiled = buildCompiledBookData();
    bookPreviewSheet.innerHTML = buildTocHtml(compiled.toc) + buildReadingKeyHtml(getModalOptions()) + compiled.html;
  }

  function openAllPagesModal() {
    refreshCompiledView();
    allPagesModal.classList.add('open');
  }

  function closeAllPagesModal() {
    allPagesModal.classList.remove('open');
  }

  function handleBackdropClick(e) {
    if (e.target === allPagesModal) {
      closeAllPagesModal();
    }
  }

  function copyCompiledBook() {
    const compiled = buildCompiledBookData();
    const richHtml = `<div style="font-family: ${textFontStack()}; font-size: 15pt; line-height: 1.9; color: #111;">${compiled.html}</div>`;
    copyToClipboard(compiled.plain, `✔ सम्पूर्णः पाठः प्रतिकृतः — Word / Docs मध्ये स्थापयतु (Copied! Paste anywhere)`, richHtml);
  }

  const BOOK_TITLE = 'श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः';

  // Title page, table of contents, reading key and text: shared by the PDF and Word exports
  function buildExportBodyHtml() {
    const compiled = buildCompiledBookData();
    const opts = getModalOptions();
    return [buildTitlePageHtml(opts), buildTocHtml(compiled.toc), buildReadingKeyHtml(opts), compiled.html].join('\n');
  }

  function buildExportDocumentHtml() {
    return buildStandaloneDocumentHtml(BOOK_TITLE, buildExportBodyHtml());
  }

  function buildStandaloneDocumentHtml(title, bodyHtml) {
    return `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40" lang="sa">
<head>
<meta charset="UTF-8">
<title>${title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tiro+Devanagari+Sanskrit:ital@0;1&family=Martel:wght@400;600;800&family=Sahitya:wght@400;700&family=Noto+Serif+Devanagari:wght@400;600;700&family=Noto+Serif:ital,wght@0,400;0,600;1,400&display=swap">
<style>
  @page {
    size: A4;
    margin: 2.2cm;
    @bottom-center { content: counter(page); font-family: 'Noto Serif', Georgia, serif; font-size: 10pt; color: #666666; }
  }
  @page :first { @bottom-center { content: none; } }
  body {
    font-family: ${textFontStack()};
    font-size: 15.5pt;
    line-height: 1.95;
    color: #111827;
    max-width: 780px;
    margin: 0 auto;
    padding: 20px;
  }
  p { margin: 0 0 14pt 0; text-align: justify; white-space: pre-wrap; }
  .title-page { text-align: center; padding-top: 18%; page-break-after: always; }
  .title-page p { text-align: center; white-space: normal; }
  .tp-shri { font-size: 16pt; }
  .tp-author { font-size: 17pt; margin-top: 48pt; }
  h1, h2, h3 { font-weight: normal; }
  .tp-title { font-size: 40pt; color: #7c2d12; margin: 6pt 0 36pt 0; }
  .tp-latin { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; font-size: 13pt; line-height: 1.5; }
  .tp-meta { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; font-size: 10.5pt; line-height: 1.6; color: #555555; margin-top: 72pt; }
  .book-toc-title { font-size: 22pt; color: #7c2d12; text-align: center; margin: 0 0 18pt 0; }
  table.toc-table { border-collapse: collapse; width: 100%; margin: 0; font-size: 14pt; }
  table.toc-table td { border: none; padding: 3pt 0; }
  table.toc-table a { color: #111827; text-decoration: none; }
  .toc-pages { text-align: right; white-space: nowrap; color: #555555; }
  .toc-part td { color: #7c2d12; padding-top: 12pt; }
  h1.book-part-heading {
    font-size: 30pt;
    color: #7c2d12;
    text-align: center;
    padding-top: 30%;
    page-break-before: always;
  }
  h2.book-section-heading {
    font-size: 24pt;
    color: #7c2d12;
    text-align: center;
    margin: 0 0 18pt 0;
    padding-bottom: 6pt;
    border-bottom: 1px solid #fed7aa;
    page-break-before: always;
    page-break-after: avoid;
  }
  h3.book-page-divider {
    font-size: 12pt;
    color: #9a3412;
    margin-top: 18pt;
    margin-bottom: 6pt;
    border-bottom: 1px solid #fed7aa;
    page-break-after: avoid;
  }
  .reading-key { border: 1px solid #e7e5e4; padding: 8pt 14pt 0 14pt; margin: 24pt 0 0 0; font-size: 13pt; }
  .reading-key-title { color: #7c2d12; margin-bottom: 4pt; }
  .key-gloss { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; font-size: 10.5pt; color: #57534e; }
  .para-pair { page-break-inside: auto; }
  .src-para { page-break-after: avoid; }
  h3.book-notes-heading {
    font-size: 15pt;
    color: #7c2d12;
    margin: 28pt 0 6pt 0;
    padding-top: 10pt;
    border-top: 1px solid #e7e5e4;
    page-break-after: avoid;
  }
  .book-notes-page { font-size: 11pt; color: #9a3412; margin: 10pt 0 2pt 0; page-break-after: avoid; }
  h3.review-heading { color: #991b1b; }
  p.corr-intro { font-size: 12pt; line-height: 1.6; text-align: left; color: #57534e; }
  p.review-item { font-size: 12.5pt; line-height: 1.6; text-align: left; margin: 0 0 8pt 0; page-break-inside: avoid; }
  .review-num { color: #991b1b; }
  .review-where, .review-note { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; font-size: 10pt; color: #57534e; }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0 18pt 0;
    font-size: 11pt;
  }
  th, td {
    border: 1px solid #94a3b8;
    padding: 6pt 8pt;
    text-align: left;
    vertical-align: top;
  }
  th { background: #f1f5f9; font-weight: bold; }
  .book-en { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; line-height: 1.6; }
  .book-en p { text-align: left; }
</style>
</head>
<body>
${bodyHtml}
</body>
</html>`;
  }

  // "015_to_032" for the pages included in the compiled book
  function pageRangeTag() {
    const pages = compiledPages(getModalOptions());
    if (!pages.length) return 'empty';
    return `${pages[0].page}_to_${pages[pages.length - 1].page}`;
  }

  function downloadWordDoc() {
    const docx = buildDocx(buildExportBodyHtml());
    const filename = `bharata_sangraha_${pageRangeTag()}.docx`;
    triggerFileDownload(filename, docx, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    showToast(`📘 Word सञ्चिका (${filename}) अवतारिता!`);
  }

  /* ---------- Word (.docx) export ----------
     The export HTML (the same markup the PDF uses) is walked element by element and written
     out as WordprocessingML with named styles, then packed into a zip without compression. */

  function xmlEscape(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Word bookmark names allow letters, digits and underscores only
  function docxBookmarkName(id) {
    return id.replace(/[^A-Za-z0-9_]/g, '_');
  }

  // First family of the chosen text font, e.g. "Tiro Devanagari Sanskrit"
  function docxTextFont() {
    const chosen = getComputedStyle(document.documentElement).getPropertyValue('--font-family');
    return chosen.split(',')[0].replace(/['"]/g, '').trim() || 'Tiro Devanagari Sanskrit';
  }

  const DOCX_LATIN_FONT = 'Noto Serif';
  const DOCX_TEXT_WIDTH = 9412;  // A4 width minus 2.2 cm margins, in twips

  function docxRun(text, rPr) {
    const props = rPr ? `<w:rPr>${rPr}</w:rPr>` : '';
    return text.split('\n').map((line, i) =>
      (i ? `<w:r>${props}<w:br/></w:r>` : '') + (line ? `<w:r>${props}<w:t xml:space="preserve">${xmlEscape(line)}</w:t></w:r>` : '')
    ).join('');
  }

  // Inline content of an element as runs: bold, italic, English glosses, line breaks, links
  function docxRuns(node, rPr = '') {
    let out = '';
    node.childNodes.forEach(child => {
      if (child.nodeType === Node.TEXT_NODE) { out += docxRun(child.textContent, rPr); return; }
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      const tag = child.tagName.toLowerCase();
      if (tag === 'br') { out += '<w:r><w:br/></w:r>'; return; }
      let extra = '';
      if (tag === 'strong' || tag === 'b') extra = '<w:b/><w:bCs/>';
      else if (tag === 'em' || tag === 'i') extra = '<w:i/><w:iCs/>';
      else if (child.classList.contains('review-flag')) {
        const look = { ocr: ['FEE2E2', 'wave', 'DC2626'], print: ['FEF3C7', 'wave', 'D97706'], verify: ['DBEAFE', 'dotted', '2563EB'], pada: ['F3E8FF', 'wave', '9333EA'], mine: ['CCFBF1', 'wave', '0D9488'], askai: ['E0E7FF', 'wave', '4F46E5'], reply: ['D1FAE5', 'dotted', '059669'] }[child.dataset.kind] || ['FEF3C7', 'single', 'D97706'];
        extra = `<w:u w:val="${look[1]}" w:color="${look[2]}"/><w:shd w:val="clear" w:color="auto" w:fill="${look[0]}"/>`;
      }
      else if (child.classList.contains('review-ref')) extra = '<w:color w:val="991B1B"/><w:vertAlign w:val="superscript"/>';
      else if (child.classList.contains('review-where') || child.classList.contains('review-note')) {
        extra = `<w:rFonts w:ascii="${DOCX_LATIN_FONT}" w:hAnsi="${DOCX_LATIN_FONT}"/><w:color w:val="57534E"/><w:sz w:val="19"/><w:szCs w:val="19"/>`;
      }
      else if (child.classList.contains('review-num')) extra = '<w:color w:val="991B1B"/>';
      else if (child.classList.contains('key-gloss')) {
        extra = `<w:rFonts w:ascii="${DOCX_LATIN_FONT}" w:hAnsi="${DOCX_LATIN_FONT}"/><w:color w:val="57534E"/><w:sz w:val="20"/><w:szCs w:val="20"/>`;
      }
      const inner = docxRuns(child, rPr + extra);
      if (tag === 'a' && (child.getAttribute('href') || '').startsWith('#')) {
        out += `<w:hyperlink w:anchor="${docxBookmarkName(child.getAttribute('href').slice(1))}" w:history="1">${inner}</w:hyperlink>`;
      } else {
        out += inner;
      }
    });
    return out;
  }

  let docxBookmarkId = 0;
  function docxParagraph(style, runs, { jc = '', firstLine = false, bookmark = '' } = {}) {
    const pPr = `<w:pPr><w:pStyle w:val="${style}"/>${firstLine ? '<w:ind w:firstLine="420"/>' : ''}${jc ? `<w:jc w:val="${jc}"/>` : ''}</w:pPr>`;
    if (!bookmark) return `<w:p>${pPr}${runs}</w:p>`;
    const id = ++docxBookmarkId;
    return `<w:p>${pPr}<w:bookmarkStart w:id="${id}" w:name="${docxBookmarkName(bookmark)}"/>${runs}<w:bookmarkEnd w:id="${id}"/></w:p>`;
  }

  function docxTable(table) {
    const rows = [...table.querySelectorAll('tr')];
    const cols = Math.max(1, ...rows.map(r => r.children.length));
    const colW = Math.floor(DOCX_TEXT_WIDTH / cols);
    const border = side => `<w:${side} w:val="single" w:sz="4" w:space="0" w:color="94A3B8"/>`;
    const xmlRows = rows.map(tr => {
      const isHeader = tr.parentElement && tr.parentElement.tagName.toLowerCase() === 'thead';
      const cells = [...tr.children].map(td => {
        const shade = isHeader ? '<w:shd w:val="clear" w:color="auto" w:fill="F1F5F9"/>' : '';
        return `<w:tc><w:tcPr><w:tcW w:w="${colW}" w:type="dxa"/>${shade}</w:tcPr>${docxParagraph('TableText', docxRuns(td, isHeader ? '<w:b/><w:bCs/>' : ''))}</w:tc>`;
      }).join('');
      return `<w:tr>${isHeader ? '<w:trPr><w:tblHeader/></w:trPr>' : ''}${cells}</w:tr>`;
    }).join('');
    return `<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>${['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].map(border).join('')}</w:tblBorders>` +
      `<w:tblCellMar><w:left w:w="90" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr>` +
      `<w:tblGrid>${'<w:gridCol w:w="' + colW + '"/>'.repeat(cols)}</w:tblGrid>${xmlRows}</w:tbl>` +
      docxParagraph('TableSpacer', '');
  }

  // Table of contents: a real Word TOC field (Right-click → Update Field adds page numbers),
  // pre-filled with linked entries and printed page ranges so it reads well before updating
  function docxToc(tocDiv) {
    const out = [];
    const title = tocDiv.querySelector('.book-toc-title');
    if (title) out.push(docxParagraph('TOCHeading', docxRuns(title)));
    const rows = [...tocDiv.querySelectorAll('tr')];
    rows.forEach((tr, i) => {
      const link = tr.querySelector('a');
      const pages = tr.querySelector('.toc-pages');
      const anchor = link ? docxBookmarkName((link.getAttribute('href') || '#').slice(1)) : '';
      let runs = docxRuns(link || tr) + (pages && pages.textContent ? `<w:r><w:tab/></w:r>${docxRun(pages.textContent, '')}` : '');
      if (anchor) runs = `<w:hyperlink w:anchor="${anchor}" w:history="1">${runs}</w:hyperlink>`;
      if (i === 0) runs = '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>' + runs;
      if (i === rows.length - 1) runs += '<w:r><w:fldChar w:fldCharType="end"/></w:r>';
      out.push(docxParagraph(tr.classList.contains('toc-part') ? 'TOC1' : 'TOC2', runs));
    });
    return out;
  }

  function docxBlocks(el, ctx) {
    const out = [];
    el.childNodes.forEach(node => {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.tagName.toLowerCase();
      const cls = node.classList;
      const style = node.getAttribute('style') || '';
      const centred = /text-align:\s*center/.test(style);
      const id = node.getAttribute('id') || '';

      if (cls.contains('title-page')) {
        const map = { 'tp-shri': 'TitleShri', 'tp-author': 'TitleAuthor', 'tp-title': 'Title', 'tp-latin': 'TitleLatin', 'tp-meta': 'TitleMeta' };
        [...node.children].forEach(c => {
          const s = Object.keys(map).find(k => c.classList.contains(k));
          if (s) out.push(docxParagraph(map[s], docxRuns(c)));
        });
        out.push('<w:p><w:r><w:br w:type="page"/></w:r></w:p>');
      } else if (cls.contains('book-toc')) {
        out.push(...docxToc(node));
      } else if (cls.contains('reading-key-title')) {
        out.push(docxParagraph('KeyTitle', docxRuns(node)));
      } else if (cls.contains('book-notes-page')) {
        out.push(docxParagraph('NotesPageLabel', docxRuns(node)));
      } else if (tag === 'table') {
        out.push(docxTable(node));
      } else if (tag === 'div') {
        out.push(...docxBlocks(node, cls.contains('book-en') ? { ...ctx, english: true } : ctx));
      } else if (tag === 'h1') {
        out.push(docxParagraph('Heading1', docxRuns(node), { bookmark: id }));
      } else if (tag === 'h2') {
        out.push(docxParagraph('Heading2', docxRuns(node), { bookmark: id }));
      } else if (tag === 'h3') {
        out.push(docxParagraph(cls.contains('book-notes-heading') ? 'NotesHeading' : 'Heading3', docxRuns(node), { bookmark: id }));
      } else if (tag === 'p') {
        if (cls.contains('review-item') || cls.contains('corr-intro')) {
          out.push(docxParagraph('ReviewItem', docxRuns(node)));
        } else if (cls.contains('pada-para')) {
          out.push(docxParagraph(centred ? 'PadacchedaCentred' : 'Padaccheda', docxRuns(node)));
        } else if (cls.contains('src-para')) {
          out.push(docxParagraph(ctx.english ? 'BodyEnglish' : 'SourceText', docxRuns(node),
            { jc: centred ? 'center' : '', firstLine: !centred && /text-indent/.test(style) }));
        } else {
          out.push(docxParagraph(ctx.english ? 'BodyEnglish' : 'SourceText', docxRuns(node), { jc: centred ? 'center' : '' }));
        }
      }
    });
    return out;
  }

  function docxStyles(font) {
    const fonts = (f, cs = font) => `<w:rFonts w:ascii="${f}" w:hAnsi="${f}" w:eastAsia="${f}" w:cs="${cs}"/>`;
    const size = hp => `<w:sz w:val="${hp}"/><w:szCs w:val="${hp}"/>`;
    const color = c => `<w:color w:val="${c}"/>`;
    const para = (id, name, { basedOn = 'Normal', next = '', pPr = '', rPr = '', outline = null, builtIn = false } = {}) =>
      `<w:style w:type="paragraph"${builtIn ? '' : ' w:customStyle="1"'} w:styleId="${id}"><w:name w:val="${name}"/>` +
      (basedOn ? `<w:basedOn w:val="${basedOn}"/>` : '') + (next ? `<w:next w:val="${next}"/>` : '') + '<w:qFormat/>' +
      `<w:pPr>${pPr}${outline !== null ? `<w:outlineLvl w:val="${outline}"/>` : ''}</w:pPr><w:rPr>${rPr}</w:rPr></w:style>`;
    const deep = '7C2D12', rust = '9A3412';
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults>
  <w:rPrDefault><w:rPr>${fonts(font)}${size(31)}<w:lang w:val="en-GB" w:eastAsia="en-GB" w:bidi="sa-IN"/></w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="384" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/><w:rPr>${color('111827')}</w:rPr></w:style>
${para('SourceText', 'Source Text', { pPr: '<w:spacing w:after="80"/><w:jc w:val="both"/>' })}
${para('Padaccheda', 'Padaccheda', { next: 'SourceText', pPr: '<w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="C7D2FE"/></w:pBdr><w:spacing w:after="240" w:line="360" w:lineRule="auto"/><w:ind w:left="567"/><w:jc w:val="left"/>', rPr: size(26) + color('3B4A6B') })}
${para('PadacchedaCentred', 'Padaccheda Centred', { basedOn: 'Padaccheda', pPr: '<w:pBdr><w:left w:val="nil"/></w:pBdr><w:ind w:left="0"/><w:jc w:val="center"/>' })}
${para('BodyEnglish', 'Body English', { pPr: '<w:spacing w:after="160" w:line="336" w:lineRule="auto"/><w:jc w:val="left"/>', rPr: fonts(DOCX_LATIN_FONT) + size(24) })}
${para('Heading1', 'heading 1', { builtIn: true, next: 'SourceText', outline: 0, pPr: '<w:keepNext/><w:pageBreakBefore/><w:spacing w:before="3600" w:after="240"/><w:jc w:val="center"/>', rPr: size(60) + color(deep) })}
${para('Heading2', 'heading 2', { builtIn: true, next: 'SourceText', outline: 1, pPr: '<w:keepNext/><w:pageBreakBefore/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="6" w:color="FED7AA"/></w:pBdr><w:spacing w:before="0" w:after="360"/><w:jc w:val="center"/>', rPr: size(48) + color(deep) })}
${para('Heading3', 'heading 3', { builtIn: true, next: 'SourceText', outline: 2, pPr: '<w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="2" w:color="FED7AA"/></w:pBdr><w:spacing w:before="360" w:after="120"/>', rPr: size(24) + color(rust) })}
${para('NotesHeading', 'Notes Heading', { next: 'NotesPageLabel', outline: 2, pPr: '<w:keepNext/><w:pBdr><w:top w:val="single" w:sz="4" w:space="8" w:color="E7E5E4"/></w:pBdr><w:spacing w:before="560" w:after="120"/>', rPr: size(30) + color(deep) })}
${para('NotesPageLabel', 'Notes Page Label', { pPr: '<w:keepNext/><w:spacing w:before="200" w:after="60"/>', rPr: size(22) + color(rust) })}
${para('TableText', 'Table Text', { pPr: '<w:spacing w:before="40" w:after="40" w:line="300" w:lineRule="auto"/>', rPr: size(20) })}
${para('TableSpacer', 'Table Spacer', { pPr: '<w:spacing w:after="120"/>', rPr: size(12) })}
${para('Title', 'Title', { builtIn: true, pPr: '<w:spacing w:before="120" w:after="720"/><w:jc w:val="center"/>', rPr: size(80) + color(deep) })}
${para('TitleShri', 'Title Shri', { pPr: '<w:spacing w:before="2400" w:after="0"/><w:jc w:val="center"/>', rPr: size(32) })}
${para('TitleAuthor', 'Title Author', { pPr: '<w:spacing w:before="960" w:after="0"/><w:jc w:val="center"/>', rPr: size(34) })}
${para('TitleLatin', 'Title Latin', { pPr: '<w:spacing w:after="0" w:line="300" w:lineRule="auto"/><w:jc w:val="center"/>', rPr: fonts(DOCX_LATIN_FONT) + size(26) })}
${para('TitleMeta', 'Title Meta', { pPr: '<w:spacing w:before="1440" w:after="0" w:line="300" w:lineRule="auto"/><w:jc w:val="center"/>', rPr: fonts(DOCX_LATIN_FONT) + size(21) + color('555555') })}
${para('TOCHeading', 'TOC Heading', { builtIn: true, pPr: '<w:spacing w:after="360"/><w:jc w:val="center"/>', rPr: size(44) + color(deep) })}
${para('TOC1', 'toc 1', { builtIn: true, pPr: `<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="${DOCX_TEXT_WIDTH}"/></w:tabs><w:spacing w:before="240" w:after="60"/>`, rPr: size(28) + color(deep) })}
${para('TOC2', 'toc 2', { builtIn: true, pPr: `<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="${DOCX_TEXT_WIDTH}"/></w:tabs><w:spacing w:after="60"/><w:ind w:left="360"/>`, rPr: size(28) })}
${para('ReviewItem', 'Review Item', { pPr: '<w:keepLines/><w:spacing w:after="160" w:line="312" w:lineRule="auto"/><w:jc w:val="left"/>', rPr: size(24) })}
${para('KeyTitle', 'Reading Key Title', { pPr: '<w:spacing w:before="480" w:after="120"/>', rPr: size(24) + color(deep) })}
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr>${color('1E3A8A')}</w:rPr></w:style>
</w:styles>`;
  }

  function buildDocx(bodyHtml) {
    docxBookmarkId = 0;
    const font = docxTextFont();
    const doc = new DOMParser().parseFromString(`<body>${bodyHtml}</body>`, 'text/html');
    const blocks = docxBlocks(doc.body, { english: false });
    const W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
    const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document ${W}><w:body>${blocks.join('\n')}<w:p/>
<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="11906" w:h="16838"/>
<w:pgMar w:top="1247" w:right="1247" w:bottom="1247" w:left="1247" w:header="708" w:footer="567" w:gutter="0"/><w:titlePg/></w:sectPr>
</w:body></w:document>`;
    const footerXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr ${W}><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="${DOCX_LATIN_FONT}" w:hAnsi="${DOCX_LATIN_FONT}"/><w:color w:val="666666"/><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>`;
    const settingsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:defaultTabStop w:val="720"/><w:characterSpacingControl w:val="doNotCompress"/>
<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>`;
    const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>`;
    const rootRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>`;
    const docRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>`;
    const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    const coreXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>${xmlEscape(BOOK_TITLE)}</dc:title><dc:language>sa</dc:language>
<dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>
</cp:coreProperties>`;
    return zipStore([
      ['[Content_Types].xml', contentTypes],
      ['_rels/.rels', rootRels],
      ['docProps/core.xml', coreXml],
      ['word/document.xml', documentXml],
      ['word/styles.xml', docxStyles(font)],
      ['word/settings.xml', settingsXml],
      ['word/_rels/document.xml.rels', docRels],
      ['word/footer1.xml', footerXml],
    ]);
  }

  /* Minimal zip writer (stored entries, no compression): enough for a .docx package */
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  function zipStore(entries) {
    const enc = new TextEncoder();
    const d = new Date();
    const dosTime = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    const dosDate = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    const chunks = [], central = [];
    let offset = 0;
    entries.forEach(([name, content]) => {
      const nameBytes = enc.encode(name), data = enc.encode(content), crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
      local.setUint16(8, 0, true); local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
      local.setUint16(26, nameBytes.length, true); local.setUint16(28, 0, true);
      chunks.push(new Uint8Array(local.buffer), nameBytes, data);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
      cen.setUint16(10, 0, true); cen.setUint16(12, dosTime, true); cen.setUint16(14, dosDate, true);
      cen.setUint32(16, crc, true); cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
      cen.setUint16(28, nameBytes.length, true); cen.setUint32(42, offset, true);
      central.push(new Uint8Array(cen.buffer), nameBytes);
      offset += 30 + nameBytes.length + data.length;
    });
    const centralSize = central.reduce((n, c) => n + c.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, entries.length, true); end.setUint16(10, entries.length, true);
    end.setUint32(12, centralSize, true); end.setUint32(16, offset, true);
    return new Blob([...chunks, ...central, new Uint8Array(end.buffer)]);
  }

  function printOrSavePdf() {
    const docHtml = buildExportDocumentHtml();
    const printWin = window.open('', '_blank');
    if (!printWin) {
      alert('कृपया Pop-up अनुमन्यताम् (Please allow pop-ups to print or save as PDF).');
      return;
    }
    printWin.document.open();
    printWin.document.write(docHtml);
    printWin.document.close();
    printWin.onload = () => {
      setTimeout(() => {
        printWin.focus();
        printWin.print();
      }, 350);
    };
  }

  function generateAllPagesMarkdownString() {
    if (data[currentIndex]) {
      data[currentIndex].sec1 = sec1Editor.value;
      data[currentIndex].sec2 = sec2Editor.value;
    }
    const opts = getModalOptions();
    const blocks = compiledPages(opts).map(item => buildPageMarkdown(item, opts).trim());
    return blocks.join('\n\n---\n\n') + '\n';
  }

  function downloadCompiledMarkdown() {
    const md = generateAllPagesMarkdownString();
    const filename = `bharata_sangraha_pages_${pageRangeTag()}.md`;
    triggerFileDownload(filename, md, 'text/markdown;charset=utf-8');
    showToast(`⬇ ${filename} अवतारितम् (Downloaded .md)`);
  }

  let saveResetTimer = null;
  function resetSaveButton() {
    saveBtn.innerText = '💾 रक्षतु (Save)';
    saveBtn.style.background = '';
  }

  async function saveVerifiedDirect() {
    const item = data[currentIndex];
    item.sec1 = sec1Editor.value;
    item.sec2 = sec2Editor.value;
    const saved = buildSavedMarkdown(item);
    const outContent = saved.content;

    saveBtn.innerText = '⏳ रक्षणं क्रियते... (Saving)';
    saveBtn.style.background = '#d97706';

    try {
      const res = await fetch(APPS_SCRIPT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify({
          page: item.page,
          content: outContent,
          // Structured copy of the correction log, for a backend that keeps a running log
          log: saved.log,
          saved_at: new Date().toISOString()
        })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // The backend replies {ok, github: {ok, error?}, drive: {ok, error?}}
      let reply = null;
      try { reply = JSON.parse(await res.text()); } catch (e) { /* older backend without a JSON reply */ }
      // An older Drive-only backend replies {status: "success" | "error", error?}
      if (reply && (reply.ok === false || reply.status === 'error')) {
        throw new Error(reply.error || (reply.github && reply.github.error) || (reply.drive && reply.drive.error) || 'unknown error');
      }
      const where = reply && reply.github && reply.github.ok
        ? (reply.drive && reply.drive.ok ? 'GitHub + Drive' : 'GitHub')
        : 'Drive';

      item.savedSnapshot = outContent;
      updateStatus();
      saveBtn.innerText = '✔ रक्षितम् (Saved!)';
      saveBtn.style.background = '#059669';
      showToast(where.startsWith('GitHub')
        ? `✔ ${pageLabel(item)} सुरक्षितम् (Saved to ${where}; the live site updates in about 2 minutes)`
        : `✔ ${pageLabel(item)} सुरक्षितम् (Saved to Drive)`);
      if (reply && reply.github && reply.github.ok && reply.drive && !reply.drive.ok) {
        console.warn('Drive backup failed:', reply.drive.error);
      }
      saveResetTimer = setTimeout(resetSaveButton, 2000);
    } catch (err) {
      alert("रक्षणे दोषः जातः (Save failed): " + err.message);
      resetSaveButton();
    }
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && allPagesModal.classList.contains('open')) {
      closeAllPagesModal();
      return;
    }
    if (e.altKey && (e.key === 'g' || e.key === 'G' || e.code === 'KeyG')) {
      e.preventDefault();
      togglePagePanel(true);
      return;
    }
    if (e.key === 'Escape' && !settingsMenu.hidden) {
      toggleSettings(false);
      settingsBtn.focus();
      return;
    }
    if (e.altKey && e.key === 'ArrowLeft') prevPage();
    if (e.altKey && e.key === 'ArrowRight') nextPage();
    if (!markDialog.hidden) {
      if (e.key === 'Escape') { closeMarkDialog(); return; }
      if (e.key === 'Enter') { e.preventDefault(); saveMark(); return; }
    }
    if (e.altKey && (e.key === 'm' || e.key === 'M' || e.code === 'KeyM')) {
      e.preventDefault();
      openMarkDialog(document.activeElement === sec2Editor ? 'sec2' : (document.activeElement === sec1Editor ? 'sec1' : lastEditorSec));
      return;
    }
    if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); gotoReview(1); }
    if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); gotoReview(-1); }
  });

  /* Movable Split Pane Resizer Logic */
  const paneResizer = document.getElementById('paneResizer');
  const imagePane = document.getElementById('imagePane');
  const mainContainer = document.querySelector('.main-container');
  let isResizingPanes = false;

  paneResizer.addEventListener('pointerdown', (e) => {
    isResizingPanes = true;
    paneResizer.classList.add('dragging');
    document.body.classList.add('resizing-panes');
    paneResizer.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  paneResizer.addEventListener('pointermove', (e) => {
    if (!isResizingPanes) return;
    const rect = mainContainer.getBoundingClientRect();
    let newLeftPct = ((e.clientX - rect.left) / rect.width) * 100;
    newLeftPct = Math.max(20, Math.min(80, newLeftPct));
    imagePane.style.width = newLeftPct.toFixed(2) + '%';
    autoResize(sec1Editor);
    autoResize(sec2Editor);
  });

  function stopPaneResize(e) {
    if (!isResizingPanes) return;
    isResizingPanes = false;
    paneResizer.classList.remove('dragging');
    document.body.classList.remove('resizing-panes');
    try {
      if (e && e.pointerId !== undefined) paneResizer.releasePointerCapture(e.pointerId);
    } catch (_) {}
  }

  paneResizer.addEventListener('pointerup', stopPaneResize);
  paneResizer.addEventListener('pointercancel', stopPaneResize);

  paneResizer.addEventListener('dblclick', () => {
    imagePane.style.width = '48%';
    autoResize(sec1Editor);
    autoResize(sec2Editor);
    showToast('समविभाजनम् स्थापितम् (Reset pane split)');
  });

  sec1Editor.addEventListener('focus', () => { lastEditorSec = 'sec1'; });
  sec2Editor.addEventListener('focus', () => { lastEditorSec = 'sec2'; });

  applySettings();
  if (data.length > 0) {
    const last = settings.rememberPage ? data.findIndex(d => d.page === settings.lastPage) : -1;
    switchPage(last !== -1 ? last : 0);
  }
</script>
</body>
</html>"""

def generate_viewer(standalone=False, verified_dir=VERIFIED_DIR, review_flags_json=REVIEW_FLAGS_JSON):
    md_files = sorted(glob.glob(os.path.join(RAW_DIR, "page_*.md")))
    if not md_files:
        print(f"[Error] No markdown files found in {RAW_DIR}/.")
        return

    review_flags = {}
    if os.path.exists(review_flags_json):
        with open(review_flags_json, "r", encoding="utf-8") as f:
            review_flags = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    pages_data = []
    for md_path in md_files:
        match = re.search(r"page_(\d+)\.md", os.path.basename(md_path))
        if not match:
            continue
        p_num = match.group(1)
        jpg_path = ensure_web_image(p_num)

        if not jpg_path:
            print(f"[Warning] No image for page {p_num} in {PAGE_IMAGES}/ or {WEB_IMAGE_DIR}/. Skipping.")
            continue

        with open(jpg_path, "rb") as img_f:
            img_bytes = img_f.read()
        if standalone:
            img_src = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("utf-8")
        else:
            # Content hash in the query string so browsers refetch a scan only when it changes
            img_src = f"{WEB_IMAGE_DIR}/page_{p_num}.jpg?v={hashlib.sha1(img_bytes).hexdigest()[:10]}"

        with open(md_path, "r", encoding="utf-8") as md_f:
            raw_text = md_f.read()

        sec1, sec2, sec3_md, sec3_html = parse_sections(raw_text)

        # A page the scholar has saved opens with the saved text; the raw OCR stays as the
        # baseline for proof marks, and the saved correction log restores the change tags
        extra = {}
        verified_path = os.path.join(verified_dir, f"page_{p_num}.md")
        if os.path.exists(verified_path):
            with open(verified_path, "r", encoding="utf-8") as v_f:
                verified_text = v_f.read()
            extra = {"verified": True, "orig_sec1": sec1, "orig_sec2": sec2,
                     "saved_log": parse_correction_log(verified_text),
                     "saved_marks": parse_review_marks(verified_text)}
            sec1, sec2, sec3_md, sec3_html = parse_sections(verified_text)

        pages_data.append({
            "page": p_num,
            **page_metadata(int(p_num)),
            "img": img_src,
            "sec1": sec1,
            "sec2": sec2,
            "sec3_md": sec3_md,
            "sec3_html": sec3_html,
            "flags": review_flags.get(p_num, []),
            **extra
        })

    json_data = json.dumps(pages_data, ensure_ascii=False)
    final_html = HTML_TEMPLATE.replace("<!-- JSON_DATA_PLACEHOLDER -->", json_data)
    final_html = final_html.replace("<!-- APPS_SCRIPT_URL_PLACEHOLDER -->", APPS_SCRIPT_URL)
    parvas = [{"name": name, "from": lo, "to": hi} for lo, hi, name in PARVAS]
    final_html = final_html.replace("<!-- PARVAS_PLACEHOLDER -->", json.dumps(parvas, ensure_ascii=False))

    output_html = STANDALONE_HTML if standalone else SITE_HTML
    os.makedirs(os.path.dirname(output_html) or ".", exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(final_html)
    verified_count = sum(1 for p in pages_data if p.get("verified"))
    print(f"[Success] Generated review portal: {output_html} (Loaded {len(pages_data)} pages, {verified_count} from {verified_dir}/)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the proofreading portal from output/raw/ and page images.")
    parser.add_argument("--standalone", action="store_true",
                        help=f"write a single offline file with embedded scans to {STANDALONE_HTML} instead of {SITE_HTML}")
    parser.add_argument("--verified-dir", default=VERIFIED_DIR,
                        help=f"folder of pages saved by the scholar, shown instead of the raw OCR (default: {VERIFIED_DIR})")
    parser.add_argument("--review-flags", default=REVIEW_FLAGS_JSON,
                        help=f"review flags file (default: {REVIEW_FLAGS_JSON})")
    args = parser.parse_args()
    generate_viewer(standalone=args.standalone, verified_dir=args.verified_dir, review_flags_json=args.review_flags)
