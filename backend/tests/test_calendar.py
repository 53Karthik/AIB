import unittest
from datetime import datetime

from backend.engine.calendar import Calendar
from backend.engine.datetime import parse_stamp, iso_of, hours_between
from backend.engine.outcome import judge, norm


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.calendar = Calendar(["2026-03-17", "2025-12-25", "2025-12-26"])

    def test_timestamp_formats(self):
        for value in ("26/08/2026 22:11:38", 46260.92474537037,
                      "46260.92474537037", "2026-08-26T22:11:38Z",
                      datetime(2026, 8, 26, 22, 11, 37, 999500)):
            self.assertEqual(iso_of(parse_stamp(value)), "2026-08-26T22:11:38")
        for value in (None, "nan", "  ", "invalid", float("nan"), float("inf")):
            self.assertIsNone(parse_stamp(value))

    def test_cutoff(self):
        self.assertEqual(self.calendar.cutoff_rule(parse_stamp("02/09/2026 14:59:59")), "2026-09-02")
        self.assertEqual(self.calendar.cutoff_rule(parse_stamp("02/09/2026 15:00:00")), "2026-09-03")
        self.assertEqual(self.calendar.cutoff_rule(parse_stamp("04/09/2026 16:30:00")), "2026-09-07")

    def test_closed_days(self):
        stamp = parse_stamp("05/09/2026 18:00:00")
        self.assertEqual(self.calendar.clock_start(stamp), {"day": "2026-09-07", "beforeCutoff": True})
        self.assertEqual(self.calendar.cutoff_rule(stamp), "2026-09-07")
        self.assertEqual(self.calendar.next_day(stamp), "2026-09-08")
        self.assertEqual(self.calendar.same_day(parse_stamp("17/03/2026 09:00:00")), "2026-03-18")
        self.assertEqual(self.calendar.next_day(parse_stamp("24/12/2025 10:00:00")), "2025-12-29")

    def test_business_days(self):
        self.assertEqual(self.calendar.business_days_between("2026-09-04", "2026-09-07"), 1)
        self.assertEqual(self.calendar.business_days_between("2026-09-07", "2026-09-07"), 0)
        self.assertEqual(self.calendar.business_days_between("2026-09-07", "2026-09-04"), 0)

    def test_48_hours(self):
        start = parse_stamp("01/09/2026 10:00:00")
        self.assertLess(hours_between(start, parse_stamp("03/09/2026 09:59:30")), 48)
        self.assertEqual(hours_between(start, parse_stamp("03/09/2026 10:00:00")), 48)

    def test_outcomes(self):
        self.assertEqual(judge(None, "2026-09-23", "2026-09-24"), "OPEN - PAST DEADLINE")
        self.assertEqual(judge(None, "2026-09-24", "2026-09-24"), "OPEN - NOT YET DUE")
        self.assertEqual(judge("2026-09-24", "2026-09-24", "2026-09-30"), "MET")
        self.assertEqual(judge("2026-09-25", "2026-09-24", "2026-09-30"), "MISSED")
        self.assertEqual(norm("  Ul   Workflow  "), "ul workflow")


if __name__ == "__main__":
    unittest.main()
