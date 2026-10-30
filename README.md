# Bhārata Saṅgraha — Digitization & Scholar Review

A digital edition of the Sanskrit *Bhārata Saṅgraha* by Mahāmahopādhyāya M. Lakshmana Suri. The book is a prose summary of the Mahābhārata. Each scanned page is transcribed by an AI with a sandhi-split (padaccheda) version alongside. A Sanskrit scholar then checks both against the scan in a web portal.

**Review portal:** https://sramaka.github.io/bharata-review/

## How it works

```
scanned PDF ──extract_pages.py──▶ page images ──AI transcription──▶ output/raw/page_XXX.md
                                                                          │
                                                          build_html_review.py
                                                                          ▼
          output/verified/page_XXX.md ◀──Save── review portal (GitHub Pages)
                     │                              ▲
                     └──GitHub Action rebuilds──────┘
```

1. **Extract:** pages of the scanned PDF are rendered to images.
2. **Transcribe:** the AI writes three sections for each page:
   - **१. मूलपाठः** — the text as printed.
   - **२. पदच्छेदसहितः पाठः** — the same text with sandhi and compounds split.
   - **३. सम्पादनटिप्पण्यः** — editorial notes.

   The format is defined in [config/agent_rules.md](config/agent_rules.md).
3. **Review:** the scholar reads each page beside its scan in the portal and does three things:
   - **Correct:** fixes mistakes, and tags each change as an OCR error, a misprint in the book, or a padaccheda error.
   - **Check flags:** goes through words the AI flagged, accepting or rejecting its suggestions.
   - **Mark for later:** marks words to come back to, or asks the AI to check them.
4. **Save:** saving commits the page to [output/verified/](output/verified/), through a Google Apps Script ([apps_script/Code.gs](apps_script/Code.gs)) that also keeps a copy in Google Drive. A GitHub Action then rebuilds the site, which shows the change within a couple of minutes.
5. **Feed back:** each saved page records what was corrected and why. Scripts turn these records into feedback for the AI and into worklists:
   - recurring OCR errors;
   - padaccheda that needs redoing after a source correction;
   - words the scholar asked the AI about.

   The AI's answers come back to the portal as new review flags.

The portal can also export the reviewed text as a PDF or Word document. The export has a title page, a table of contents, and each source passage followed by its padaccheda.

## Repository layout

| Path | Contents |
| :--- | :--- |
| `index.html`, `page_web/` | The built review portal and its page scans (served by GitHub Pages) |
| `output/raw/` | AI transcriptions, one Markdown file per PDF page |
| `output/verified/` | Pages saved by the scholar from the portal |
| `output/review_flags.json` | Words flagged for the scholar's review |
| `config/agent_rules.md` | Transcription rules for the AI |
| `scripts/` | Page extraction, portal builder, and correction/feedback tools |
| `apps_script/Code.gs` | Save backend (Google Apps Script) |
| `.github/workflows/rebuild-site.yml` | Rebuilds the portal when a page is saved |

The source PDF (`input_pdf/`) and the 300 DPI page images (`page_images/`) are not in the repository.

## Common tasks

Requires Python 3.10+. Only the page extraction step needs `pymupdf` (`pip install pymupdf`).

**Pull first.** Saves from the portal arrive as new commits on `main`.

```bash
git pull

# Render PDF pages 33–40 to page_images/ (then transcribe them into output/raw/)
python3 scripts/extract_pages.py 33 40

# Rebuild the portal and preview it at http://localhost:8000/
python3 scripts/build_html_review.py
python3 scripts/local_review_and_direct_save_server.py

# Feedback from the scholar's saved pages, written to output/corrections/
python3 scripts/collect_corrections.py      # correction log → summary of recurring errors
python3 scripts/padaccheda_worklist.py      # padaccheda to redo after source corrections
python3 scripts/review_marks.py             # words the scholar asked the AI to check
```

Pushing changes to `output/raw/`, `output/review_flags.json` or the builder rebuilds the live site automatically.

## More detail

[project_context_specification.md](project_context_specification.md) is the full specification. It covers:
- the text schema;
- every portal feature;
- the correction log format;
- the step-by-step workflows, including the one-time setup of GitHub saving.
