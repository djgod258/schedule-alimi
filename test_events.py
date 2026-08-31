import unittest
from datetime import date

import events as ev
import schedule_rules as sr


class StockoutChannelNoticeTest(unittest.TestCase):
    def test_weekday_uses_the_fifteenth(self):
        self.assertEqual(ev.stockout_channel_notice_target(2026, 9), date(2026, 9, 15))

    def test_weekend_moves_back_exactly_one_calendar_day(self):
        self.assertEqual(ev.stockout_channel_notice_target(2026, 11), date(2026, 11, 14))

    def test_holiday_moves_back_exactly_one_calendar_day(self):
        self.assertEqual(ev.stockout_channel_notice_target(2028, 8), date(2028, 8, 14))

    def test_reminder_is_sent_at_0830_with_requested_text(self):
        reminder = sr._expand_event("stockout_channel_notice", 2026, 9)[0]
        self.assertEqual(reminder.fire_at, sr._dt(date(2026, 9, 15), 8, 30))
        self.assertEqual(reminder.label, "품절현황 채널공지")
        self.assertIn("품절현황 채널공지", reminder.message)


if __name__ == "__main__":
    unittest.main()
