#!/usr/bin/env python3
"""Render an Addison, IL weather board for the ZecTrix Note 4C (400x300 BWRY e-paper).

Outputs:
  out/weather.bin  30,000 bytes, SSD2683 2bpp stream (what the device downloads)
  out/weather.png  preview in true panel colors

Usage:
  python3 render.py                 # live data from Open-Meteo (no API key)
  python3 render.py --sample sample.json
"""
import argparse
import json
import math
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- config
LAT, LON = 41.9317, -87.9890            # Addison, IL
TZ = "America/Chicago"
PLACE = "ADDISON"
W, H = 400, 300

# Pure panel colors (drawing uses only these, no antialiasing)
BLACK, WHITE, YELLOW, RED = (0, 0, 0), (255, 255, 255), (255, 200, 0), (200, 0, 0)
# SSD2683 2-bit codes (from the vendor driver): 00 black, 01 white, 10 yellow, 11 red
CODE = {BLACK: 0b00, WHITE: 0b01, YELLOW: 0b10, RED: 0b11}
# What the preview PNG looks like (closer to real pigment)
PREVIEW = {BLACK: (34, 34, 34), WHITE: (236, 236, 230), YELLOW: (232, 184, 48), RED: (176, 44, 44)}

HERE = os.path.dirname(os.path.abspath(__file__))


def font(weight, size):
    return ImageFont.truetype(os.path.join(HERE, "fonts", f"BarlowCondensed-{weight}.ttf"), size)


# ---------------------------------------------------------------- data
def fetch_live():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&current=temperature_2m,weather_code,is_day"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"
        "&temperature_unit=fahrenheit&timezone=America%2FChicago&forecast_days=5"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "note4c-weather/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def kind(code, is_day=1):
    """Map WMO weather code to an icon kind + short label."""
    if code == 0:
        return ("clear" if is_day else "night"), ("SUNNY" if is_day else "CLEAR")
    if code in (1, 2):
        return ("partly" if is_day else "night_cloud"), ("MOSTLY SUNNY" if code == 1 else "PARTLY CLOUDY")
    if code == 3:
        return "cloud", "OVERCAST"
    if code in (45, 48):
        return "fog", "FOGGY"
    if code in (51, 53, 55, 56, 57):
        return "rain", "DRIZZLE"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain", "RAIN" if code < 80 else "SHOWERS"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow", "SNOW"
    if code in (95, 96, 99):
        return "storm", "T-STORMS"
    return "cloud", "CLOUDY"


# ---------------------------------------------------------------- icons
def cloud(d, x, y, s, fill=WHITE, stroke=BLACK):
    """Cloud whose bounding box is roughly (x, y) .. (x+s, y+0.62s)."""
    parts = [
        ("e", x + 0.00 * s, y + 0.30 * s, x + 0.40 * s, y + 0.62 * s),
        ("e", x + 0.18 * s, y + 0.06 * s, x + 0.66 * s, y + 0.54 * s),
        ("e", x + 0.52 * s, y + 0.22 * s, x + 1.00 * s, y + 0.62 * s),
        ("r", x + 0.20 * s, y + 0.40 * s, x + 0.80 * s, y + 0.62 * s),
    ]
    t = max(2, round(s / 26))
    for col, grow in ((stroke, t), (fill, 0)):
        for k, a, b, c, e in parts:
            box = [a - grow, b - grow, c + grow, e + grow]
            (d.ellipse if k == "e" else d.rectangle)(box, fill=col)


def sun(d, cx, cy, r, color=YELLOW):
    w = max(2, round(r / 5))
    for i in range(8):
        a = math.pi / 4 * i
        d.line(
            [cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35,
             cx + math.cos(a) * r * 1.85, cy + math.sin(a) * r * 1.85],
            fill=color, width=w,
        )
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def moon(d, cx, cy, r, bg=WHITE):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=YELLOW)
    o = r * 0.55
    d.ellipse([cx - r + o, cy - r - o * 0.4, cx + r + o, cy + r - o * 0.4], fill=bg)


