"""Vercel entry point: GET /weather.bin?batt=82 (see renderer/serve.py for the logic)."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "renderer"))
import serve  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, ctype, body = serve.respond(self.path)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # Vercel captures stdout; keep the default noise down
        pass
