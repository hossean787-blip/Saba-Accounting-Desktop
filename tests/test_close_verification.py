"""Independent tests for fiscal-year closing journal verification."""
import tempfile
import unittest
from pathlib import Path
from saba_accounting.finance import FinanceStore, AccountingError


class YearEndVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = FinanceStore(Path(self.tmp.name) / 'year_end.sqlite3')
        self.company = self.store.create_company('شرکت آزمون')
        self.y1 = self.store.create_fiscal_year(self.company, '1405', '1405/01/01', '1405/12/29')
        self.y2 = self.store.create_fiscal_year(self.company, '1406', '1406/01/01', '1406/12/29')
        self.asset = self.account('1', 'asset')
        self.equity = self.account('3', 'equity')
        self.revenue = self.account('4', 'revenue')
        self.retained = self.account('39', 'equity')

    def account(self, code, category):
        roots = [a for a in self.store.accounts(self.company)
                 if a['level'] == 1 and a['account_class'] == category]
        root = roots[0]['id'] if roots else self.store.create_account(
            self.company, code, 'گروه ' + category, 1, account_class=category)
        prefix = code if not roots else code + '0'
        gl = self.store.create_account(self.company, prefix + '1', 'کل', 2, parent_id=root)
        sub = self.store.create_account(self.company, prefix + '11', 'معین', 3, parent_id=gl)
        return self.store.create_account(self.company, prefix + '111', 'تفصیلی', 4,
                                         parent_id=sub, is_postable=True)

    def seed(self):
        for debit, credit, value in [(self.asset, self.equity, 1000),
                                     (self.asset, self.revenue, 250)]:
            doc = self.store.new_draft(self.company, self.y1, '1405/02/01', 'سند آزمون', [
                {'account_id': debit, 'debit': value},
                {'account_id': credit, 'credit': value}])
            self.store.post(self.company, doc)

    def test_preview_exposes_balanced_three_journals_without_writes(self):
        self.seed()
        before = len(self.store._read_all('SELECT * FROM journal_entries WHERE company_id=?',(self.company,)))
        report = self.store.closing_preview_details(self.company,self.y1,self.y2,self.retained)
        self.assertEqual([p['kind'] for p in report['journals']],
                         ['temporary_lines','closing_lines','opening_lines'])
        self.assertEqual(report['profit'], 250)
        for part in report['journals']:
            self.assertEqual(part['total_debit'],part['total_credit'])
            for row in part['rows']:
                self.assertTrue(row['account_code'])
                self.assertTrue(row['account_title'])
        after = len(self.store._read_all('SELECT * FROM journal_entries WHERE company_id=?',(self.company,)))
        self.assertEqual(before,after)
        self.assertFalse(self.store.fiscal_years(self.company)[0]['is_closed'])

    def test_preview_rejects_cross_company_year(self):
        self.seed()
        other = self.store.create_company('دیگر')
        with self.assertRaises(AccountingError):
            self.store.closing_preview_details(other,self.y1,self.y2,self.retained)

    def test_preview_matches_actual_closing_dimensions(self):
        self.seed()
        preview=self.store.closing_preview_details(self.company,self.y1,self.y2,self.retained)
        self.store.close_fiscal_year(self.company,self.y1,self.y2,self.retained)
        result=self.store.verify_fiscal_closure(self.company,self.y1)
        self.assertEqual(preview['profit'],result['profit_rial'])
        bykind={p['kind']:p for p in preview['journals']}
        for key in ('closing_lines','opening_lines'):
            self.assertEqual(bykind[key]['total_debit'],bykind[key]['total_credit'])
        self.assertEqual(bykind['closing_lines']['total_debit'],bykind['opening_lines']['total_credit'])

    def test_verify_close_and_opening_dimensions(self):
        self.seed()
        ids = self.store.close_fiscal_year(self.company, self.y1, self.y2, self.retained)
        result = self.store.verify_fiscal_closure(self.company, self.y1)
        self.assertTrue(result['ok'])
        self.assertEqual(result['opening_id'], ids['opening_id'])
        self.assertEqual(result['closing_id'], ids['close_id'])
        self.assertEqual(result['profit_rial'], 250)
        self.assertGreaterEqual(result['dimensions_checked'], 2)

    def test_reject_unclosed_year(self):
        with self.assertRaises(AccountingError):
            self.store.verify_fiscal_closure(self.company, self.y1)

    def test_verify_is_company_scoped(self):
        self.seed()
        self.store.close_fiscal_year(self.company, self.y1, self.y2, self.retained)
        outsider = self.store.create_company('شرکت دیگر')
        with self.assertRaises(AccountingError):
            self.store.verify_fiscal_closure(outsider, self.y1)

    def test_posted_opening_is_immutable(self):
        self.seed()
        ids = self.store.close_fiscal_year(self.company, self.y1, self.y2, self.retained)
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                row = conn.execute('SELECT id FROM journal_lines WHERE entry_id=? AND debit_rial>0 LIMIT 1',
                                   (ids['opening_id'],)).fetchone()
                conn.execute('UPDATE journal_lines SET debit_rial=debit_rial+1 WHERE id=?', (row['id'],))
        self.assertTrue(self.store.verify_fiscal_closure(self.company, self.y1)['ok'])


if __name__ == '__main__':
    unittest.main()
