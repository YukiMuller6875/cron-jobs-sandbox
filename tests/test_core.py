import unittest
from datetime import datetime

from cron_jobs_sandbox import parse_cron, next_fire_times, CronExpression


class TestParsing(unittest.TestCase):
    def test_basic_five_fields(self):
        expr = parse_cron("0 9 * * *")
        self.assertIsInstance(expr, CronExpression)
        self.assertEqual(expr.raw, "0 9 * * *")

    def test_step_with_wildcard(self):
        expr = parse_cron("*/15 * * * *")
        self.assertEqual(expr.minute.values, (0, 15, 30, 45))

    def test_step_with_range(self):
        expr = parse_cron("10-20/5 * * * *")
        self.assertEqual(expr.minute.values, (10, 15, 20))

    def test_step_with_single_value(self):
        expr = parse_cron("5/15 * * * *")
        self.assertEqual(expr.minute.values, (5, 20, 35, 50))

    def test_comma_list(self):
        expr = parse_cron("1,5,10 * * * *")
        self.assertEqual(expr.minute.values, (1, 5, 10))

    def test_month_names(self):
        expr = parse_cron("0 0 1 JAN,JUL *")
        self.assertEqual(expr.month.values, (1, 7))

    def test_weekday_names_case_insensitive(self):
        expr = parse_cron("0 0 * * mon")
        self.assertEqual(expr.weekday.values, (0,))

    def test_invalid_field_count(self):
        with self.assertRaises(ValueError):
            parse_cron("0 9 * *")

    def test_out_of_range_value(self):
        with self.assertRaises(ValueError):
            parse_cron("60 * * * *")

    def test_zero_step_rejected(self):
        with self.assertRaises(ValueError):
            parse_cron("*/0 * * * *")

    def test_empty_field_rejected(self):
        with self.assertRaises(ValueError):
            parse_cron("0 9 *  *")

    def test_invalid_month_name_rejected(self):
        with self.assertRaises(ValueError):
            parse_cron("0 0 1 XYZ *")

    def test_feb_30_impossible_rejected(self):
        with self.assertRaises(ValueError):
            parse_cron("0 0 30 2 *")

    def test_dom_wildcard_allows_31(self):
        # 31 is valid in some months, so wildcard should parse fine.
        expr = parse_cron("0 0 31 * *")
        self.assertEqual(expr.day_of_month.values, (31,))


class TestNextFireTimes(unittest.TestCase):
    def test_wildcard_minute(self):
        expr = parse_cron("* * * * *")
        start = datetime(2024, 1, 1, 12, 0, 0)
        times = next_fire_times(expr, start, 3)
        self.assertEqual(times, [
            datetime(2024, 1, 1, 12, 1, 0),
            datetime(2024, 1, 1, 12, 2, 0),
            datetime(2024, 1, 1, 12, 3, 0),
        ])

    def test_daily_at_nine(self):
        expr = parse_cron("0 9 * * *")
        start = datetime(2024, 1, 1, 8, 59, 0)
        times = next_fire_times(expr, start, 2)
        self.assertEqual(times, [
            datetime(2024, 1, 1, 9, 0, 0),
            datetime(2024, 1, 2, 9, 0, 0),
        ])

    def test_every_15_minutes(self):
        expr = parse_cron("*/15 * * * *")
        start = datetime(2024, 1, 1, 12, 7, 0)
        times = next_fire_times(expr, start, 2)
        self.assertEqual(times, [
            datetime(2024, 1, 1, 12, 15, 0),
            datetime(2024, 1, 1, 12, 30, 0),
        ])

    def test_month_boundary(self):
        expr = parse_cron("0 0 1 * *")
        start = datetime(2024, 1, 31, 23, 59, 0)
        times = next_fire_times(expr, start, 1)
        self.assertEqual(times, [datetime(2024, 2, 1, 0, 0, 0)])

    def test_weekday_named(self):
        # Every Monday at 00:00. 2024-01-01 is a Monday.
        expr = parse_cron("0 0 * * MON")
        start = datetime(2024, 1, 1, 0, 0, 0)
        times = next_fire_times(expr, start, 2)
        self.assertEqual(times, [
            datetime(2024, 1, 8, 0, 0, 0),
            datetime(2024, 1, 15, 0, 0, 0),
        ])

    def test_dom_and_dow_or_logic(self):
        # Fires on the 1st OR on Sundays. 2024-01-01 (Mon) 00:00 is the 1st.
        expr = parse_cron("0 0 1 * SUN")
        start = datetime(2024, 1, 1, 0, 0, 0)
        times = next_fire_times(expr, start, 3)
        self.assertEqual(times, [
            datetime(2024, 1, 7, 0, 0, 0),   # Sunday
            datetime(2024, 1, 14, 0, 0, 0),  # Sunday
            datetime(2024, 1, 21, 0, 0, 0),   # Sunday
        ])

    def test_start_seconds_stripped(self):
        expr = parse_cron("0 0 * * *")
        start = datetime(2024, 1, 1, 0, 0, 30)
        times = next_fire_times(expr, start, 1)
        self.assertEqual(times, [datetime(2024, 1, 2, 0, 0, 0)])

    def test_count_zero(self):
        expr = parse_cron("* * * * *")
        self.assertEqual(next_fire_times(expr, datetime(2024, 1, 1), 0), [])


if __name__ == "__main__":
    unittest.main()
