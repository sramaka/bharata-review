# Bhārata Saṅgraha Sanskrit OCR & Scholar Review Pipeline

## 1. Project Mission & Objective
Digitize, transcribe, and verify the classical Sanskrit work *Bhārata Saṅgraha* by Mahāmahopādhyāya M. Lakshmana Suri. The project combines local vision-based OCR extraction, automated sandhi analysis, and a web-based, scholar-friendly proofreading interface hosted on GitHub Pages that saves verified edits back to Google Drive without requiring logins or technical knowledge.

---

## 2. Workspace & Environment Architecture
- **Primary OS / Host:** Ubuntu 24.04 LTS via WSL2 on Windows 11
- **Working Directory:** `~/ocr_bharata_sangrahaha/`
- **Python Environment:** Python 3.12+ virtual environment (`venv/`)
- **Key Python Packages:** `pymupdf` (page extraction, and web-image generation in the portal builder; the local server uses the standard library only)
- **Deployment Platform:** GitHub Pages (`https://sramaka.github.io/bharata-review/`), served from the root `index.html` on `main`
- **Backend Sync Webhook:** Google Apps Script Web App (URL set in `APPS_SCRIPT_URL` at the top of `scripts/build_html_review.py`). It receives zero-token POST payloads `{page, content}` and writes them directly to Google Drive (`bharata_verified_pages/`).

---

## 3. Directory Layout & Roles

```text
~/ocr_bharata_sangrahaha/
├── config/
│   └── agent_rules.md                         # Guidelines + template for 3-section Sanskrit transcription
├── input_pdf/                                 # (git-ignored)
│   └── bharata_sangraha.pdf                   # Source scanned PDF
├── page_images/                               # (git-ignored) 300 DPI renderings (page_015.png … page_032.png)
├── output/
│   ├── raw/                                   # Agent-generated OCR markdown (page_015.md … page_032.md), committed
│   ├── verified/                              # Scholar-verified final markdown files
│   ├── review_flags.json                      # Words flagged for scholar review (shown in the portal)
│   └── proofread_bundle.html                  # (git-ignored) Optional offline portal with embedded scans (--standalone)
├── scripts/
│   ├── extract_pages.py                       # PyMuPDF extractor: extract_pages.py START END [--dpi N]
│   ├── build_html_review.py                   # Builds index.html + page_web/ from output/raw/ and page images
│   └── local_review_and_direct_save_server.py # Local HTTP server (port 8000) with POST /save_verified → output/verified/
├── index.html                                 # GitHub Pages portal, written by build_html_review.py (text only, ~0.4 MB)
├── page_web/                                  # Committed 1600px grayscale JPEG scans (~250 KB each) loaded by index.html
├── project_context_specification.md           # Project architecture and instructions (this file)
└── .gitignore                                 # Excludes venv/, .venv/, input_pdf/, page_images/, __pycache__/,
                                               #   output/proofread_bundle.html, *:Zone.Identifier
```

Current coverage in `output/raw/`: front matter on PDF pages **7–13** (Foreword pp. 7–11 and the Preface to the Second Edition on p. 11, in English; Works of the author on p. 12, in IAST; Contents on p. 13, in Devanagari) and the main text on PDF pages **15–32** (Ādiparva, book pages 1–18). Book page = PDF page − 14.

---

## 4. Text Schema & Annotation Standards
All transcribed markdown files in `output/raw/` and `output/verified/` must adhere strictly to the 3-section structure defined in `config/agent_rules.md`, headed `# पृष्ठम् ०XX` (Devanagari page number):

1. **`## १. मूलपाठः` (Devanagari OCR Text)**
   - Accurate, un-split transcription faithful to the source scan image.
   - Retains original verse numbering, section headers, dandas (`।`), and double dandas (`॥`).
   - A word broken across the page end keeps its trailing hyphen (e.g. `पाण्डुरित्ये-`).
   - No arbitrary modernisation or silent emendations.

