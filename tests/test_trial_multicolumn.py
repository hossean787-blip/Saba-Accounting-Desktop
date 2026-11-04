"""Independent regression coverage for multi-column trial reports."""
import csv
from pathlib import Path
import tempfile
import unittest
from saba_accounting.storage import AccountingError, AccountingStore


class MultiColumnTrialTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.store = AccountingStore(self.folder / 'data.db')
        self.company = self.store.create_company('شرکت نمونه')
        self.other = self.store.create_company('شرکت دیگر')
        self.year = self.store.create_fiscal_year(self.company, '1405', '1405/01/01', '1405/12/29')
        self.other_year = self.store.create_fiscal_year(self.other, '1405', '1405/01/01', '1405/12/29')

        def leaf(prefix, title):
            group = self.store.create_account(self.company, prefix, title, 1)
            whole = self.store.create_account(self.company, prefix + '1', 'کل ' + title, 2, parent_id=group)
            detail = self.store.create_account(self.company, prefix + '11', 'معین ' + title, 3, parent_id=whole)
            postable = self.store.create_account(self.company, prefix + '111', 'تفصیلی ' + title,
                                                 4, parent_id=detail, is_postable=True)
            return (group, whole, detail, postable)
        self.cash = leaf('1', 'صندوق')
        self.equity = leaf('2', 'سرمایه')

    def post(self, day, amount):
        ident = self.store.new_draft(self.company, self.year, day, 'ثبت', [
            {'account_id': self.cash[3], 'debit': amount, 'credit': 0},
            {'account_id': self.equity[3], 'debit': 0, 'credit': amount}])
        self.store.post(self.company, ident)

    def test_139_all_account_levels_aggregate(self):
        self.post('1405/02/01', 120)
        for level in (1, 2, 3, 4):
            report = self.store.trial_balance_detailed(self.company, self.year, level=level)
            self.assertEqual(len(report['rows']), 2)
            self.assertEqual(sum(row['period_debit'] for row in report['rows']), 120)
            self.assertEqual(sum(row['period_credit'] for row in report['rows']), 120)

    def test_140_date_ranges_opening_movement_and_closing(self):
        self.post('1405/02/01', 100)
        self.post('1405/03/01', 75)
        report = self.store.trial_balance_detailed(self.company, self.year,
                    level=1, columns=8, start_jalali='1405/03/01', end_jalali='1405/03/31')
        cash = next(row for row in report['rows'] if row['code'] == '1')
        self.assertEqual((cash['opening_debit'], cash['period_debit'], cash['cumulative_debit'],
                          cash['closing_debit']), (100, 75, 175, 175))
        self.assertEqual(cash['period_credit'], 0)

    def test_141_drafts_excluded_and_companies_isolated(self):
        self.post('1405/02/01', 100)
        self.store.new_draft(self.company, self.year, '1405/02/02', 'پیش نویس', [
            {'account_id': self.cash[3], 'debit': 9000, 'credit': 0},
            {'account_id': self.equity[3], 'debit': 0, 'credit': 9000}])
        result = self.store.trial_balance_detailed(self.company, self.year)
        self.assertEqual(sum(row['period_debit'] for row in result['rows']), 100)
        self.assertEqual(self.store.trial_balance_detailed(self.other, self.other_year)['rows'], [])
        with self.assertRaises(AccountingError):
            self.store.trial_balance_detailed(self.other, self.year)

    def test_142_csv_and_html_escaping(self):
        self.post('1405/02/01', 150)
        csv_path = self.folder / 'taraz.csv'
        html_path = self.folder / 'taraz.html'
        self.store.export_trial_detailed_csv(self.company, self.year, csv_path, 1, 8)
        self.assertTrue(csv_path.read_bytes().startswith(b'\xef\xbb\xbf'))
        with csv_path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        self.assertEqual(len(rows[0]), 10)
        self.assertEqual(rows[-1][0], 'جمع')
        self.assertEqual(int(rows[-1][4]), 150)
        self.store.export_trial_detailed_html(self.company, self.year, html_path, 1, 8)
        page = html_path.read_text(encoding='utf-8')
        self.assertIn('dir="rtl"', page)
        self.assertIn('شرکت نمونه', page)
        self.assertIn('150', page)

    def test_143_invalid_ranges_and_columns_rejected(self):
        for kwargs in (dict(level=5), dict(columns=3),
                       dict(start_jalali='1404/12/01'),
                       dict(start_jalali='1405/12/01', end_jalali='1405/01/01')):
            with self.subTest(kwargs=kwargs), self.assertRaises(AccountingError):
                self.store.trial_balance_detailed(self.company, self.year, **kwargs)


if __name__ == '__main__':
    unittest.main()
