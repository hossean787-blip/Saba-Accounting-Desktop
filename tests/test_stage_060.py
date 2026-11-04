"""Stage 0.6: print preview, integration reconciliation, verified local backups."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from saba_accounting.finance import FinanceStore, AccountingError


class Stage060Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.store = FinanceStore(self.directory / 'test.sqlite3')
        self.company = self.store.create_company('شرکت <نمونه>')
        self.year = self.store.create_fiscal_year(self.company, '1405', '1405/01/01', '1405/12/29')
        self.next_year = self.store.create_fiscal_year(self.company, '1406', '1406/01/01', '1406/12/29')
        self.asset = self._account('1', 'asset')
        self.equity = self._account('3', 'equity')
        self.revenue = self._account('4', 'revenue')

    def _account(self, code, kind):
        root = self.store.create_account(self.company, code, 'گروه ' + kind, 1, account_class=kind)
        gl = self.store.create_account(self.company, code+'01', 'کل', 2, parent_id=root)
        sub = self.store.create_account(self.company, code+'011', 'معین', 3, parent_id=gl)
        return self.store.create_account(self.company, code+'0111', 'تفصیلی', 4, parent_id=sub, is_postable=True)

    def seed(self):
        entry = self.store.new_draft(self.company, self.year, '1405/02/01', 'نمونه', [
            {'account_id': self.asset, 'debit': 1500},
            {'account_id': self.equity, 'credit': 1000},
            {'account_id': self.revenue, 'credit': 500}])
        self.store.post(self.company, entry)

    def test_closing_preview_html_escaped_and_read_only(self):
        self.seed()
        before = len(self.store.journals(self.company, self.year))
        target = self.directory / 'preview.html'
        self.store.export_closing_preview_html(self.company,self.year,self.next_year,self.equity,target)
        html = target.read_text(encoding='utf-8')
        self.assertIn('پیش‌نمایش اسناد پایان سال',html)
        self.assertIn('سند اختتامیه',html)
        self.assertIn('سند افتتاحیه',html)
        self.assertNotIn('<script>',html)
        self.assertEqual(before,len(self.store.journals(self.company,self.year)))
        self.assertFalse(self.store.closure_info(self.company,self.year))

    def test_integration_report_balanced_and_company_scoped(self):
        self.seed()
        report=self.store.full_integrity_report(self.company,self.year)
        self.assertTrue(report['ok'],report)
        self.assertTrue(report['sources'])
        self.assertEqual(sum(x['debit_rial'] for x in report['sources']),1500)
        other=self.store.create_company('دیگر')
        other_year=self.store.create_fiscal_year(other,'1405','1405/01/01','1405/12/29')
        report2=self.store.full_integrity_report(other,other_year)
        self.assertTrue(report2['ok'])
        self.assertFalse(report2['sources'])

    def test_verified_backup_receipt_and_restore_readability(self):
        self.seed()
        dst=self.directory/'backup.sqlite3'
        result=self.store.verified_backup(dst, self.company)
        self.assertEqual(result['sha256'],hashlib.sha256(dst.read_bytes()).hexdigest())
        self.assertTrue(self.store.verify_backup_receipt(dst))
        with closing(sqlite3.connect(dst)) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0],1)
        with self.assertRaises(AccountingError):self.store.verified_backup(dst,self.company)
        with dst.open('ab') as file:file.write(b'change')
        self.assertFalse(self.store.verify_backup_receipt(dst))

    def test_closing_preview_rejects_foreign_company(self):
        outsider=self.store.create_company('نامرتبط')
        with self.assertRaises(AccountingError):
            self.store.export_closing_preview_html(outsider,self.year,self.next_year,self.equity,
                                                   self.directory/'forbidden.html')
        self.assertFalse((self.directory/'forbidden.html').exists())

if __name__=='__main__':unittest.main()
