#!/usr/bin/env python3
"""
Padaccheda Regeneration Worklist
Finds sentences whose मूलपाठः the scholar corrected (output/verified/ vs output/raw/) but whose
पदच्छेदः was neither updated nor confirmed as still correct, so the transcription agent can
redo the padaccheda for just those sentences.

  python3 scripts/padaccheda_worklist.py
      → output/corrections/padaccheda_worklist.md    sentences to redo, for the agent to read
      → output/corrections/padaccheda_flags.json     review-flag skeletons with empty "suggest"

The agent fills in each "suggest" with the new padaccheda sentence, then:

  python3 scripts/padaccheda_worklist.py --merge output/corrections/padaccheda_flags.json
      → adds the filled entries to output/review_flags.json as kind "pada" flags, which the
        scholar reviews and accepts in the portal like any other AI suggestion
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_html_review import (  # noqa: E402
    RAW_DIR, VERIFIED_DIR, REVIEW_FLAGS_JSON, parse_sections, parse_correction_log, page_metadata,
)

OUT_DIR = "output/corrections"
SENTENCE = re.compile(r"[^।॥]*[।॥]+[’'\"”]*\s*|[^।॥]+$")


def sentences(text):
    return [m.group(0) for m in SENTENCE.finditer(text or "") if m.group(0)]


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def build_worklist(raw_dir, verified_dir):
    items = []
    for v_path in sorted(glob.glob(os.path.join(verified_dir, "page_*.md"))):
        page = re.search(r"page_(\d+)\.md", os.path.basename(v_path)).group(1)
        raw_path = os.path.join(raw_dir, f"page_{page}.md")
        if not os.path.exists(raw_path):
            continue
        with open(raw_path, encoding="utf-8") as f:
            raw1, raw2, _, _ = parse_sections(f.read())
        with open(v_path, encoding="utf-8") as f:
            v_text = f.read()
        ver1, ver2, _, _ = parse_sections(v_text)
        if not raw2:
            continue    # no padaccheda on this page (English front matter)
        log = parse_correction_log(v_text)
        confirmed = [e for e in log if e["section"] == "sec1" and e["pada"] == "confirmed"]

        rs1, vs1, rs2, vs2 = sentences(raw1), sentences(ver1), sentences(raw2), sentences(ver2)
        if not (len(rs1) == len(vs1) == len(rs2) == len(vs2)):
            print(f"[Warning] page {page}: danda counts differ between sections; check this page by hand.")
            continue
        for i, (old_src, new_src) in enumerate(zip(rs1, vs1)):
            if norm(old_src) == norm(new_src):
                continue
            if norm(rs2[i]) != norm(vs2[i]):
                continue    # the scholar already updated this padaccheda
            if any(e["after"].strip() and e["after"].strip() in new_src for e in confirmed):
                continue    # the scholar confirmed the padaccheda is still correct
            items.append({
                "page": page,
                "label": page_metadata(int(page))["section"],
                "sentence": i + 1,
                "original_source": norm(old_src),
                "corrected_source": norm(new_src),
                "current_padaccheda": norm(vs2[i]),
            })
    return items


def write_outputs(items, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    md = ["# Padaccheda Worklist", "",
          f"{len(items)} sentence(s) whose मूलपाठः was corrected by the scholar but whose पदच्छेदः has not been updated.",
          "For each, write a new padaccheda of the corrected source sentence, following `config/agent_rules.md`",
          "(same sentence boundaries and dandas), into the matching entry's `suggest` in `padaccheda_flags.json`.", ""]
    flags = []
    for it in items:
        md += [f"## Page {it['page']} · sentence {it['sentence']}", "",
               f"- Original source: {it['original_source']}",
               f"- **Corrected source:** {it['corrected_source']}",
               f"- Current padaccheda (to replace): {it['current_padaccheda']}", ""]
        flags.append({
            "page": it["page"],
            "section": "sec2",
            "match": it["current_padaccheda"],
            "suggest": "",
            "kind": "pada",
            "note": f"मूलपाठः संशोधितः, अतः पदच्छेदः नवीकृतः (the source sentence was corrected to: {it['corrected_source']})",
        })
    with open(os.path.join(out_dir, "padaccheda_worklist.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    with open(os.path.join(out_dir, "padaccheda_flags.json"), "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)
    print(f"[Success] {len(items)} sentence(s) to redo → {out_dir}/padaccheda_worklist.md, padaccheda_flags.json")


def merge_flags(path, flags_json):
    with open(path, encoding="utf-8") as f:
        filled = [e for e in json.load(f) if e.get("suggest", "").strip()]
    review = {}
    if os.path.exists(flags_json):
        with open(flags_json, encoding="utf-8") as f:
            review = json.load(f)
    added = 0
    for e in filled:
        page = e.pop("page")
        page_flags = review.setdefault(page, [])
        if any(f.get("section") == e["section"] and f.get("match") == e["match"] for f in page_flags):
            continue
        page_flags.append(e)
        added += 1
    with open(flags_json, "w", encoding="utf-8") as f:
        json.dump(review, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[Success] added {added} padaccheda suggestion(s) to {flags_json}; rebuild the portal to show them.")


def main():
    parser = argparse.ArgumentParser(description="List padaccheda sentences to regenerate after source corrections.")
    parser.add_argument("--raw-dir", default=RAW_DIR)
    parser.add_argument("--verified-dir", default=VERIFIED_DIR)
    parser.add_argument("--out", default=OUT_DIR)
    parser.add_argument("--merge", metavar="FILE", help="merge filled-in suggestions from FILE into the review flags")
    parser.add_argument("--flags", default=REVIEW_FLAGS_JSON, help="review flags file to merge into")
    args = parser.parse_args()
    if args.merge:
        merge_flags(args.merge, args.flags)
    else:
        write_outputs(build_worklist(args.raw_dir, args.verified_dir), args.out)


if __name__ == "__main__":
    main()