2. **`## २. पदच्छेदसहितः पाठः` (Sandhi-Split Padaccheda)**
   - Exhaustive word-by-word sandhi decomposition of Section 1.
   - Distinct separation of compound members (*samāsa-vigraha*) according to Pāṇinian grammar.

3. **`## ३. सम्पादनटिप्पण्यः` (Apparatus & Editorial Notes)**
   - Markdown table with columns `सङ्ख्या | स्थानम् | मूलपाठः | शोधितः पाठः | प्रकारः | विवरणम्`.
   - The `प्रकारः` column uses the standard badges:
     - `⚠️ मुद्रणदोषः` (Typographical / printing error in original scan)
     - `❓ संदिग्धम्` (Doubtful / ambiguous character or damaged print)
     - `ℹ️ व्याकरणम् / सन्धिः` (Grammatical or complex euphonic junction note)
     - `ℹ️ पृष्ठसन्धिः` (Sandhi spanning across page or line break)

The builder (`parse_sections`) detects sections by the heading text `मूलपाठ`, `पदच्छेद`, and `सम्पादन`, and only renders Section 3 lines that start and end with `|` as table rows.

---

## 5. Web Proofreading Portal Specifications (`scripts/build_html_review.py`)
The builder pairs each `output/raw/page_XXX.md` with a scan, skipping pages that have none. It converts `page_images/page_XXX.png` to `page_web/page_XXX.jpg` (1600px wide, grayscale, JPEG quality 80), regenerating only when the PNG is newer, so a fresh clone without `page_images/` still builds from the committed JPEGs. It writes `index.html`, which holds the page text and loads each scan on demand (with a content-hash query string for cache-busting) and prefetches the next one. `--standalone` instead writes `output/proofread_bundle.html` with all scans embedded, for offline use.

