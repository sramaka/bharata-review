#!/usr/bin/env python3
"""
Correction Log Collector
Reads the "४. संशोधनलेखः (Correction Log)" tables that the review portal writes into each
saved page, and produces feedback for the transcription agent:

  output/corrections/corrections.jsonl   one JSON object per logged change
  output/corrections/summary.md          counts and recurring patterns per kind of error,
                                         ready to paste into config/agent_rules.md

Usage:
    python3 scripts/collect_corrections.py [--dir output/verified] [--out output/corrections]
"""
import argparse
import collections
import difflib
import glob
import json
import os
import re

CATEGORY_BY_BADGE = {
    "🔍 OCR-दोषः": "ocr",
    "⚠️ मुद्रणदोषः": "misprint",
    "✂️ पदच्छेददोषः": "pada",
    "✏️ अन्यत्": "other",
}
CATEGORY_TITLES = {
    "ocr": "OCR errors (transcription did not match the scan)",
    "misprint": "Misprints in the printed book",
    "pada": "Padaccheda errors (AI sandhi / compound splitting)",
    "other": "Other edits",
}
SECTION_BY_LABEL = {"मूलपाठः": "sec1", "पदच्छेदः": "sec2"}
DEV_TO_ASCII = str.maketrans("०१२३४५६७८९", "0123456789")


def cell(text):
    text = text.strip()
    return "" if text == "∅" else text.replace(" ↵ ", "\n")


def parse_log(md_text):
    """Return the rows of the correction log table in one saved page."""
    lines = md_text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if "४. संशोधनलेख" in l)
    except StopIteration:
        return []
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
            "n": int(cells[0].translate(DEV_TO_ASCII) or 0),
            "section": SECTION_BY_LABEL.get(cells[1], cells[1]),
            "category": CATEGORY_BY_BADGE.get(cells[2], "other"),
            "before": cell(cells[3]),
            "after": cell(cells[4]),
            "context": cells[5],
            "source": "ai" if cells[6].startswith("AI") else "reviewer",
            "note": cells[7],
        })
    return rows


def substitution_pairs(before, after):
    """Character-level replacements inside a changed word, e.g. ('श्च', 'ञ्च')."""
    pairs = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op != "equal":
            pairs.append((before[a0:a1] or "∅", after[b0:b1] or "∅"))
    return pairs


def write_summary(entries, path):
    by_cat = collections.defaultdict(list)
    for e in entries:
        by_cat[e["category"]].append(e)
    pages = sorted({e["page"] for e in entries})
    out = ["# Correction Summary", "",
           f"{len(entries)} logged change(s) on {len(pages)} page(s): {', '.join(pages)}.", ""]
    for cat in ("ocr", "pada", "misprint", "other"):
        items = by_cat.get(cat, [])
        if not items:
            continue
        out += [f"## {CATEGORY_TITLES[cat]} — {len(items)}", ""]
        patterns = collections.Counter(p for e in items for p in substitution_pairs(e["before"], e["after"]))
        if patterns and cat in ("ocr", "pada"):
            out += ["Recurring character-level patterns (printed/AI form → corrected):", ""]
            out += [f"- `{a}` → `{b}` ({n}×)" for (a, b), n in patterns.most_common(15)]
            out.append("")
        out += ["| Page | Before | After | Context | Source | Note |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
        for e in items:
            out.append(f"| {e['page']} | {e['before'] or '∅'} | {e['after'] or '∅'} | {e['context']} | {e['source']} | {e['note']} |")
        out.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def main():
    parser = argparse.ArgumentParser(description="Collect correction logs from saved pages.")
    parser.add_argument("--dir", default="output/verified", help="folder of saved page_XXX.md files")
    parser.add_argument("--out", default="output/corrections", help="folder for corrections.jsonl and summary.md")
    args = parser.parse_args()

    entries = []
    for md_path in sorted(glob.glob(os.path.join(args.dir, "page_*.md"))):
        page = re.search(r"page_(\d+)\.md", os.path.basename(md_path)).group(1)
        with open(md_path, encoding="utf-8") as f:
            for row in parse_log(f.read()):
                entries.append({"page": page, **row})

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "corrections.jsonl"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    write_summary(entries, os.path.join(args.out, "summary.md"))
    counts = collections.Counter(e["category"] for e in entries)
    print(f"[Success] {len(entries)} correction(s) from {args.dir}/ → {args.out}/ "
          f"({', '.join(f'{k}: {v}' for k, v in sorted(counts.items())) or 'none'})")


if __name__ == "__main__":
    main()
