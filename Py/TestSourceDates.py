import unittest
from SourceDates import source_date

class SourceDateTests(unittest.TestCase):
    def test_year_and_month_preserve_original_precision(self):
        year,info=source_date('1999');self.assertEqual(year.isoformat(),'1999-01-01T00:00:00');self.assertEqual(info,{'raw':'1999','precision':'Year'})
        month,info=source_date('2020-07');self.assertEqual(month.day,1);self.assertEqual(info['precision'],'Month')

    def test_full_dates_keep_source_calendar_day(self):
        value,info=source_date('2020-07-08T22:55:00-06:00');self.assertEqual(value.isoformat(),'2020-07-08T00:00:00');self.assertIsNone(info)

    def test_unparseable_values_remain_available_for_review(self):
        value,info=source_date('1999/2000');self.assertIsNone(value);self.assertEqual(info['raw'],'1999/2000');self.assertEqual(info['precision'],'Unparsed')

if __name__=='__main__':unittest.main()
