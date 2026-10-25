import os
import re
import glob
import json
import base64

PAGE_IMAGES = "page_images"
RAW_DIR = "output/raw"
OUTPUT_HTML = "output/proofread_bundle.html"

# Paste your deployed Google Apps Script Web App URL here
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxrgtnxcAj0Z7skBCbaAeAEwwEpKUBXN9bzMuUq7LbdZbVOQaeEf30jL9DVUV476Bg/exec"

DEVANAGARI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")

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
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tiro+Devanagari+Sanskrit:ital@0;1&family=Noto+Serif+Devanagari:wght@400;500;600;700&display=swap">
<style>
  :root {
    --font-family: 'Tiro Devanagari Sanskrit', 'Noto Serif Devanagari', serif;
    --font-size: 22px;
    --line-height: 2.15;
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
  body {
    margin: 0;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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
    font-family: 'Noto Serif Devanagari', serif;
    font-size: 16px;
    font-weight: 700;
    color: var(--accent-gold);
    letter-spacing: 0.3px;
    white-space: nowrap;
  }
  .page-progress-pill {
    background: #0f172a;
    color: #94a3b8;
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 999px;
    border: 1px solid #334155;
    white-space: nowrap;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .toolbar-group {
    display: flex;
    align-items: center;
    gap: 5px;
    background: var(--bg-header-group);
    padding: 4px 6px;
    border-radius: 8px;
    border: 1px solid #334155;
  }
  .toolbar-label {
    font-size: 12px;
    color: #94a3b8;
    padding: 0 4px;
    white-space: nowrap;
  }

  button, select, input[type="number"] {
    background: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    outline: none;
    line-height: 1.3;
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
    width: 52px;
    text-align: center;
    font-weight: 600;
    color: #38bdf8;
    background: #0f172a;
    border-color: #0284c7;
    padding: 4px 6px;
  }

  .nav-btn { background: #0284c7; border-color: #0369a1; font-weight: 600; }
  .nav-btn:hover:not(:disabled) { background: #0369a1; border-color: #38bdf8; }

  .action-btn {
    background: #334155;
    border-color: #475569;
    color: #e2e8f0;
  }
  .action-btn.primary-outline {
    background: #1e293b;
    border-color: #0ea5e9;
    color: #38bdf8;
  }
  .action-btn.primary-outline:hover {
    background: #0284c7;
    color: #ffffff;
  }

  .export-btn {
    background: #7c3aed;
    border-color: #6d28d9;
    color: #ffffff;
    font-weight: 600;
  }
  .export-btn:hover {
    background: #6d28d9;
    border-color: #a78bfa;
  }

  .save-btn {
    background: var(--accent-green);
    border-color: #15803d;
    font-weight: 600;
    color: #ffffff;
    padding: 6px 14px;
  }
  .save-btn:hover { background: #15803d; border-color: #4ade80; }

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
    height: calc(100vh - 54px);
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
    font-family: 'Noto Serif Devanagari', serif;
    font-size: 1.05rem;
    font-weight: 700;
    color: #7c2d12;
  }
  .page-utility-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .light-btn {
    background: #f8fafc;
    color: #334155;
    border: 1px solid #cbd5e1;
    padding: 5px 10px;
    font-size: 12.5px;
    font-weight: 600;
    border-radius: 6px;
  }
  .light-btn:hover:not(:disabled) {
    background: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
  }
  .light-btn.amber {
    background: #fffbeb;
    color: #92400e;
    border-color: #fcd34d;
  }
  .light-btn.amber:hover {
    background: #fef3c7;
    border-color: #f59e0b;
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

  .diff-view-box {
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 8px;
    padding: 16px 18px;
    margin-top: 8px;
    font-family: var(--font-family);
    font-size: var(--font-size);
    line-height: var(--line-height);
    white-space: pre-wrap;
  }
  
  .mark-edited {
    background-color: #fef08a !important;
    color: #92400e !important;
    border-bottom: 2px dotted #d97706;
    padding: 2px 4px;
    border-radius: 3px;
    font-weight: 500;
  }

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
    font-family: 'Noto Serif Devanagari', system-ui, sans-serif;
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
  .btn-word {
    background: #1d4ed8;
    border-color: #1e40af;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 12px;
  }
  .btn-word:hover {
    background: #1e40af;
  }
  .btn-pdf {
    background: #b45309;
    border-color: #92400e;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 12px;
  }
  .btn-pdf:hover {
    background: #92400e;
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
  .book-page-divider {
    font-family: 'Noto Serif Devanagari', system-ui, sans-serif;
    font-size: 0.78em;
    font-weight: 700;
    color: #9a3412;
    background: #fff7ed;
    border: 1px solid #fed7aa;
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    margin: 14px 0 8px 0;
  }
  .book-sec-heading {
    font-family: 'Noto Serif Devanagari', system-ui, sans-serif;
    font-size: 0.85em;
    font-weight: 700;
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
  }
</style>
</head>
<body>

<header>
  <div class="brand-area">
    <div class="app-title">॥ श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः — शोधनपुटम् ॥</div>
    <span id="pageProgressPill" class="page-progress-pill">पृष्ठम् १ / १</span>
  </div>
  
  <div class="toolbar">
    <!-- Navigation Group -->
    <div class="toolbar-group" title="पृष्ठ-सञ्चालनम् (Page Navigation — Alt + Left/Right)">
      <button id="prevBtn" class="nav-btn" onclick="prevPage()">‹ पूर्वम्</button>
      <select id="pageSelect" onchange="switchPage(this.value)"></select>
      <button id="nextBtn" class="nav-btn" onclick="nextPage()">परम् ›</button>
    </div>

    <!-- Typography Group -->
    <div class="toolbar-group" title="अक्षरविन्यासः (Typography Controls)">
      <select id="fontSelect" onchange="changeFont(this.value)" title="लिपिः (Font Family)">
        <option value="'Tiro Devanagari Sanskrit', serif">Tiro Devanagari</option>
        <option value="'Noto Serif Devanagari', serif">Noto Serif</option>
        <option value="Siddhanta, serif">Siddhanta</option>
      </select>
      <span class="toolbar-label">आकारः</span>
      <button onclick="stepFontSize(-2)" title="अक्षराकारं न्यूनीकरोतु (Decrease Font Size)">A−</button>
      <input type="number" id="fontSizeInput" class="num-input" value="22" min="14" max="48" onchange="setFontSizeNumber(this.value)">
      <button onclick="stepFontSize(2)" title="अक्षराकारं वर्धयतु (Increase Font Size)">A+</button>
    </div>

    <!-- Section Visibility Group -->
    <div class="toolbar-group" title="विभाग-दर्शनम् (Toggle Sections)">
      <button id="toggleSec2" class="section-toggle" onclick="toggleSection('sec2Box', 'toggleSec2')">+ पदच्छेदः</button>
      <button id="toggleSec3" class="section-toggle" onclick="toggleSection('sec3Box', 'toggleSec3')">+ टिप्पणी</button>
    </div>

    <!-- Copy & Complete Book Export Group -->
    <div class="toolbar-group">
      <button class="action-btn primary-outline" onclick="copySectionText('sec1')" title="अस्य पृष्ठस्य मूलपाठं प्रतिकुरुत (Copy this page's Sanskrit text)">
        📋 पृष्ठ-पाठं प्रतिकुरुत (Copy Page Text)
      </button>
      <button class="export-btn" onclick="openAllPagesModal()" title="सम्पूर्णं ग्रन्थं पश्यतु, प्रतिकुरुत, Word / PDF वा अवतारयतु (View, Copy, or Download Complete Book in Word / PDF)">
        📖 सम्पूर्णः ग्रन्थः (Full Text / Word / PDF)
      </button>
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
        <span id="currentPageHeading">पृष्ठम् ०१५</span>
        <span id="diffIndicator" style="font-size: 13px; font-weight: normal; color: #16a34a;">✔ अविकृतः (Matches Scan)</span>
      </div>
      <div class="page-utility-actions">
        <button class="light-btn amber" onclick="copySectionText('sec1')" title="केवलं मूलपाठं प्रतिकुरुत (Copy clean Sanskrit text of this page)">
          📋 मूलपाठं प्रतिकुरुत (Copy Sanskrit Text)
        </button>
        <button class="light-btn" onclick="copyCurrentPageFormatted()" title="अस्य पृष्ठस्य सर्वान् विभागान् प्रतिकुरुत (Copy all sections of this page for Word/Docs)">
          📑 सम्पूर्णं पृष्ठं प्रतिकुरुत (Copy Page w/ Notes)
        </button>
      </div>
    </div>

    <!-- Section 1: Mulapatha -->
    <div class="card-container">
      <div class="card-header">
        <span>१. मूलपाठः (Devanagari OCR Text)</span>
        <div class="card-header-right">
          <button class="light-btn" onclick="copySectionText('sec1')" title="Copy Mūlapāṭha text">📋 प्रतिकुरुत (Copy)</button>
          <button id="revertBtn" class="light-btn" style="display: none; color: #b91c1c; border-color: #fecaca;" onclick="revertCurrentPage()" title="मूलपाठं प्रत्यानयतु (Revert edits to original OCR)">↺ पूर्ववत् (Revert)</button>
        </div>
      </div>
      <textarea id="sec1Editor" class="sanskrit-editor" spellcheck="false" oninput="handleEdit()"></textarea>
      
      <div id="diffBox" style="margin-top: 14px; display: none;">
        <div style="font-size: 13px; color: #b45309; font-weight: 600; margin-bottom: 6px;">
          दृष्टं शोधनम् (Real-Time Proof Marks — Changes Highlighted):
        </div>
        <div id="diffView" class="diff-view-box"></div>
      </div>
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
        <button class="btn-word" onclick="downloadWordDoc()" title="Microsoft Word (.doc) सञ्चिकां अवतारयतु (Download Word Document)">
          📘 Word (.doc)
        </button>
        <button class="btn-pdf" onclick="printOrSavePdf()" title="PDF रूपेण रक्षतु अथवा मुद्रयतु (Save as PDF or Print)">
          🖨️ PDF / मुद्रणम्
        </button>
        <button class="action-btn" onclick="downloadCompiledMarkdown()" title="Markdown (.md) सञ्चिकां अवतारयतु">
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
  const pageProgressPill = document.getElementById('pageProgressPill');
  const currentPageHeading = document.getElementById('currentPageHeading');
  const sec1Editor = document.getElementById('sec1Editor');
  const sec2Editor = document.getElementById('sec2Editor');
  const sec3Content = document.getElementById('sec3Content');
  const pageImg = document.getElementById('pageImg');
  const fontSizeInput = document.getElementById('fontSizeInput');
  const diffBox = document.getElementById('diffBox');
  const diffView = document.getElementById('diffView');
  const diffIndicator = document.getElementById('diffIndicator');
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

  data.forEach((d, idx) => {
    let opt = document.createElement('option');
    opt.value = idx;
    opt.innerText = `पृष्ठम् ${toDevanagariDigits(d.page)} (Page ${d.page})`;
    select.appendChild(opt);
  });

  function switchPage(idx) {
    currentIndex = parseInt(idx, 10);
    select.value = currentIndex;
    const item = data[currentIndex];

    if (item.baseline === undefined) {
      item.baseline = item.sec1;
    }

    pageImg.src = 'data:image/png;base64,' + item.img;
    sec1Editor.value = item.sec1;
    sec2Editor.value = item.sec2;
    sec3Content.innerHTML = item.sec3_html;

    const devPage = toDevanagariDigits(item.page);
    currentPageHeading.innerText = `पृष्ठम् ${devPage} (Page ${item.page})`;
    pageProgressPill.innerText = `पृष्ठम् ${toDevanagariDigits(currentIndex + 1)} / ${toDevanagariDigits(data.length)}`;

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
  }

  function revertCurrentPage() {
    const item = data[currentIndex];
    if (item.baseline !== undefined) {
      sec1Editor.value = item.baseline;
      handleEdit();
      showToast('↺ मूलपाठः पूर्ववत् स्थापितः (Reverted to original scan text)');
    }
  }

  function handleEdit() {
    autoResize(sec1Editor);
    const item = data[currentIndex];
    const currentText = sec1Editor.value;
    item.sec1 = currentText;

    const baseWords = tokenize(item.baseline);
    const curWords = tokenize(currentText);

    let hasDifferences = false;
    let renderedHtml = "";

    curWords.forEach(w => {
      if (w.trim().length > 0 && !baseWords.includes(w)) {
        renderedHtml += `<span class="mark-edited">${escapeHtml(w)}</span>`;
        hasDifferences = true;
      } else {
        renderedHtml += escapeHtml(w);
      }
    });

    if (hasDifferences || currentText !== item.baseline) {
      diffBox.style.display = 'block';
      diffView.innerHTML = renderedHtml;
      diffIndicator.innerHTML = '<span style="color: #b45309; font-weight: 700;">● संशोधितः (Edited)</span>';
      revertBtn.style.display = 'inline-flex';
    } else {
      diffBox.style.display = 'none';
      diffView.innerHTML = '';
      diffIndicator.innerHTML = '<span style="color: #16a34a;">✔ अविकृतः (Matches Scan)</span>';
      revertBtn.style.display = 'none';
    }
  }

  function tokenize(str) {
    return str.split(/([\s।॥,.\-—]+)/);
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

  function copySectionText(secKey) {
    const item = data[currentIndex];
    item.sec1 = sec1Editor.value;
    item.sec2 = sec2Editor.value;
    const devNum = toDevanagariDigits(item.page);

    if (secKey === 'sec1') {
      const html = `<div style="font-family: 'Noto Serif Devanagari', 'Tiro Devanagari Sanskrit', serif; font-size: 16pt; line-height: 1.9;">${escapeHtml(item.sec1).replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>')}</div>`;
      copyToClipboard(item.sec1, `✔ पृष्ठम् ${devNum} — मूलपाठः प्रतिकृतः (Copied Sanskrit Text!)`, html);
    } else if (secKey === 'sec2') {
      const html = `<div style="font-family: 'Noto Serif Devanagari', 'Tiro Devanagari Sanskrit', serif; font-size: 15pt; line-height: 1.9;">${escapeHtml(item.sec2).replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>')}</div>`;
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
      `<div style="font-family: 'Noto Serif Devanagari', 'Tiro Devanagari Sanskrit', serif; font-size: 15pt; line-height: 1.9; color: #111;">`,
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

  function buildCompiledBookData() {
    if (data[currentIndex]) {
      data[currentIndex].sec1 = sec1Editor.value;
      data[currentIndex].sec2 = sec2Editor.value;
    }
    const opts = getModalOptions();
    if (!opts.sec1 && !opts.sec2 && !opts.sec3) {
      return {
        plain: 'कृपया न्यूनातिन्यूनम् एकं विभागं चिनोतु (Please select at least one section above).',
        html: '<p class="empty-note">कृपया न्यूनातिन्यूनम् एकं विभागं चिनोतु (Please select at least one section above).</p>'
      };
    }

    // Continuous seamless mode when only Mulapatha (or Mulapatha without page headers) is selected with Join Split Words
    if (opts.mergeHyphens && !opts.showPageNums && opts.sec1 && !opts.sec2 && !opts.sec3) {
      const mergedSec1 = mergeContinuousTexts(data.map(d => d.sec1 || ''));
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

    for (let i = 0; i < data.length; i++) {
      const item = data[i];
      const devNum = toDevanagariDigits(item.page);
      let pagePlain = [];
      let pageHtml = [];

      if (opts.showPageNums || multiSection) {
        pagePlain.push(`[पृष्ठम् ${devNum}]`);
        pageHtml.push(`<div class="book-page-divider">पृष्ठम् ${devNum} (Page ${item.page})</div>`);
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
    bookPreviewSheet.innerHTML = compiled.html;
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
    const richHtml = `<div style="font-family: 'Noto Serif Devanagari', 'Tiro Devanagari Sanskrit', serif; font-size: 15pt; line-height: 1.9; color: #111;">${compiled.html}</div>`;
    copyToClipboard(compiled.plain, `✔ सम्पूर्णः पाठः प्रतिकृतः — Word / Docs मध्ये स्थापयतु (Copied! Paste anywhere)`, richHtml);
  }

  function buildStandaloneDocumentHtml(title, bodyHtml) {
    return `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40" lang="sa">
<head>
<meta charset="UTF-8">
<title>${title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+Devanagari:wght@400;600;700&family=Tiro+Devanagari+Sanskrit&display=swap">
<style>
  @page { size: A4; margin: 2.2cm; }
  body {
    font-family: 'Noto Serif Devanagari', 'Tiro Devanagari Sanskrit', 'Siddhanta', serif;
    font-size: 15pt;
    line-height: 1.95;
    color: #111827;
    max-width: 780px;
    margin: 0 auto;
    padding: 20px;
  }
  p { margin: 0 0 14pt 0; text-align: justify; white-space: pre-wrap; }
  .book-page-divider {
    font-size: 12pt;
    font-weight: bold;
    color: #9a3412;
    margin-top: 18pt;
    margin-bottom: 6pt;
    border-bottom: 1px solid #fed7aa;
  }
  .book-sec-heading {
    font-size: 13pt;
    font-weight: bold;
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
</style>
</head>
<body>
${bodyHtml}
</body>
</html>`;
  }

  function downloadWordDoc() {
    const compiled = buildCompiledBookData();
    const firstPage = data.length > 0 ? data[0].page : '015';
    const lastPage = data.length > 0 ? data[data.length - 1].page : '032';
    const docHtml = '\ufeff' + buildStandaloneDocumentHtml('श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः', compiled.html);
    const filename = `bharata_sangraha_${firstPage}_to_${lastPage}.doc`;
    triggerFileDownload(filename, docHtml, 'application/msword;charset=utf-8');
    showToast(`📘 Word सञ्चिका (${filename}) अवतारिता!`);
  }

  function printOrSavePdf() {
    const compiled = buildCompiledBookData();
    const docHtml = buildStandaloneDocumentHtml('श्रीमल्लक्ष्मणसूरिविरचितः भारतसङ्ग्रहः', compiled.html);
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
    const blocks = data.map(item => buildPageMarkdown(item, opts).trim());
    return blocks.join('\n\n---\n\n') + '\n';
  }

  function downloadCompiledMarkdown() {
    const md = generateAllPagesMarkdownString();
    const firstPage = data.length > 0 ? data[0].page : '000';
    const lastPage = data.length > 0 ? data[data.length - 1].page : '000';
    const filename = `bharata_sangraha_pages_${firstPage}_to_${lastPage}.md`;
    triggerFileDownload(filename, md, 'text/markdown;charset=utf-8');
    showToast(`⬇ ${filename} अवतारितम् (Downloaded .md)`);
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

      saveBtn.innerText = '✔ रक्षितम् (Saved!)';
      saveBtn.style.background = '#059669';
      showToast(`✔ पृष्ठम् ${toDevanagariDigits(item.page)} सुरक्षितम् (Saved to Drive)`);
      setTimeout(() => {
        saveBtn.innerText = '💾 रक्षतु (Save)';
        saveBtn.style.background = '#16a34a';
      }, 2000);
    } catch (err) {
      alert("रक्षणे दोषः जातः (Save failed): " + err.message);
      saveBtn.innerText = '💾 रक्षतु (Save)';
      saveBtn.style.background = '#16a34a';
    }
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && allPagesModal.classList.contains('open')) {
      closeAllPagesModal();
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

def generate_viewer():
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
        img_path = os.path.join(PAGE_IMAGES, f"page_{p_num}.png")

        if not os.path.exists(img_path):
            continue

        with open(img_path, "rb") as img_f:
            img_b64 = base64.b64encode(img_f.read()).decode("utf-8")

        with open(md_path, "r", encoding="utf-8") as md_f:
            raw_text = md_f.read()

        sec1, sec2, sec3_md, sec3_html = parse_sections(raw_text)

        pages_data.append({
            "page": p_num,
            "img": img_b64,
            "sec1": sec1,
            "sec2": sec2,
            "sec3_md": sec3_md,
            "sec3_html": sec3_html
        })

    json_data = json.dumps(pages_data, ensure_ascii=False)
    final_html = HTML_TEMPLATE.replace("<!-- JSON_DATA_PLACEHOLDER -->", json_data)
    final_html = final_html.replace("<!-- APPS_SCRIPT_URL_PLACEHOLDER -->", APPS_SCRIPT_URL)

    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(final_html)
    print(f"[Success] Generated review portal: {OUTPUT_HTML} (Loaded {len(pages_data)} pages)")

if __name__ == "__main__":
    generate_viewer()
