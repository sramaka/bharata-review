#!/usr/bin/env python3
"""
Local Review & Verification HTTP Server
Serves the proofreading bundle and handles direct POST requests to save verified
pages directly into output/verified/ without browser download prompts.
"""

import http.server
import json
import os
import sys

PORT = 8000
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VERIFIED_DIR = os.path.join(BASE_DIR, "output", "verified")

class ReviewHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS for local testing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path == "/save_verified":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode("utf-8"))

                page_num = str(payload.get("page", "")).zfill(3)
                content = payload.get("content", "")

                if not page_num or not content:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Missing page or content"}).encode("utf-8"))
                    return

                os.makedirs(VERIFIED_DIR, exist_ok=True)
                out_file = os.path.join(VERIFIED_DIR, f"page_{page_num}.md")

                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(content)

                print(f"[Saved] Successfully written verified page to: {out_file}")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "file": f"page_{page_num}.md"}).encode("utf-8"))

            except Exception as e:
                print(f"[Error] Failed to save verified page: {e}", file=sys.stderr)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    os.chdir(BASE_DIR)
    os.makedirs(VERIFIED_DIR, exist_ok=True)
    server_address = ("", PORT)
    httpd = http.server.HTTPServer(server_address, ReviewHandler)
    print("=" * 60)
    print(f"Bhārata Saṅgraha Local Review Server")
    print(f"Running at: http://localhost:{PORT}/output/proofread_bundle.html")
    print(f"Verified files target: {VERIFIED_DIR}")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Shutting down] Server stopped.")

if __name__ == "__main__":
    run_server()