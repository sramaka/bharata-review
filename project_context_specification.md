# Bhārata Saṅgraha Sanskrit OCR & Scholar Review Pipeline

## 1. Project Mission & Objective
Digitize, transcribe, and verify the classical Sanskrit work *Bhārata Saṅgraha* by Mahāmahopādhyāya M. Lakshmana Suri. The project combines local vision-based OCR extraction, automated sandhi analysis, and a web-based, scholar-friendly proofreading interface hosted on GitHub Pages that saves verified edits back to Google Drive without requiring logins or technical knowledge.

---

## 2. Workspace & Environment Architecture
- **Primary OS / Host:** Ubuntu 24.04 LTS via WSL2 on Windows 11
- **Working Directory:** `~/ocr_bharata_sangrahaha/`
- **Python Environment:** Python 3.12+ virtual environment (`venv/`)
- **Key Python Packages:** `pymupdf` (fitz)
- **Deployment Platform:** GitHub Pages (`https://sramaka.github.io/bharata-review/`)
- **Backend Sync Webhook:** Google Apps Script Web App receiving zero-token POST payloads to write directly to Google Drive (`bharata_verified_pages/`).

---

## 3. Directory Layout & Roles

```text
~/ocr_bharata_sangrahaha/
├── config/
│   └── agent_rules.md            # Guidelines for 3-section Sanskrit transcription
├── input_pdf/
│   └── bharata_sangraha.pdf      # Source scanned PDF text
├── page_images/                  # 300 DPI page renderings (page_015.png, etc.)
├── output/
│   ├── raw/                      # Agent-generated OCR markdown (page_015.md, etc.)
│   ├── verified/                 # Scholar-verified final markdown files
│   └── proofread_bundle.html     # Standalone generated reviewer portal
├── scripts/
│   ├── extract_pages.py          # PyMuPDF 300 DPI extractor script
│   ├── build_html_review.py      # Bundler compiling images + text into the web portal
│   └── review_server.py          # Local HTTP server for zero-prompt testing & direct saves
├── index.html                    # Root GitHub Pages deployment file
├── PROJECT_CONTEXT.md            # Project architecture and instructions (this file)
└── .gitignore                    # Excludes venv, large images, and source PDFs
```

---

## 4. Text Schema & Annotation Standards
All transcribed markdown files in `output/raw/` and `output/verified/` must adhere strictly to the following 3-section structure:

1. **Section 1: मूलपाठः (Devanagari OCR Text)**
   - Accurate, un-split transcription faithful to the source scan image.
   - Retains original verse numbering, dandas (`।`), and double dandas (`॥`).
   - No arbitrary modernisation or silent emendations.

2. **Section 2: पदच्छेदसहितः पाठः (Sandhi-Split Padaccheda)**
   - Exhaustive word-by-word sandhi decomposition of Section 1.
   - Distinct separation of compound members (*samāsa-vigraha*) according to Pāṇinian grammar.

3. **Section 3: सम्पादनटिप्पण्यः (Apparatus & Editorial Notes)**
   - Markdown table categorizing source peculiarities using standard badges:
     - `⚠️ मुद्रणदोषः` (Typographical / printing error in original scan)
     - `❓ संदिग्धम्` (Doubtful / ambiguous character or damaged print)
     - `ℹ️ व्याकरणम् / सन्धिः` (Grammatical or complex euphonic junction note)
     - `ℹ️ पृष्ठसन्धिः` (Sandhi spanning across page or line break)

---

## 5. Web Proofreading Portal Specifications (`scripts/build_html_review.py`)
- **Scholar UX:** Tailored for a traditional Sanskrit scholar; presents no raw Markdown markup or technical prompts.
- **Side-by-Side Verification:** Left pane renders the source 300 DPI page scan; right pane renders editable Devanagari text.
- **Section Visibility:** Section 1 (मूलपाठः) is visible by default. Sections 2 (पदच्छेदः) and 3 (टिप्पणी) are collapsible via toolbar toggles.
- **Auto-Fitting & Resizable Area:** Textareas automatically resize to the full height of the text content without internal scrollbars while preserving manual drag handles.
- **Typography Controls:** Dedicated numeric font-size selector (`pt`), increment buttons (`A+` / `A-`), and font family selectors (`Tiro Devanagari Sanskrit`, `Noto Serif Devanagari`, `Siddhanta`).
- **Real-Time Proof Marks:** Edits made to Section 1 trigger an immediate live token diff box highlighting altered words in amber/yellow (`#fef08a`) without needing to save.
- **Zero-Prompt Persistence:** Clicking **रक्षतु (Save)** sends a payload to the Google Apps Script Web App URL, persisting the file to `bharata_verified_pages/` in Google Drive with instant visual confirmation (`✔ रक्षितम्`).

---

## 6. Common Developer / Agent Workflows

### A. Extract Pages from PDF
```bash
source venv/bin/activate
python3 scripts/extract_pages.py
```

### B. Transcribe a Target Page
When asked to transcribe `page_images/page_XXX.png`:
1. Read the image visually.
2. Read `config/agent_rules.md` for formatting and table syntax.
3. Generate `output/raw/page_XXX.md` with all three required sections.

### C. Rebuild and Deploy Reviewer Portal
```bash
python3 scripts/build_html_review.py
cp output/proofread_bundle.html index.html
git add index.html scripts/ output/raw/
git commit -m "Update pages in review portal"
git push origin main
```

### D. Syncing Verified Files from Scholar
Scholar edits land in Google Drive folder `bharata_verified_pages/`. Verified pages are periodically pulled down into `output/verified/` for archival and downstream corpus generation.