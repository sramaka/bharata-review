import os
import re
import glob
import json
import base64
import hashlib
import argparse

PAGE_IMAGES = "page_images"
RAW_DIR = "output/raw"

# Deployed site: index.html at the repo root loads page scans from WEB_IMAGE_DIR on demand
SITE_HTML = "index.html"
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

  /* Settings (font, size, copy) popover */
  .settings-wrap { position: relative; }
  .settings-btn { font-size: 17px; padding: 6px 10px; }
  .settings-menu {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 50;
    width: 290px;
    background: #ffffff;
    color: #1e293b;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.35);
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .menu-label {
    font-size: 13px;
    font-weight: 600;
    color: #475569;
  }
  .menu-row { display: flex; align-items: center; gap: 6px; }
  .settings-menu select, .settings-menu button, .settings-menu input {
    background: #f8fafc;
    color: #1e293b;
    border-color: #cbd5e1;
  }
  .settings-menu button:hover:not(:disabled), .settings-menu select:hover {
    background: #f1f5f9;
    border-color: #94a3b8;
  }
  .settings-menu select { width: 100%; }
  .menu-sep { height: 1px; background: #e2e8f0; margin: 4px 0; }
  .menu-item { justify-content: flex-start; width: 100%; white-space: normal; text-align: left; }

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
    background: #ffffff;
    color: #0f172a;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .sanskrit-editor:focus {
    border-color: #0284c7;
    box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
  }

  .lang-en .sanskrit-editor { font-family: 'Noto Serif', Georgia, 'Tiro Devanagari Sanskrit', serif; }

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
    display: block;
    width: 100%;
    text-align: left;
    background: #ffffff;
    color: #1c1917;
    border: 1px solid #fde68a;
    font-family: var(--font-family);
    font-size: calc(var(--font-size) * 0.85);
    line-height: 1.6;
    white-space: normal;
  }
  .change-item:hover:not(:disabled) { background: #fef9c3; border-color: #f59e0b; }
  .change-item .ctx { color: #78716c; }
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
  .book-sec-heading {
    font-family: var(--font-family);
    font-size: 0.9em;
    font-weight: 400;
    color: #1e3a8a;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 4px;
    margin: 16px 0 8px 0;
  }

  /* Toast Notification */
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
      <select id="pageSelect" onchange="switchPage(this.value)"></select>
      <button id="nextBtn" class="nav-btn" onclick="nextPage()">परम् ›</button>
    </div>

    <!-- Section Visibility Group -->
    <div class="toolbar-group" title="विभाग-दर्शनम् (Toggle Sections)">
      <button id="toggleSec2" class="section-toggle" onclick="toggleSection('sec2Box', 'toggleSec2')">+ पदच्छेदः</button>
      <button id="toggleSec3" class="section-toggle" onclick="toggleSection('sec3Box', 'toggleSec3')">+ टिप्पणी</button>
    </div>

    <div class="toolbar-spacer"></div>

    <button class="export-btn" onclick="openAllPagesModal()" title="सम्पूर्णं ग्रन्थं पश्यतु, प्रतिकुरुत, Word / PDF वा अवतारयतु (View, Copy, or Download Complete Book in Word / PDF)">
      📖 सम्पूर्णः ग्रन्थः
    </button>

    <!-- Display settings & copy actions -->
    <div class="settings-wrap" id="settingsWrap">
      <button id="settingsBtn" class="settings-btn" onclick="toggleSettings()" title="विन्यासाः (Font, size and copy options)" aria-haspopup="true" aria-expanded="false">⚙</button>
      <div id="settingsMenu" class="settings-menu" hidden>
        <div class="menu-label">लिपिः (Font)</div>
        <select id="fontSelect" onchange="changeFont(this.value)">
          <option value="'Tiro Devanagari Sanskrit', serif">Tiro Devanagari Sanskrit</option>
          <option value="Martel, serif">Martel</option>
          <option value="Sahitya, serif">Sahitya</option>
          <option value="'Noto Serif Devanagari', serif">Noto Serif</option>
          <option value="Siddhanta, serif">Siddhanta</option>
        </select>
        <div class="menu-label">अक्षराकारः (Text size)</div>
        <div class="menu-row">
          <button onclick="stepFontSize(-2)" title="अक्षराकारं न्यूनीकरोतु (Decrease Font Size)">A−</button>
          <input type="number" id="fontSizeInput" class="num-input" value="22" min="14" max="48" onchange="setFontSizeNumber(this.value)">
          <button onclick="stepFontSize(2)" title="अक्षराकारं वर्धयतु (Increase Font Size)">A+</button>
        </div>
        <div class="menu-sep"></div>
        <button class="menu-item" onclick="copySectionText('sec1')">📋 मूलपाठं प्रतिकुरुत (Copy page text)</button>
        <button class="menu-item" onclick="copyCurrentPageFormatted()">📑 सम्पूर्णं पृष्ठं प्रतिकुरुत (Copy page with notes)</button>
      </div>
    </div>

    <!-- Save to Cloud / Server -->
    <button id="saveBtn" class="save-btn" onclick="saveVerifiedDirect()" title="संशोधितं पृष्ठं रक्षतु (Save verified page)">
      💾 रक्षतु (Save)
    </button>
  </div>
</header>

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

    <!-- Section 1: Mulapatha -->
    <div class="card-container">
      <div class="card-header">
        <span id="sec1Label">१. मूलपाठः (Devanagari OCR Text)</span>
        <div class="card-header-right">
          <button class="light-btn" onclick="copySectionText('sec1')" title="Copy Mūlapāṭha text">📋 प्रतिकुरुत (Copy)</button>
          <button id="revertBtn" class="light-btn" style="display: none; color: #b91c1c; border-color: #fecaca;" onclick="revertCurrentPage()" title="मूलपाठं प्रत्यानयतु (Revert edits to original OCR)">↺ पूर्ववत् (Revert)</button>
        </div>
      </div>
      <textarea id="sec1Editor" class="sanskrit-editor" spellcheck="false" oninput="handleEdit()"></textarea>
    </div>

    <!-- Section 2: Padaccheda -->
    <div id="sec2Box" class="card-container collapsible-section">
      <div class="card-header" style="color: #1e3a8a; border-color: #bfdbfe;">
        <span>२. पदच्छेदसहितः पाठः (Sandhi-split Padaccheda)</span>
        <div class="card-header-right">
          <button class="light-btn" onclick="copySectionText('sec2')" title="Copy Padaccheda text">📋 प्रतिकुरुत (Copy)</button>
        </div>
      </div>
      <textarea id="sec2Editor" class="sanskrit-editor" spellcheck="false" oninput="handleSec2Edit()"></textarea>
    </div>

    <!-- Section 3: Apparatus -->
    <div id="sec3Box" class="card-container collapsible-section">
      <div class="card-header" style="color: #334155; border-color: #cbd5e1;">
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
          <input type="checkbox" id="optFrontMatter" onchange="refreshCompiledView()">
          प्रस्तावनादि (Front Matter)
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
        <button class="btn-export-light" onclick="downloadWordDoc()" title="Microsoft Word (.doc) सञ्चिकां अवतारयतु (Download Word Document)">
          📘 Word (.doc)
        </button>
        <button class="btn-export-light" onclick="printOrSavePdf()" title="PDF रूपेण रक्षतु अथवा मुद्रयतु (Save as PDF or Print)">
          🖨️ PDF / मुद्रणम्
        </button>
        <button class="btn-export-light" onclick="downloadCompiledMarkdown()" title="Markdown (.md) सञ्चिकां अवतारयतु">
          ⬇ .md
        </button>
      </div>
    </div>
    <div class="modal-body">
      <div id="bookPreviewSheet" class="book-preview-sheet"></div>
    </div>
  </div>
</div>

<!-- Toast Feedback -->
<div id="toast" class="toast"></div>

<script>
  const APPS_SCRIPT_URL = "<!-- APPS_SCRIPT_URL_PLACEHOLDER -->";
  const data = <!-- JSON_DATA_PLACEHOLDER -->;
  let currentIndex = 0;
  let currentZoom = 100;

  const select = document.getElementById('pageSelect');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const currentPageHeading = document.getElementById('currentPageHeading');
  const pagePdfNum = document.getElementById('pagePdfNum');
  const statusChip = document.getElementById('statusChip');
  const textPane = document.getElementById('textPane');
  const sec1Label = document.getElementById('sec1Label');
  const toggleSec2Btn = document.getElementById('toggleSec2');
  const settingsWrap = document.getElementById('settingsWrap');
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
    }, 2400);
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
    const changed = item.sec1 !== item.baseline || item.sec2 !== item.sec2Baseline;
    if (item.savedSnapshot !== undefined) {
      return buildPageMarkdown(item) === item.savedSnapshot ? 'saved' : 'edited';
    }
    return changed ? 'edited' : 'unreviewed';
  }

  function refreshPageOption(idx) {
    const item = data[idx];
    select.options[idx].text = `${STATUS_MARK[pageStatus(item)]}${pageLabel(item)}  (PDF ${item.page})`;
  }

  function updateStatus() {
    const status = pageStatus(data[currentIndex]);
    statusChip.className = `status-chip ${status}`;
    statusChip.innerText = STATUS_TEXT[status];
    refreshPageOption(currentIndex);
  }

  data.forEach((d, idx) => {
    let opt = document.createElement('option');
    opt.value = idx;
    select.appendChild(opt);
    refreshPageOption(idx);
  });

  function toggleSettings(forceOpen) {
    const open = forceOpen !== undefined ? forceOpen : settingsMenu.hidden;
    settingsMenu.hidden = !open;
    settingsBtn.setAttribute('aria-expanded', String(open));
  }
  document.addEventListener('click', (e) => {
    if (!settingsMenu.hidden && !settingsWrap.contains(e.target)) toggleSettings(false);
  });

  function switchPage(idx) {
    currentIndex = parseInt(idx, 10);
    select.value = currentIndex;
    const item = data[currentIndex];

    if (item.baseline === undefined) {
      item.baseline = item.sec1;
      item.sec2Baseline = item.sec2;
    }

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
    document.documentElement.style.setProperty('--font-size', num + 'px');
    autoResize(sec1Editor);
    autoResize(sec2Editor);
  }

  function stepFontSize(delta) {
    let cur = parseInt(fontSizeInput.value, 10) || 22;
    setFontSizeNumber(cur + delta);
  }

  function changeFont(fontFamily) {
    document.documentElement.style.setProperty('--font-family', fontFamily);
    autoResize(sec1Editor);
    autoResize(sec2Editor);
  }

  function toggleSection(elementId, btnId) {
    const el = document.getElementById(elementId);
    const btn = document.getElementById(btnId);
    const isVisible = el.classList.contains('visible');

    if (isVisible) {
      el.classList.remove('visible');
      btn.classList.remove('active');
      btn.innerText = btn.innerText.replace('−', '+');
    } else {
      el.classList.add('visible');
      btn.classList.add('active');
      btn.innerText = btn.innerText.replace('+', '−');
      if (elementId === 'sec2Box') autoResize(sec2Editor);
    }
  }

  function handleSec2Edit() {
    autoResize(sec2Editor);
    data[currentIndex].sec2 = sec2Editor.value;
    updateStatus();
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

    const changed = currentText !== item.baseline;
    revertBtn.style.display = changed ? 'inline-flex' : 'none';
    proofPanel.hidden = !changed;
    if (changed) renderProofMarks(diffTokens(tokenize(item.baseline), tokenize(currentText)));
    updateStatus();
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

  function renderProofMarks(ops) {
    // Group consecutive changed tokens into hunks, tracking their offsets in the edited text
    const hunks = [];
    let pos = 0, hunk = null;
    ops.forEach(([op, tok], k) => {
      if (op === '=') { hunk = null; pos += tok.length; return; }
      if (!hunk) { hunk = { first: k, last: k, del: '', ins: '', start: pos, end: pos }; hunks.push(hunk); }
      hunk.last = k;
      if (op === '-') hunk.del += tok;
      else { hunk.ins += tok; pos += tok.length; hunk.end = pos; }
    });

    const n = hunks.length;
    proofTitle.innerText = `दृष्टं शोधनम् — ${toDevanagariDigits(n)} परिवर्तन${n === 1 ? 'म्' : 'ानि'} (${n} change${n === 1 ? '' : 's'})`;

    proofList.innerHTML = hunks.map((h, idx) => {
      const before = escapeHtml(contextText(ops, h.first - 1, -1));
      const after = escapeHtml(contextText(ops, h.last + 1, 1));
      const del = h.del ? `<del>${escapeHtml(visibleToken(h.del))}</del>` : '';
      const ins = h.ins ? `<ins>${escapeHtml(visibleToken(h.ins))}</ins>` : '';
      return `<button class="change-item" onclick="jumpToChange(${h.start}, ${h.end})" title="पाठे दर्शयतु (Show in editor)"><span class="ctx">…${before}</span>${del}${del && ins ? ' → ' : ''}${ins}<span class="ctx">${after}…</span></button>`;
    }).join('');

    proofFull.innerHTML = ops.map(([op, tok]) => {
      if (op === '=') return escapeHtml(tok);
      return op === '-' ? `<del>${escapeHtml(visibleToken(tok))}</del>` : `<ins>${escapeHtml(tok)}</ins>`;
    }).join('');

    applyProofView();
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

  function jumpToChange(start, end) {
    sec1Editor.focus({ preventScroll: true });
    sec1Editor.setSelectionRange(start, Math.max(start, end));
    const paneRect = textPane.getBoundingClientRect();
    const editorTop = sec1Editor.getBoundingClientRect().top - paneRect.top + textPane.scrollTop;
    const target = editorTop + caretOffsetTop(sec1Editor, start) - paneRect.height / 3;
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
      sec1: document.getElementById('incSec1').checked,
      sec2: document.getElementById('incSec2').checked,
      sec3: document.getElementById('incSec3').checked
    };
  }

  function mergeContinuousTexts(pageTexts) {
    if (pageTexts.length === 0) return '';
    let result = pageTexts[0].trim();
    for (let i = 1; i < pageTexts.length; i++) {
      let nextText = pageTexts[i].trim();
      if (!nextText) continue;
      // If previous page ends with a hyphenated word (e.g. पाण्डुरित्ये-), join directly with next page's first word
      if (/[-‐‑–—]\s*$/.test(result)) {
        result = result.replace(/[-‐‑–—]\s*$/, '') + nextText;
      } else {
        result = result + ' ' + nextText;
      }
    }
    return result;
  }

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

  function compileSectionGroup(pages, opts) {
    // Continuous seamless mode when only Mulapatha (or Mulapatha without page headers) is selected with Join Split Words
    if (opts.mergeHyphens && !opts.showPageNums && opts.sec1 && !opts.sec2 && !opts.sec3) {
      const mergedSec1 = mergeContinuousTexts(pages.map(d => d.sec1 || ''));
      const paragraphs = mergedSec1.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
      const htmlParagraphs = paragraphs.map(p => `<p>${escapeHtml(p)}</p>`).join('\n');
      return {
        plain: paragraphs.join('\n\n') + '\n',
        html: htmlParagraphs
      };
    }

    let plainBlocks = [];
    let htmlBlocks = [];
    const multiSection = (opts.sec1 ? 1 : 0) + (opts.sec2 ? 1 : 0) + (opts.sec3 ? 1 : 0) > 1;

    for (let i = 0; i < pages.length; i++) {
      const item = pages[i];
      let pagePlain = [];
      let pageHtml = [];

      if (opts.showPageNums || multiSection) {
        pagePlain.push(`[${pageLabel(item)}]`);
        pageHtml.push(`<h3 class="book-page-divider">${escapeHtml(pageLabel(item))} (PDF ${item.page})</h3>`);
      }

      if (opts.sec1) {
        let s1 = (item.sec1 || '').trim();
        if (multiSection) {
          pagePlain.push(`१. मूलपाठः\n${s1}`);
          pageHtml.push(`<div class="book-sec-heading">१. मूलपाठः</div>`);
        } else {
          pagePlain.push(s1);
        }
        const paras = s1.split(/\n\s*\n/).map(p => `<p>${escapeHtml(p.trim())}</p>`).join('\n');
        pageHtml.push(paras);
      }

      if (opts.sec2) {
        let s2 = (item.sec2 || '').trim();
        if (multiSection || opts.sec1) {
          pagePlain.push(`२. पदच्छेदसहितः पाठः\n${s2}`);
          pageHtml.push(`<div class="book-sec-heading">२. पदच्छेदसहितः पाठः</div>`);
        } else {
          pagePlain.push(s2);
        }
        const paras2 = s2.split(/\n\s*\n/).map(p => `<p>${escapeHtml(p.trim())}</p>`).join('\n');
        pageHtml.push(paras2);
      }

      if (opts.sec3) {
        let s3 = (item.sec3_md || '').trim();
        pagePlain.push(`३. सम्पादनटिप्पण्यः\n${s3}`);
        pageHtml.push(`<div class="book-sec-heading">३. सम्पादनटिप्पण्यः</div>`);
        pageHtml.push(item.sec3_html || '');
      }

      plainBlocks.push(pagePlain.join('\n\n'));
      htmlBlocks.push(pageHtml.join('\n'));
    }

    return {
      plain: plainBlocks.join('\n\n') + '\n',
      html: htmlBlocks.join('\n')
    };
  }

  function refreshCompiledView() {
    const compiled = buildCompiledBookData();
    bookPreviewSheet.innerHTML = buildTocHtml(compiled.toc) + compiled.html;
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

  function buildExportDocumentHtml() {
    const compiled = buildCompiledBookData();
    const body = buildTitlePageHtml(getModalOptions()) + '\n' + buildTocHtml(compiled.toc) + '\n' + compiled.html;
    return buildStandaloneDocumentHtml('श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः', body);
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
  .book-sec-heading {
    font-size: 13.5pt;
    color: #1e3a8a;
    margin-top: 14pt;
    margin-bottom: 6pt;
  }
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
    const docHtml = '\ufeff' + buildExportDocumentHtml();
    const filename = `bharata_sangraha_${pageRangeTag()}.doc`;
    triggerFileDownload(filename, docHtml, 'application/msword;charset=utf-8');
    showToast(`📘 Word सञ्चिका (${filename}) अवतारिता!`);
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
    const outContent = buildPageMarkdown(item);

    saveBtn.innerText = '⏳ रक्षणं क्रियते... (Saving)';
    saveBtn.style.background = '#d97706';

    try {
      await fetch(APPS_SCRIPT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify({
          page: item.page,
          content: outContent
        })
      });

      item.savedSnapshot = outContent;
      updateStatus();
      saveBtn.innerText = '✔ रक्षितम् (Saved!)';
      saveBtn.style.background = '#059669';
      showToast(`✔ ${pageLabel(item)} सुरक्षितम् (Saved to Drive)`);
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
    if (e.key === 'Escape' && !settingsMenu.hidden) {
      toggleSettings(false);
      settingsBtn.focus();
      return;
    }
    if (e.altKey && e.key === 'ArrowLeft') prevPage();
    if (e.altKey && e.key === 'ArrowRight') nextPage();
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

  if (data.length > 0) switchPage(0);
</script>
</body>
</html>"""

def generate_viewer(standalone=False):
    md_files = sorted(glob.glob(os.path.join(RAW_DIR, "page_*.md")))
    if not md_files:
        print(f"[Error] No markdown files found in {RAW_DIR}/.")
        return

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

        pages_data.append({
            "page": p_num,
            **page_metadata(int(p_num)),
            "img": img_src,
            "sec1": sec1,
            "sec2": sec2,
            "sec3_md": sec3_md,
            "sec3_html": sec3_html
        })

    json_data = json.dumps(pages_data, ensure_ascii=False)
    final_html = HTML_TEMPLATE.replace("<!-- JSON_DATA_PLACEHOLDER -->", json_data)
    final_html = final_html.replace("<!-- APPS_SCRIPT_URL_PLACEHOLDER -->", APPS_SCRIPT_URL)

    output_html = STANDALONE_HTML if standalone else SITE_HTML
    os.makedirs(os.path.dirname(output_html) or ".", exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(final_html)
    print(f"[Success] Generated review portal: {output_html} (Loaded {len(pages_data)} pages)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the proofreading portal from output/raw/ and page images.")
    parser.add_argument("--standalone", action="store_true",
                        help=f"write a single offline file with embedded scans to {STANDALONE_HTML} instead of {SITE_HTML}")
    generate_viewer(standalone=parser.parse_args().standalone)
