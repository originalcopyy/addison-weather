"""On-demand front for the renderer: every request gets a freshly drawn frame.

Vercel runs this through api/weather.py; it has no state and no cache, so the
clock and forecast in the picture are always from the moment of the fetch.
  GET /weather.bin?batt=82   -> 30,000-byte panel frame with the gauge at 82 %
  GET /weather.png?batt=82   -> preview PNG of the same frame
"""
import io
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

from PIL import Image  # noqa: E402


def battery_from(query):
    """Battery percent from a query string ('batt=82'), clamped to 0-100, or None."""
    raw = parse_qs(query).get("batt", [None])[0]
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return None


def respond(path, fetch=render.fetch_live):
    """Return (status, content_type, body) for a request path such as /weather.bin?batt=82."""
    u = urlparse(path)
    want_png = u.path.endswith(".png") or parse_qs(u.query).get("fmt", [""])[0] == "png"
    try:
        data = fetch()
    except Exception as e:  # the device keeps its old picture and retries later
        return 502, "text/plain", f"weather feed unavailable: {e}".encode()
    img = render.render(data, battery=battery_from(u.query))
    if want_png:
        buf = io.BytesIO()
        render.preview(img).resize((render.W * 2, render.H * 2), Image.NEAREST).save(buf, "PNG")
        return 200, "image/png", buf.getvalue()
    return 200, "application/octet-stream", render.encode(img)
