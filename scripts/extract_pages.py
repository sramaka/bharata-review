#!/usr/bin/env python3
"""
Sanskrit OCR Pipeline - High-DPI Page Extractor
Converts specified PDF pages to 300 DPI PNG images for OCR processing.

Usage:
    python3 scripts/extract_pages.py START_PAGE END_PAGE [--dpi DPI]
"""
import argparse
import sys
from pathlib import Path
import pymupdf

# Workspace paths
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
INPUT_PDF = WORKSPACE_DIR / "input_pdf" / "bharata_sangraha.pdf"
OUTPUT_DIR = WORKSPACE_DIR / "page_images"

DEFAULT_DPI = 300

def render_pages(pdf_path: Path, output_dir: Path, start: int, end: int, dpi: int):
    if not pdf_path.exists():
        print(f"[Error] Source PDF not found at: {pdf_path}")
        sys.exit(1)
        
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    print(f"[Info] Opened '{pdf_path.name}' (Total Pages: {total_pages})")
    print(f"[Info] Extracting pages {start} to {end} at {dpi} DPI...")
    
    # Calculate zoom factor (72 DPI is standard baseline)
    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    
    for page_num in range(start, end + 1):
        if page_num < 1 or page_num > total_pages:
            print(f"[Warning] Page {page_num} is out of bounds. Skipping.")
            continue
            
        # Convert to 0-indexed
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        output_filename = output_dir / f"page_{page_num:03d}.png"
        pix.save(output_filename)
        print(f"  └─ Extracted: {output_filename.relative_to(WORKSPACE_DIR)}")
        
    doc.close()
    print("[Success] Page extraction complete.")

def parse_args():
    parser = argparse.ArgumentParser(description="Render PDF pages to PNG images for OCR.")
    parser.add_argument("start", type=int, help="First page to extract (1-indexed, inclusive)")
    parser.add_argument("end", type=int, help="Last page to extract (1-indexed, inclusive)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"Render resolution (default: {DEFAULT_DPI})")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("start page must not be greater than end page")
    return args

if __name__ == "__main__":
    args = parse_args()
    render_pages(INPUT_PDF, OUTPUT_DIR, args.start, args.end, args.dpi)