- **Scholar UX:** Tailored for a traditional Sanskrit scholar. Labels are in Sanskrit with English glosses, and no raw Markdown markup or technical prompts are shown.
- **Single-Row Header:** Page navigation and section toggles on the left; **📖 सम्पूर्णः ग्रन्थः**, a **⚙** settings menu, and **💾 रक्षतु (Save)** on the right. The interface font is Noto Sans Devanagari (loaded from Google Fonts), with 14px+ text and 36px-tall buttons.
- **Page Navigation:** Previous / Next buttons, a page dropdown, and `Alt + ←/→` keyboard shortcuts. Pages are labelled by section and printed page (e.g. `आदिपर्व · पृ. १ (PDF 015)`, `प्रस्तावना (Foreword) · iii (PDF 007)`). The builder derives these labels from `PARVAS`, `FRONT_MATTER` and `BOOK_PAGE_OFFSET` in `build_html_review.py`.
- **Page Status:** Each page shows `○ अपरीक्षितम्` (not yet saved), `● संशोधितम्, अरक्षितम्` (edited, not saved) or `✔ रक्षितम्` (saved). The same mark is shown in the page dropdown. Status is kept for the browser session only.
- **English Front Matter:** Pages marked `en` use a Latin serif font (Noto Serif), relabel Section 1 as "Original Text — English", and hide the पदच्छेदः toggle.
- **Side-by-Side Verification:** The left pane renders the 300 DPI scan with zoom controls (−/+ and Fit). The right pane renders the editable Devanagari text.
- **Movable Divider:** Drag the divider between the panes to resize them (limited to 20–80% width). Double-click it to reset to the default 48% split. The divider is hidden on narrow screens.
- **Section Visibility:** Section 1 (मूलपाठः) is visible by default. Sections 2 (पदच्छेदः) and 3 (टिप्पणी) are collapsible via toolbar toggles. Sections 1 and 2 are editable textareas. Section 3 is a read-only rendered table.
- **Auto-Fitting & Resizable Area:** Textareas automatically resize to the full height of the text content without internal scrollbars while preserving manual drag handles.
- **Typography Controls (⚙ menu):** A numeric font-size input (14–48, default 22), `A−` / `A+` step buttons, and a font family selector (`Tiro Devanagari Sanskrit` (default), `Martel`, `Sahitya`, `Noto Serif Devanagari`, `Siddhanta`). All but Siddhanta load from Google Fonts; Siddhanta works only if it is installed locally. The chosen font is also used for the notes table, the Complete Text preview, copied text and Word/PDF exports. Headings use larger regular-weight type, because Tiro has no bold.
- **Real-Time Proof Marks:** Edits to Section 1 are compared word by word (LCS diff) with the original OCR as they are typed. The results appear in a panel pinned to the bottom of the text pane, so they are always in view. The panel lists each change with surrounding context: deletions are struck through in red and insertions highlighted in amber/yellow (`#fef08a`). Clicking a change selects it in the editor. The panel can switch to a full-text view or collapse. A **↺ पूर्ववत् (Revert)** button restores the OCR text.
- **Review Flags:** `output/review_flags.json` lists words that need the scholar's attention, keyed by PDF page.
  - Each entry has: `section` (`sec1`/`sec2`), the exact `match` text, an optional `suggest` replacement, a `kind`, and a `note`.
  - There are three kinds: `ocr` (transcription differs from the scan; red wavy highlight), `print` (matches the scan but is probably a misprint; amber), and `verify` (unclear in the scan; blue dotted).
  - Flagged words are highlighted inside the editors by a layer drawn behind the transparent textarea.
  - A ⚑ card above Section 1 lists the flags with notes. **दर्शयतु (Show)** selects the word in the text. **स्वीकरोतु (Accept)** applies the suggestion as a normal edit, so it appears in the proof marks and still needs saving.
  - A flag counts as resolved once its text no longer appears. The page dropdown shows the number of open flags (⚑n).
  - The transcriptions themselves are not changed by flagging.
  - **In exports:** the Complete Text option **⚑ समीक्षणीयानि (Mark Words to Review)**, on by default, marks each open flag in the Word/PDF/copied text. The word gets the flag's colour and a numbered ⚑n superscript, and a "Words to Review" list (number, word → suggestion, page, kind, note) closes each section. Plain-text copies show `word[⚑n]`. Accepted or edited-away flags are left out; untick the option for a clean copy.
