When transcribing and processing page images from `page_images/`, produce a structured Markdown file in `output/raw/page_XXX.md` using the exact 3-section layout detailed below.

---

## Output Section Specifications

### Section 1: Clean OCR Text (मूलपाठः)

* Transcribe original Devanagari characters accurately, preserving text flow and verse formatting (e.g., danda `।` and double danda `॥`).

* Do not apply sandhi splitting or morphological structural changes in this section.

* Retain original verse numbering and section headers as shown in the source image.

### Section 2: Sandhi-split Padaccheda Paragraph (पदच्छेदसहितः पाठः)

* Provide a complete sandhi-split decomposition (*padaccheda*) of Section 1.

* Separate joined compound words into individual grammatical constituents.

* Maintain clean Devanagari output with clear spacing between split words.

### Section 3: Apparatus & Verification Table (सम्पादनटिप्पण्यः)

Generate a structured table recording all textual flags, ambiguities, corrections, and sandhi details using these standard classification badges:

| Badge | Type | Meaning / Usage |

| :--- | :--- | :--- |

| `⚠️ मुद्रणदोषः` | Print Error | Typographical error or misprint in source image |

| `❓ संदिग्धम्` | Doubtful | Unclear, damaged, or smudged characters |

| `ℹ️ व्याकरणम् / सन्धिः` | Grammar / Sandhi | Complex phonetic transformation note |

| `ℹ️ पृष्ठसन्धिः` | Page Junction | Sandhi rule spanning page/line boundaries |

---

## Output Template Structure

```markdown

# पृष्ठम् ०१५

## १. मूलपाठः

[Original transcribed Devanagari verse/prose text]

## २. पदच्छेदसहितः पाठः

[Decomposed sandhi-split text]

## ३. सम्पादनटिप्पण्यः

| सङ्ख्या | स्थानम् | मूलपाठः | शोधितः पाठः | प्रकारः | विवरणम् |

| :--- | :--- | :--- | :--- | :--- | :--- |

| १ | श्लोकः २ | ... | ... | ⚠️ मुद्रणदोषः | ... |

```
