"""Tests for the on-demand HTTP front (what Vercel runs). Run: python3 -m unittest -v test_serve"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import serve  # noqa: E402


def feed():
    with open(os.path.join(HERE, "sample.json")) as f:
        return json.load(f)


class Respond(unittest.TestCase):
    def test_default_is_the_panel_frame(self):
        status, ctype, body = serve.respond("/weather.bin?batt=82", fetch=feed)
        self.assertEqual((status, ctype, len(body)), (200, "application/octet-stream", 30000))

    def test_png_preview_on_request(self):
        status, ctype, body = serve.respond("/api/weather?fmt=png", fetch=feed)
        self.assertEqual((status, ctype, body[:4]), (200, "image/png", b"\x89PNG"))

    def test_png_by_extension(self):
        self.assertEqual(serve.respond("/weather.png", fetch=feed)[1], "image/png")

    def test_bad_battery_value_is_ignored(self):
        self.assertEqual(serve.respond("/weather.bin?batt=abc", fetch=feed)[0], 200)

    def test_feed_failure_is_a_502_not_a_crash(self):
        def broken():
            raise OSError("timed out")
        status, ctype, body = serve.respond("/weather.bin", fetch=broken)
        self.assertEqual(status, 502)
        self.assertIn(b"timed out", body)

    def test_battery_parsing(self):
        self.assertEqual(serve.battery_from("batt=82"), 82)
        self.assertEqual(serve.battery_from("batt=250"), 100)
        self.assertIsNone(serve.battery_from(""))
        self.assertIsNone(serve.battery_from("batt=x"))


if __name__ == "__main__":
    unittest.main()
