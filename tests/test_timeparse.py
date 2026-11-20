import unittest
from helpers import ROOT  # noqa
from vf.timeparse import parse_stamp, find_clock_times


class Stamps(unittest.TestCase):
    def test_three_formats_same_instant(self):
        a = parse_stamp(1772504040000)
        b = parse_stamp("2026-03-02T21:14:00-05:00")
        self.assertEqual((a.kind, b.kind), ("abs", "abs"))
        self.assertAlmostEqual(a.seconds, b.seconds)

    def test_epoch_seconds_vs_ms(self):
        self.assertAlmostEqual(parse_stamp("1772504040").seconds, parse_stamp("1772504040000").seconds)

    def test_naive_is_not_guessed(self):
        s = parse_stamp("2026-03-02 21:10:19")
        self.assertEqual(s.kind, "naive")
        self.assertIsNone(s.offset)

    def test_time_of_day_and_ampm(self):
        self.assertEqual(parse_stamp("21:15").seconds, 21 * 3600 + 15 * 60)
        self.assertEqual(parse_stamp("9:05 PM").seconds, 21 * 3600 + 5 * 60)

    def test_garbage_is_none(self):
        for bad in ("", "abc", "25:99", "2026-13-40 10:00:00", 12, None, True, "12345"):
            self.assertIsNone(parse_stamp(bad), bad)

    def test_text_times(self):
        self.assertEqual(find_clock_times("about 21:16.")[0][0], 21 * 3600 + 16 * 60)
        self.assertEqual(find_clock_times("2026-03-02 no clock here"), [])


if __name__ == "__main__":
    unittest.main()
