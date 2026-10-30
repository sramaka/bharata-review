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

* Keep the periphrastic perfect (आम्-प्रत्यय + अनुप्रयुक्त लिट् of अस् / कृ / भू) as **one word**. Do not split off the auxiliary. Hyphenate only an upasarga or compound member before it:
  * `नियोजयामास` → `नि-योजयामास` (not `नि-योजयाम् आस`)
  * `गमयामासुः`, `चकासामासतुः`, `पलायाञ्चक्रिरे`, `जागरांबभूव` stay whole.

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

---

## Learning from Reviewer Corrections

Before transcribing, read `output/corrections/summary.md` if it exists. It is built by `scripts/collect_corrections.py` from the correction logs the scholar's saves record (`## ४. संशोधनलेखः` in `output/verified/page_XXX.md`):

* **OCR errors**: character-level patterns you misread before (for example `श्च` where the print has `ञ्च`, or a candrabindu typed for a printed anusvāra). Check every occurrence of these shapes against the scan.
* **Padaccheda errors**: splits the scholar corrected. Apply the same splitting to similar forms.
* **Misprints**: errors in the printed book itself. Transcribe them as printed in Section 1 and record the correction in Section 3 with `⚠️ मुद्रणदोषः`.

## Regenerating Padaccheda after Source Corrections

When asked to update padaccheda after the scholar's corrections, run `python3 scripts/padaccheda_worklist.py` and read `output/corrections/padaccheda_worklist.md`. For each listed sentence:

* Write the padaccheda of the **corrected source** sentence, following Section 2 rules above. Keep the same dandas and the same sentence boundaries, and keep the parts of the current padaccheda that are still correct.
* If the current padaccheda already fits the corrected source, leave `suggest` empty (nothing is proposed).
* Put the new sentence in the matching entry's `suggest` in `output/corrections/padaccheda_flags.json`, then run `python3 scripts/padaccheda_worklist.py --merge output/corrections/padaccheda_flags.json` and rebuild the portal.