- **Copy Actions:** Per-section copy buttons; "Copy page text" and "Copy page with notes" are in the ⚙ menu. Where the browser supports it, the copied content is rich HTML that pastes cleanly into Word / Google Docs.
- **Complete Text View (सम्पूर्णः ग्रन्थः):** A modal that compiles all pages into one reader-friendly text, using the current in-browser edits.
  - Options choose which sections to include (1/2/3), show page-number headers, and join words hyphenated across page breaks (पृष्ठसन्धि-संयोजनम्, on by default).
  - Front matter (Foreword, Works, Contents) is included by default via **प्रस्तावनादि (Front Matter)**; untick it for the main text only. When it is included, it comes first, English pages use a Latin font, and a rule separates it from the main text.
  - Text is compiled per section (Foreword, each parva, …), so one section never runs on into the next. With only Section 1 selected, joining on, and page numbers off, each section renders as one continuous flow. Page headers use the section label (e.g. `आदिपर्व · पृ. ३ (PDF 017)`).
  - Exports: **Rich Copy**, **Word (.docx)**, **PDF / Print** (opens a print window, so pop-ups must be allowed), and **Markdown (.md)**.
  - Word and PDF exports are laid out as a book:
    - A title page.
    - A linked अनुक्रमणिका (Table of Contents) listing each section with its printed page range (e.g. `आदिपर्व … पृ. १–१८`).
    - When front matter is included, part headings (`प्रस्तावनादि` / `मूलग्रन्थः`) on their own pages.
    - Each section starting on a new page under a heading.
    - Page numbers in the PDF footer.
  - **Source + padaccheda layout:** when both Section 1 and Section 2 are included, the padaccheda is set under each passage of the source text, not page by page. It is smaller, muted blue, indented, with a thin rule at the left.
    - Paragraphs are paired by position on each page. A page whose paragraph counts differ is kept as one pair.
    - Paragraphs split across a page break are joined in both texts. In the padaccheda, a page that continues a split word restates its head in parentheses (e.g. `(पाण्डुः इति ए)व`, `(इद)म्`), and the builder uses this to rejoin the word.
    - Long prose paragraphs are cut into chunks of a few sentences (about 320 characters) at the same danda in both texts. Every paragraph pair has matching dandas; any that don't are kept whole.
    - Verses and short lines are centred, prose gets a first-line indent, and a padaccheda identical to its source (e.g. `श्रीः`) is omitted.
    - A पठनसङ्केतः (How to read) key explains the two styles.
    - With page numbers off, editorial notes are gathered at the end of each section, labelled by page. With page numbers on, they follow each page.
  - **Word export** produces a real `.docx` (Office Open XML). It is generated in the browser from the same export markup as the PDF and packed by a small built-in zip writer, with no external libraries. It uses named styles: `Source Text`, `Padaccheda`, `Padaccheda Centred`, `Body English`, Heading 1–3, `Notes Heading`, `Title`, and `toc 1`/`toc 2`. The table of contents is a real Word TOC field, pre-filled with linked entries; right-click → Update Field adds Word page numbers. Notes are Word tables with a repeating header row, and the footer has a PAGE field (none on the title page). Word shows the chosen text font (default Tiro Devanagari Sanskrit) only if it is installed on that computer.
  - Headings are real H1 (parts) / H2 (sections) / H3 (page markers, when page numbers are on), so Word's Navigation Pane and PDF links work. The in-app preview shows the same table of contents and headings. Exported files are named `bharata_sangraha_<first>_to_<last>` after the PDF pages included.
  - `Esc` closes the modal.
- **Zero-Prompt Persistence:** Clicking **💾 रक्षतु (Save)** POSTs `{page, content}` (the full 3-section Markdown) to the Google Apps Script Web App URL as `text/plain`, persisting `page_XXX.md` to `bharata_verified_pages/` in Google Drive. The button then shows `✔ रक्षितम्` along with a toast.

### Local Review Server (`scripts/local_review_and_direct_save_server.py`)
Serves the repo root (the portal is at `http://localhost:8000/`) with CORS enabled. It also exposes `POST /save_verified`, which takes a JSON body `{page, content}` and writes it to `output/verified/page_XXX.md`.
**Note:** the generated portal currently always saves to the Apps Script URL and does not call `/save_verified`. The endpoint is available for local testing or a future local-save mode.

---

## 6. Common Developer / Agent Workflows

### A. Extract Pages from PDF
```bash
source venv/bin/activate
python3 scripts/extract_pages.py 15 32          # START END (1-indexed PDF pages, inclusive)
python3 scripts/extract_pages.py 7 13 --dpi 400 # optional render resolution (default 300)
```

### B. Transcribe a Target Page
When asked to transcribe `page_images/page_XXX.png`:
1. Read the image visually.
2. Read `config/agent_rules.md` for formatting and table syntax.
3. Generate `output/raw/page_XXX.md` with all three required sections.

### C. Preview Locally
```bash
venv/bin/python scripts/build_html_review.py
python3 scripts/local_review_and_direct_save_server.py
# open http://localhost:8000/
```

### D. Rebuild and Deploy Reviewer Portal
```bash
venv/bin/python scripts/build_html_review.py       # writes index.html and page_web/
git add index.html page_web/ scripts/ output/raw/
git commit -m "Update pages in review portal"
git push origin main
```

### E. Syncing Verified Files from Scholar
Scholar edits land in Google Drive folder `bharata_verified_pages/`. Verified pages are periodically pulled down into `output/verified/` for archival and downstream corpus generation. This step is manual, and `output/verified/` is currently empty.
