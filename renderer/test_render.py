"""Tests for the renderer. Run: python3 -m unittest -v test_render"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render  # noqa: E402

SUNRISE, SUNSET = "2026-10-22T07:12", "2026-10-22T17:59"
# Band under the hero temperature that the sun row occupies (x0, y0, x1, y1)
SUN_STRIP = (0, 140, 222, 174)


def sample(with_sun=True):
    with open(os.path.join(HERE, "sample.json")) as f:
        d = json.load(f)
    d["daily"].pop("sunrise", None)
    d["daily"].pop("sunset", None)
    if with_sun:
        d["daily"]["sunrise"] = [f"{t}T07:12" for t in d["daily"]["time"]]
        d["daily"]["sunset"] = [f"{t}T17:59" for t in d["daily"]["time"]]
    return d


def colors_in(img, box):
    px = img.load()
    x0, y0, x1, y1 = box
    return {px[x, y] for y in range(y0, y1) for x in range(x0, x1)}


class ClockParts(unittest.TestCase):
    def test_morning_time_drops_leading_zero(self):
        self.assertEqual(render.clock_parts(SUNRISE), ("7:12", "AM"))

    def test_evening_time_uses_twelve_hour_clock(self):
        self.assertEqual(render.clock_parts(SUNSET), ("5:59", "PM"))


class DaylightLabel(unittest.TestCase):
    def test_hours_and_minutes_between_sunrise_and_sunset(self):
        self.assertEqual(render.daylight_label(SUNRISE, SUNSET), "10H 47M")

    def test_minutes_are_zero_padded(self):
        self.assertEqual(render.daylight_label("2026-06-21T05:16", "2026-06-21T20:23"), "15H 07M")


class SunRow(unittest.TestCase):
    def test_sun_icons_are_drawn_in_yellow_under_the_hero(self):
        self.assertIn(render.YELLOW, colors_in(render.render(sample()), SUN_STRIP))

    def test_daylight_total_is_drawn_in_red_under_the_hero(self):
        self.assertIn(render.RED, colors_in(render.render(sample()), SUN_STRIP))

    def test_strip_stays_blank_when_feed_has_no_sunrise(self):
        # Regression guard: an old feed without sunrise/sunset must still render.
        self.assertEqual(colors_in(render.render(sample(with_sun=False)), SUN_STRIP), {render.WHITE})


if __name__ == "__main__":
    unittest.main()
