#!/usr/bin/env python3
"""
Reviewer Marks Addressed to the AI
Lists the words the scholar marked "AI-परीक्षणाय (ask the AI to check)" in saved pages
(the '५. समीक्षाचिह्नानि' table in output/verified/page_XXX.md), so the agent can answer them:

  python3 scripts/review_marks.py
      → output/corrections/ai_review_requests.md     each marked word with its sentence and note
      → output/corrections/ai_review_replies.json    one reply skeleton per mark

For each entry the agent either proposes a correction (fill "suggest"; set "kind" to "ocr",
"print" or "pada") or explains that no change is needed (leave "suggest" empty, keep
"kind": "reply", write the reasoning in "note"). Then:

  python3 scripts/review_marks.py --merge output/corrections/ai_review_replies.json
      → adds the answers to output/review_flags.json; the scholar sees them on the marked words
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_html_review import VERIFIED_DIR, REVIEW_FLAGS_JSON, parse_sections, parse_review_marks  # noqa: E402
from padaccheda_worklist import merge_flags, sentences, norm  # noqa: E402

OUT_DIR = "output/corrections"


def build_requests(verified_dir):
    requests = []
    for v_path in sorted(glob.glob(os.path.join(verified_dir, "page_*.md"))):
        page = re.search(r"page_(\d+)\.md", os.path.basename(v_path)).group(1)
        with open(v_path, encoding="utf-8") as f:
            text = f.read()
        sec1, sec2, _, _ = parse_sections(text)
        for m in parse_review_marks(text):
            if m["target"] != "askai":
                continue
            section_text = sec1 if m["section"] == "sec1" else sec2
            sentence = next((s for s in sentences(section_text) if m["match"] in s), "")
            requests.append({"page": page, **m, "sentence": norm(sentence)})
    return requests


def write_outputs(requests, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    md = ["# Words the Scholar Asked the AI to Check", "",
          f"{len(requests)} marked word(s). Check each against the scan (`page_images/page_XXX.png`) and the grammar,",
          "then answer in `ai_review_replies.json`: fill `suggest` (and set `kind` to ocr / print / pada) to propose a",
          "correction, or leave `suggest` empty with `kind: \"reply\"` and explain in `note` why no change is needed.", ""]
    replies = []
    for r in requests:
        where = "मूलपाठः" if r["section"] == "sec1" else "पदच्छेदः"
        md += [f"## Page {r['page']} · {where} · {r['match']}", "",
               f"- Scholar's note: {r['note'] or '—'}",
               f"- Sentence: {r['sentence']}", ""]
        replies.append({"page": r["page"], "section": r["section"], "match": r["match"],
                        "suggest": "", "kind": "reply", "note": ""})
    with open(os.path.join(out_dir, "ai_review_requests.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    with open(os.path.join(out_dir, "ai_review_replies.json"), "w", encoding="utf-8") as f:
        json.dump(replies, f, ensure_ascii=False, indent=2)
    print(f"[Success] {len(requests)} word(s) marked for the AI → {out_dir}/ai_review_requests.md, ai_review_replies.json")


def main():
    parser = argparse.ArgumentParser(description="List words the scholar marked for the AI to check.")
    parser.add_argument("--verified-dir", default=VERIFIED_DIR)
    parser.add_argument("--out", default=OUT_DIR)
    parser.add_argument("--merge", metavar="FILE", help="merge filled-in replies from FILE into the review flags")
    parser.add_argument("--flags", default=REVIEW_FLAGS_JSON, help="review flags file to merge into")
    args = parser.parse_args()
    if args.merge:
        # A reply counts once it proposes a correction or explains why none is needed
        merge_flags(args.merge, args.flags, keep=lambda e: e.get("suggest", "").strip() or e.get("note", "").strip())
    else:
        write_outputs(build_requests(args.verified_dir), args.out)


if __name__ == "__main__":
    main()