def icon(d, k, x, y, s):
    """Draw icon k in an s x s box at (x, y)."""
    if k == "clear":
        sun(d, x + s / 2, y + s / 2, s * 0.24)
    elif k == "night":
        moon(d, x + s / 2, y + s / 2, s * 0.32)
    elif k == "partly":
        sun(d, x + s * 0.36, y + s * 0.34, s * 0.17)
        cloud(d, x + s * 0.12, y + s * 0.36, s * 0.84)
    elif k == "night_cloud":
        moon(d, x + s * 0.40, y + s * 0.34, s * 0.22)
        cloud(d, x + s * 0.12, y + s * 0.36, s * 0.84)
    elif k == "cloud":
        cloud(d, x + s * 0.04, y + s * 0.18, s * 0.92)
    elif k == "fog":
        cloud(d, x + s * 0.08, y + s * 0.08, s * 0.84)
        t = max(2, round(s / 22))
        for i, (a, b) in enumerate(((0.10, 0.80), (0.24, 0.92))):
            yy = y + s * (0.72 + i * 0.13)
            d.line([x + s * a, yy, x + s * b, yy], fill=BLACK, width=t)
    elif k in ("rain", "snow", "storm"):
        cloud(d, x + s * 0.08, y + s * 0.04, s * 0.84)
        if k == "storm":
            bolt = [(0.52, 0.56), (0.38, 0.80), (0.50, 0.80), (0.42, 1.00), (0.66, 0.72), (0.53, 0.72), (0.60, 0.56)]
            d.polygon([(x + s * a, y + s * b) for a, b in bolt], fill=YELLOW, outline=BLACK)
        else:
            r = max(2, s / 18)
            for i in range(3):
                cx, cy = x + s * (0.30 + 0.20 * i), y + s * 0.80
                if k == "rain":
                    d.ellipse([cx - r, cy - r * 1.4, cx + r, cy + r * 1.4], fill=BLACK)
                else:
                    t = max(1, round(s / 30))
                    for a in range(3):
                        ang = math.pi / 3 * a
                        dx, dy = math.cos(ang) * r * 1.6, math.sin(ang) * r * 1.6
                        d.line([cx - dx, cy - dy, cx + dx, cy + dy], fill=BLACK, width=t)


