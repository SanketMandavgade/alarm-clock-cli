import unittest
from datetime import datetime, timedelta

from alarm_clock.parsing import ParseError, parse_when

NOW = datetime(2026, 10, 22, 14, 0, 0)


class AbsoluteTimes(unittest.TestCase):
    def check(self, text, expected, now=NOW):
        self.assertEqual(parse_when(text, now), expected)

    def test_24h_later_today(self):
        self.check("15:30", datetime(2026, 10, 22, 15, 30))

    def test_with_seconds(self):
        self.check("15:30:45", datetime(2026, 10, 22, 15, 30, 45))

    def test_12h_forms(self):
        self.check("3:30pm", datetime(2026, 10, 22, 15, 30))
        self.check("7pm", datetime(2026, 10, 22, 19, 0))
        self.check("  3:30 PM ", datetime(2026, 10, 22, 15, 30))

    def test_midnight_and_noon(self):
        self.check("12:00am", datetime(2026, 10, 23, 0, 0))   # passed today -> tomorrow
        self.check("12:00pm", datetime(2026, 10, 23, 12, 0))  # passed today -> tomorrow
        self.check("12:30am", datetime(2026, 10, 23, 0, 30))

    def test_past_time_rolls_to_tomorrow(self):
        self.check("13:59", datetime(2026, 10, 23, 13, 59))

    def test_exactly_now_rolls_to_tomorrow(self):
        self.check("14:00", datetime(2026, 10, 23, 14, 0))

    def test_rollover_across_month_end(self):
        self.check("07:00", datetime(2026, 11, 1, 7, 0), now=datetime(2026, 10, 31, 23, 30))


class RelativeTimes(unittest.TestCase):
    def test_durations(self):
        cases = {
            "90s": timedelta(seconds=90),
            "10m": timedelta(minutes=10),
            "1h30m": timedelta(hours=1, minutes=30),
            "in 5m": timedelta(minutes=5),
            "1h 30m 5s": timedelta(hours=1, minutes=30, seconds=5),
        }
        for text, delta in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_when(text, NOW), NOW + delta)


class RelativeBounds(unittest.TestCase):
    def test_exactly_24h_allowed(self):
        self.assertEqual(parse_when("24h", NOW), NOW + timedelta(hours=24))


class InvalidInput(unittest.TestCase):
    def test_error_message_does_not_echo_huge_input(self):
        with self.assertRaises(ParseError) as ctx:
            parse_when("x" * 5000, NOW)
        self.assertLess(len(str(ctx.exception)), 200)

    def test_rejected(self):
        for text in ["", "abc", "25:00", "24:00", "12:60", "13:00pm", "0:30am",
                     "7", "0m", "in", "7:5", "10:30:61", "-5m", "10:30:00:00",
                     "24h1s", "25h", "99999h", "999999999999h", "9" * 5000 + "h",
                     "\u0660\u0667:\u0663\u0660",   # Arabic-Indic digits
                     "\uff10\uff17:\uff13\uff10",   # full-width digits
                     "\u0661\u0660m"]:
            with self.subTest(text=text):
                with self.assertRaises(ParseError):
                    parse_when(text, NOW)


if __name__ == "__main__":
    unittest.main()
