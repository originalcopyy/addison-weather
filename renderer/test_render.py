"""Tests for the renderer. Run: python3 -m unittest -v test_render"""
import json
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render  # noqa: E402

SUNRISE, SUNSET = "2026-10-22T07:12", "2026-10-22T17:59"
# Band under the hero temperature that the sun row occupies (x0, y0, x1, y1)
SUN_STRIP = (0, 140, 222, 174)
# Inside of the black banner (x0, y0, x1, y1) and its right end where the clock and gauge live
BANNER = (14, 270, 386, 292)
GAUGE_END = (300, 270, 386, 292)
NOON = datetime(2026, 10, 25, 12, 59)  # "12:59 PM" is the widest clock string


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


def rightmost(img, box, color):
    px = img.load()
    x0, y0, x1, y1 = box
    xs = [x for y in range(y0, y1) for x in range(x0, x1) if px[x, y] == color]
    return max(xs) if xs else None


def rainy_wednesday():
    """Sample whose banner is the longest one: umbrella + 'TAKE AN UMBRELLA WEDNESDAY'."""
    d = sample()
    d["daily"]["time"] = ["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]
    d["daily"]["precipitation_probability_max"] = [0, 0, 0, 70, 0]
    d["daily"]["weather_code"] = [0, 0, 0, 61, 0]
    return d


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


class BatteryColor(unittest.TestCase):
    def test_half_or_more_fills_white(self):
        self.assertEqual(render.battery_color(82), render.WHITE)
        self.assertEqual(render.battery_color(50), render.WHITE)

    def test_twenty_to_forty_nine_fills_yellow(self):
        self.assertEqual(render.battery_color(49), render.YELLOW)
        self.assertEqual(render.battery_color(35), render.YELLOW)
        self.assertEqual(render.battery_color(20), render.YELLOW)

    def test_under_twenty_fills_red(self):
        self.assertEqual(render.battery_color(19), render.RED)
        self.assertEqual(render.battery_color(0), render.RED)


class FitBanner(unittest.TestCase):
    measure = staticmethod(lambda s: 8 * len(s))  # a fake 8 px per character font

    def fit(self, lead, hi, umb, max_right):
        return render.fit_banner(self.measure, lead, hi, umb, max_right)

    def test_keeps_text_that_fits(self):
        self.assertEqual(self.fit("TAKE AN UMBRELLA", "WEDNESDAY", True, 400), ("TAKE AN UMBRELLA", "WEDNESDAY", True))

    def test_shortens_the_day_name_when_too_wide(self):
        # 20 + 26 + 8*17 + 8*9 = 254 does not fit in 240; with "WED" it is 206
        self.assertEqual(self.fit("TAKE AN UMBRELLA", "WEDNESDAY", True, 240), ("TAKE AN UMBRELLA", "WED", True))

    def test_drops_the_umbrella_when_still_too_wide(self):
        self.assertEqual(self.fit("TAKE AN UMBRELLA", "WEDNESDAY", True, 190), ("TAKE AN UMBRELLA", "WED", False))

    def test_only_day_names_are_shortened(self):
        self.assertEqual(self.fit("FROST TONIGHT", "COVER PLANTS", False, 100), ("FROST TONIGHT", "COVER PLANTS", False))


class BatteryGauge(unittest.TestCase):
    def test_no_gauge_without_a_battery_reading(self):
        self.assertEqual(colors_in(render.render(sample(), now=NOON), GAUGE_END), {render.BLACK, render.WHITE})

    def test_full_battery_fills_white_only(self):
        self.assertEqual(colors_in(render.render(sample(), battery=82, now=NOON), GAUGE_END), {render.BLACK, render.WHITE})

    def test_low_battery_fills_yellow(self):
        self.assertIn(render.YELLOW, colors_in(render.render(sample(), battery=35, now=NOON), GAUGE_END))

    def test_critical_battery_shows_red(self):
        self.assertIn(render.RED, colors_in(render.render(sample(), battery=12, now=NOON), GAUGE_END))

    def test_out_of_range_readings_are_clamped(self):
        render.render(sample(), battery=130, now=NOON)
        render.render(sample(), battery=-5, now=NOON)

    def test_long_banner_never_runs_into_the_clock(self):
        img = render.render(rainy_wednesday(), battery=100, now=NOON)
        highlight_end = rightmost(img, BANNER, render.YELLOW)  # the yellow day name
        self.assertIsNotNone(highlight_end)
        # Everything right of the day name up to the clock is a solid black gap
        gap = (highlight_end + 1, 270, highlight_end + 8, 292)
        self.assertEqual(colors_in(img, gap), {render.BLACK})
        self.assertLess(highlight_end, render.W - 140)


if __name__ == "__main__":
    unittest.main()