def umbrella(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    d.pieslice([cx - r * 0.7, cy - r * 0.6, cx + r * 0.7, cy + r * 0.5], 180, 360, fill=YELLOW)
    d.line([cx, cy - r * 0.05, cx, cy + r * 0.55], fill=BLACK, width=2)


def sun_marker(d, x, y, rising):
    """Sunrise/sunset glyph in an 18 x 16 box at (x, y): arrow, yellow half-disc, horizon line."""
    cx = x + 9
    tri = [(cx - 4, y + 5), (cx + 4, y + 5), (cx, y + 1)] if rising else [(cx - 4, y + 1), (cx + 4, y + 1), (cx, y + 5)]
    d.polygon(tri, fill=BLACK)
    d.pieslice([cx - 7, y + 7, cx + 7, y + 21], 180, 360, fill=YELLOW)
    d.line([x, y + 14, x + 18, y + 14], fill=BLACK, width=2)


# ---------------------------------------------------------------- text helpers
def text(d, xy, s, f, fill=BLACK, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)
    return d.textlength(s, font=f)


def deg(n):
    return f"{round(n)}°"


def clock_parts(iso):
    """'2026-10-22T07:12' -> ('7:12', 'AM')"""
    t = datetime.fromisoformat(iso)
    return t.strftime("%-I:%M"), t.strftime("%p")


def daylight_label(sunrise, sunset):
    """Daylight between two local ISO timestamps, e.g. '10H 47M'."""
    mins = round((datetime.fromisoformat(sunset) - datetime.fromisoformat(sunrise)).total_seconds() / 60)
    return f"{mins // 60}H {mins % 60:02d}M"


# ---------------------------------------------------------------- banner logic
def banner(days, now):
    """Return (lead_text, highlight_text, show_umbrella)."""
    names = ["TODAY"] + [datetime.fromisoformat(t).strftime("%A").upper() for t in days["time"][1:]]
    for i in range(0, 4):
        k, _ = kind(days["weather_code"][i])
        pop = days["precipitation_probability_max"][i] or 0
        if k == "snow" and pop >= 40:
            return "SNOW EXPECTED", names[i], False
        if k == "storm" and pop >= 40:
            return "STORMS POSSIBLE", names[i], True
        if pop >= 50:
            return "TAKE AN UMBRELLA", names[i], True
    if days["temperature_2m_min"][0] <= 32:
        return "FROST TONIGHT", "COVER PLANTS", False
    for i in range(0, 4):
        if days["temperature_2m_max"][i] >= 90:
            return "HOT DAY", names[i], False
    return "NO RAIN IN SIGHT", "", False


# ---------------------------------------------------------------- layout
def render(data):
    tz = ZoneInfo(TZ)
    now = datetime.now(tz)
    cur, days = data["current"], data["daily"]

    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # no antialiasing -> only pure panel colors

    # --- hero: icon + current temperature
    k, label = kind(cur["weather_code"], cur.get("is_day", 1))
    icon(d, k, 10, 30, 92)
    t = str(round(cur["temperature_2m"]))
    tf = font(800, 112 if len(t) <= 2 else 88)
    l, tp, r, _ = d.textbbox((206, 92), t, font=tf, anchor="rm")
    text(d, (206, 92), t, tf, anchor="rm")
    d.ellipse([r + 3, tp + 2, r + 15, tp + 14], outline=BLACK, width=3)

    # --- sunrise / sunset / daylight, under the hero
    if days.get("sunrise") and days.get("sunset"):
        sr, ss = days["sunrise"][0], days["sunset"][0]
        y, x = 164, 14  # baseline, left edge
        for iso, rising in ((sr, True), (ss, False)):
            sun_marker(d, x, y - 16, rising)
            x += 20
            hm, ap = clock_parts(iso)
            x += text(d, (x, y), hm, font(700, 20), anchor="ls") + 1
            x += text(d, (x, y), ap, font(700, 12), anchor="ls") + 6
        text(d, (212, y), daylight_label(sr, ss), font(800, 15), fill=RED, anchor="rs")

    # divider
    d.line([226, 16, 226, 160], fill=BLACK, width=2)

    # --- right panel
    x0 = 238
    text(d, (x0, 10), PLACE, font(800, 36))
    text(d, (x0, 42), "WEATHER", font(800, 36), fill=RED)
    d.line([x0, 84, 390, 84], fill=BLACK, width=2)
    text(d, (x0, 90), now.strftime("%A / %b %-d").upper(), font(600, 20))
    tk, tlabel = kind(days["weather_code"][0])
    icon(d, tk, x0 - 2, 112, 30)
    text(d, (x0 + 32, 127), tlabel, font(600, 19), anchor="lm")
    # HI | LO
    y = 160
    fx, fn = font(700, 18), font(800, 28)
    x = x0
    x += text(d, (x, y), "HI", fx, anchor="ls") + 5
    x += text(d, (x, y), deg(days["temperature_2m_max"][0]), fn, fill=RED, anchor="ls") + 10
    d.line([x, y - 20, x, y - 2], fill=BLACK, width=2)
    x += 10
    x += text(d, (x, y), "LO", fx, anchor="ls") + 5
    text(d, (x, y), deg(days["temperature_2m_min"][0]), fn, anchor="ls")

    # --- three-day cards
    cw, ch, gap, top = 122, 84, 7, 176
    for i in range(3):
        j = i + 1
        cx = 10 + i * (cw + gap)
        d.rounded_rectangle([cx, top, cx + cw, top + ch], radius=4, outline=BLACK, width=2)
        dt = datetime.fromisoformat(days["time"][j])
        weekend = dt.weekday() >= 5
        text(d, (cx + 8, top + 4), dt.strftime("%a").upper(), font(800, 20), fill=RED if weekend else BLACK)
        ck, _ = kind(days["weather_code"][j])
        icon(d, ck, cx + 6, top + 28, 50)
        rx = cx + cw - 8
        text(d, (rx, top + 30), deg(days["temperature_2m_max"][j]), font(800, 36), anchor="rm")
        lf, vf = font(700, 13), font(800, 16)
        for row, (lbl, val, col) in enumerate(
            (("HI", days["temperature_2m_max"][j], RED), ("LO", days["temperature_2m_min"][j], BLACK))
        ):
            yy = top + 60 + row * 16
            vw = d.textlength(deg(val), font=vf)
            text(d, (rx, yy), deg(val), vf, fill=col, anchor="rm")
            text(d, (rx - vw - 4, yy), lbl, lf, anchor="rm")

    # --- banner
    by = 268
    d.rounded_rectangle([10, by, 390, by + 26], radius=4, fill=BLACK)
    lead, hi, umb = banner(days, now)
    bx = 20
    if umb:
        umbrella(d, bx + 10, by + 13, 10)
        bx += 26
    bf = font(700, 19)
    bx += text(d, (bx, by + 13), lead + " ", bf, fill=WHITE, anchor="lm")
    text(d, (bx, by + 13), hi, bf, fill=YELLOW, anchor="lm")
    text(d, (382, by + 13), now.strftime("%-I:%M %p"), font(600, 15), fill=WHITE, anchor="rm")
    return img


# ---------------------------------------------------------------- encode
def nearest(rgb):
    return min(CODE, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, rgb)))


def encode(img):
    """Pack to SSD2683 2bpp: 4 px per byte, leftmost pixel in the top bits, 100 bytes per row."""
    px = img.load()
    out = bytearray()
    cache = {}
    for y in range(H):
        for xb in range(0, W, 4):
            b = 0
            for k in range(4):
                c = px[xb + k, y]
                if c not in cache:
                    cache[c] = CODE[nearest(c)]
                b = (b << 2) | cache[c]
            out.append(b)
    assert len(out) == W * H // 4
    return bytes(out)


def preview(img):
    p = img.copy()
    px = p.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = PREVIEW[nearest(px[x, y])]
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="render from a saved Open-Meteo JSON file instead of fetching")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    data = json.load(open(a.sample)) if a.sample else fetch_live()
    img = render(data)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "weather.bin"), "wb") as f:
        f.write(encode(img))
    preview(img).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(a.out, "weather.png"))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
