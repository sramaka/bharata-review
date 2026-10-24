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

def clean_inline(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    return text

def build_table(rows):
    if len(rows) < 2:
        return ""
    table_html = ["<table class='scholarly-table'>"]
    header = rows[0]
    headers = [c.strip() for c in header.strip('|').split('|')]
    table_html.append("<thead><tr>" + "".join(f"<th>{clean_inline(h)}</th>" for h in headers) + "</tr></thead><tbody>")

    start_idx = 2 if re.match(r'^[|\s\-:]+$', rows[1]) else 1
    for r in rows[start_idx:]:
        cells = [c.strip() for c in r.strip('|').split('|')]
        table_html.append("<tr>" + "".join(f"<td>{clean_inline(c)}</td>" for c in cells) + "</tr>")
    table_html.append("</tbody></table>")
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

    table_rows = [l.strip() for l in sec3_lines if l.strip().startswith("|") and l.strip().endswith("|")]
    sec3_html = build_table(table_rows) if table_rows else "<p><em>टिप्पणी नास्ति।</em></p>"

    return sec1_text, sec2_text, sec3_html

HTML_TEMPLATE = """<!DOCTYPE html>
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
    --line-height: 2.2;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; overflow: hidden; background: #0f172a; }

  header {
    background: #1e293b;
    color: #f8fafc;
    padding: 8px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #334155;
    flex-wrap: wrap;
    gap: 8px;
    z-index: 10;
  }
  .app-title { font-size: 15px; font-weight: bold; color: #fde68a; }
  .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

  button, select, input[type="number"] {
    background: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    outline: none;
  }
  button, select { cursor: pointer; transition: all 0.15s ease; }
  button:hover, select:hover { background: #475569; }
  
  .num-input {
    width: 60px;
    text-align: center;
    font-weight: 600;
    color: #38bdf8;
    background: #0f172a;
    border-color: #0284c7;
  }

  .nav-btn { background: #0284c7; border-color: #0284c7; font-weight: 600; }
  .nav-btn:hover { background: #0369a1; }
  .save-btn { background: #16a34a; border-color: #16a34a; font-weight: 600; color: #fff; }
  .save-btn:hover { background: #15803d; }

  .section-toggle {
    background: #1e293b;
    border: 1px solid #64748b;
    color: #cbd5e1;
  }
  .section-toggle.active {
    background: #0369a1;
    border-color: #38bdf8;
    color: #ffffff;
    font-weight: 600;
  }

  .main-container { display: flex; flex: 1; height: calc(100vh - 54px); overflow: hidden; }
  .pane { flex: 1; height: 100%; overflow-y: auto; padding: 20px; }

  .image-pane {
    background: #334155;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    border-right: 2px solid #1e293b;
  }
  .image-pane img {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  }

  .text-pane {
    background: #fdfbf7;
    color: #1c1917;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .card-container {
    max-width: 880px;
    margin: 0 auto;
    width: 100%;
    background: #ffffff;
    border-radius: 8px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    border: 1px solid #e2e8f0;
  }

  .card-header {
    font-size: 1.1em;
    font-weight: bold;
    color: #9a3412;
    border-bottom: 2px solid #fed7aa;
    padding-bottom: 6px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .sanskrit-editor {
    width: 100%;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 16px;
    font-family: var(--font-family);
    font-size: var(--font-size);
    line-height: var(--line-height);
    outline: none;
    resize: vertical;
    overflow-y: hidden;
    white-space: pre-wrap;
    background: #ffffff;
    color: #0f172a;
    transition: border-color 0.15s ease;
  }
  .sanskrit-editor:focus {
    border-color: #0284c7;
    box-shadow: 0 0 0 2px rgba(2,132,199,0.15);
  }

  .diff-view-box {
    background: #fafaf9;
    border: 1px solid #e7e5e4;
    border-radius: 6px;
    padding: 16px;
    margin-top: 10px;
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

  .scholarly-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    font-size: 0.85em;
    line-height: 1.6;
  }
  .scholarly-table th, .scholarly-table td {
    border: 1px solid #cbd5e1;
    padding: 8px 12px;
    text-align: left;
  }
  .scholarly-table th { background: #f1f5f9; color: #334155; font-weight: 600; }
  .scholarly-table tr:nth-child(even) { background: #f8fafc; }
</style>
</head>
<body>

<header>
  <div class="app-title">॥ भारतसङ्ग्रहः — शोधनपुटम् ॥</div>
  
  <div class="toolbar">
    <button class="nav-btn" onclick="prevPage()">‹ पूर्वम् (Prev)</button>
    <select id="pageSelect" onchange="switchPage(this.value)"></select>
    <button class="nav-btn" onclick="nextPage()">परम् (Next) ›</button>

    <select id="fontSelect" onchange="changeFont(this.value)">
      <option value="'Tiro Devanagari Sanskrit', serif">Tiro Devanagari</option>
      <option value="'Noto Serif Devanagari', serif">Noto Serif</option>
      <option value="Siddhanta, serif">Siddhanta</option>
    </select>

    <label style="font-size: 13px; color: #94a3b8;">अक्षराकारः (pt):</label>
    <input type="number" id="fontSizeInput" class="num-input" value="22" min="14" max="48" onchange="setFontSizeNumber(this.value)">
    <button onclick="stepFontSize(-1)">A−</button>
    <button onclick="stepFontSize(1)">A+</button>

    <button id="toggleSec2" class="section-toggle" onclick="toggleSection('sec2Box', 'toggleSec2')">+ पदच्छेदः (Padaccheda)</button>
    <button id="toggleSec3" class="section-toggle" onclick="toggleSection('sec3Box', 'toggleSec3')">+ टिप्पणी (Apparatus)</button>

    <button id="saveBtn" class="save-btn" onclick="saveVerifiedDirect()">रक्षतु (Save)</button>
  </div>
</header>

<div class="main-container">
  <div class="pane image-pane">
    <img id="pageImg" src="" alt="Scan Image">
  </div>

  <div class="pane text-pane">
    <div class="card-container">
      <div class="card-header">
        <span>१. मूलपाठः (Devanagari OCR Text)</span>
        <span id="diffIndicator" style="font-size: 13px; font-weight: normal; color: #64748b;">(अपरिवर्तितः)</span>
      </div>
      <textarea id="sec1Editor" class="sanskrit-editor" spellcheck="false" oninput="handleEdit()"></textarea>
      
      <div id="diffBox" style="margin-top: 14px; display: none;">
        <div style="font-size: 13px; color: #b45309; font-weight: 600; margin-bottom: 6px;">
          दृष्टं शोधनम् (Real-Time Proof Marks — Changes Highlighted):
        </div>
        <div id="diffView" class="diff-view-box"></div>
      </div>
    </div>

    <div id="sec2Box" class="card-container collapsible-section">
      <div class="card-header" style="color: #1e3a8a; border-color: #bfdbfe;">
        <span>२. पदच्छेदसहितः पाठः (Sandhi-split Padaccheda)</span>
      </div>
      <textarea id="sec2Editor" class="sanskrit-editor" spellcheck="false" oninput="autoResize(this)"></textarea>
    </div>

    <div id="sec3Box" class="card-container collapsible-section">
      <div class="card-header" style="color: #475569; border-color: #cbd5e1;">
        <span>३. सम्पादनटिप्पण्यः (Apparatus & Editorial Notes)</span>
      </div>
      <div id="sec3Content"></div>
    </div>
  </div>
</div>

<script>
  const APPS_SCRIPT_URL = "<!-- APPS_SCRIPT_URL_PLACEHOLDER -->";
  const data = <!-- JSON_DATA_PLACEHOLDER -->;
  let currentIndex = 0;

  const select = document.getElementById('pageSelect');
  const sec1Editor = document.getElementById('sec1Editor');
  const sec2Editor = document.getElementById('sec2Editor');
  const sec3Content = document.getElementById('sec3Content');
  const pageImg = document.getElementById('pageImg');
  const fontSizeInput = document.getElementById('fontSizeInput');
  const diffBox = document.getElementById('diffBox');
  const diffView = document.getElementById('diffView');
  const diffIndicator = document.getElementById('diffIndicator');
  const saveBtn = document.getElementById('saveBtn');

  function autoResize(textarea) {
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = (textarea.scrollHeight + 6) + 'px';
  }

  data.forEach((d, idx) => {
    let opt = document.createElement('option');
    opt.value = idx;
    opt.innerText = 'PDF पृष्ठम् ' + d.page;
    select.appendChild(opt);
  });

  function switchPage(idx) {
    currentIndex = parseInt(idx);
    select.value = currentIndex;
    const item = data[currentIndex];

    if (item.baseline === undefined) {
      item.baseline = item.sec1;
    }

    pageImg.src = 'data:image/png;base64,' + item.img;
    sec1Editor.value = item.sec1;
    sec2Editor.value = item.sec2;
    sec3Content.innerHTML = item.sec3_html;

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

  function setFontSizeNumber(val) {
    let num = parseInt(val);
    if (isNaN(num)) num = 22;
    num = Math.max(14, Math.min(48, num));
    fontSizeInput.value = num;
    document.documentElement.style.setProperty('--font-size', num + 'px');
    autoResize(sec1Editor);
    autoResize(sec2Editor);
  }

  function stepFontSize(delta) {
    let cur = parseInt(fontSizeInput.value) || 22;
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

    if (hasDifferences) {
      diffBox.style.display = 'block';
      diffView.innerHTML = renderedHtml;
      diffIndicator.innerHTML = '<span style="color: #b45309; font-weight: bold;">● संशोधितः (Changes Detected)</span>';
    } else {
      diffBox.style.display = 'none';
      diffView.innerHTML = '';
      diffIndicator.innerHTML = '<span style="color: #16a34a;">✔ अविकृतः (Matches Scan)</span>';
    }
  }

  function tokenize(str) {
    return str.split(/([\s।॥,.\-—]+)/);
  }

  function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  async function saveVerifiedDirect() {
    const item = data[currentIndex];
    const outContent = `## [PDF पृष्ठम् ${item.page}]\n\n### १. मूलपाठः\n${sec1Editor.value}\n\n### २. पदच्छेदसहितः पाठः\n${sec2Editor.value}\n\n### ३. सम्पादनटिप्पण्यः\n(Verified against scan)\n`;

    saveBtn.innerText = 'रक्षणं क्रियते... (Saving)';
    saveBtn.style.background = '#d97706';

    try {
      // POST plain text to avoid CORS preflight options check
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
      setTimeout(() => {
        saveBtn.innerText = 'रक्षतु (Save)';
        saveBtn.style.background = '#16a34a';
      }, 2000);
    } catch (err) {
      alert("रक्षणे दोषः जातः (Save failed): " + err.message);
      saveBtn.innerText = 'रक्षतु (Save)';
      saveBtn.style.background = '#16a34a';
    }
  }

  window.addEventListener('keydown', (e) => {
    if (e.altKey && e.key === 'ArrowLeft') prevPage();
    if (e.altKey && e.key === 'ArrowRight') nextPage();
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

        sec1, sec2, sec3_html = parse_sections(raw_text)

        pages_data.append({
            "page": p_num,
            "img": img_b64,
            "sec1": sec1,
            "sec2": sec2,
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
