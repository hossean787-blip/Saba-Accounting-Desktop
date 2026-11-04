import csv
from datetime import date
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from saba_accounting.storage import AccountingStore, AccountingError
from saba_accounting.jalali import parse_jalali, display_jalali, jalali_to_gregorian, gregorian_to_jalali, rial_number

class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=AccountingStore(self.root/'test.sqlite3')
        self.c1=self.store.create_company('آفاق')
        self.c2=self.store.create_company('بهار')
        self.fy=self.store.create_fiscal_year(self.c1,'1405','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
        self.fy2=self.store.create_fiscal_year(self.c2,'1405','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
        self.cash=self.account_tree(self.c1,'1','11','1101','110101','صندوق')
        self.capital=self.account_tree(self.c1,'3','31','3101','310101','سرمایه')
        self.other=self.account_tree(self.c2,'1','11','1101','110101','صندوق شرکت ب')

    def tearDown(self):
        self.tmp.cleanup()

    def account_tree(self,c,*args):
        g,k,m,d,title=args
        p=None
        for level,code in enumerate((g,k,m,d),1):
            p=self.store.create_account(c,code, title if level==4 else 'گروه '+code,level, parent_id=p,is_postable=level==4)
        return p

    def balanced(self,amount=1000):
        return [{'account_id':self.cash,'debit':amount,'credit':0},
                {'account_id':self.capital,'debit':0,'credit':amount}]

    def new(self,lines=None,company=None,year=None,day='۱۴۰۵/۰۲/۰۱'):
        return self.store.new_draft(company or self.c1,year or self.fy,day,'ورود اولیه',lines if lines is not None else self.balanced())

    def test_01_create_companies(self):
        self.assertEqual(len(self.store.companies()),2)

    def test_02_year_dates(self):
        years=self.store.fiscal_years(self.c1)
        self.assertEqual(years[0]['start_date'],'2026-03-21')

    def test_03_block_overlapping_year(self):
        with self.assertRaises(AccountingError):self.store.create_fiscal_year(self.c1,'1405b','1405/02/01','1405/12/01')

    def test_fiscal_year_rejects_partial_overlaps(self):
        for code, start, end in (
            ('cross_begin', '1404/12/20', '1405/01/05'),
            ('cross_end', '1405/12/20', '1406/01/05'),
            ('contains', '1404/12/20', '1406/01/05'),
        ):
            with self.subTest(code=code), self.assertRaises(AccountingError):
                self.store.create_fiscal_year(self.c1, code, start, end)

    def test_fiscal_year_sql_guard_blocks_insert_and_update(self):
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('INSERT INTO fiscal_years(company_id,code,start_date,end_date) VALUES (?,?,?,?)',
                             (self.c1, 'raw', '2026-03-20', '2026-03-22'))
        with self.store._write() as conn:
            cur=conn.execute('INSERT INTO fiscal_years(company_id,code,start_date,end_date) VALUES (?,?,?,?)',
                             (self.c1, 'next', '2027-03-21', '2028-03-19'))
            following=cur.lastrowid
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE fiscal_years SET start_date=? WHERE id=?',
                             ('2027-03-19', following))
        self.assertEqual(len(self.store.fiscal_years(self.c2)), 1)

    def test_04_year_is_company_scoped(self):
        with self.assertRaises(AccountingError):self.new(company=self.c2,year=self.fy)

    def test_05_account_parent_required(self):
        with self.assertRaises(AccountingError):self.store.create_account(self.c1,'100','بدون والد',3)

    def test_06_cross_company_account(self):
        with self.assertRaises(AccountingError):self.new([{'account_id':self.other,'debit':100,'credit':0},self.balanced()[1]])

    def test_07_reject_both_sides(self):
        with self.assertRaises(AccountingError):self.new([{'account_id':self.cash,'debit':100,'credit':1},self.balanced()[1]])

    def test_08_reject_negative(self):
        with self.assertRaises(AccountingError):self.new([{'account_id':self.cash,'debit':-1,'credit':0},self.balanced()[1]])

    def test_09_reject_too_large(self):
        with self.assertRaises(AccountingError):self.new([{'account_id':self.cash,'debit':9_000_000_000_000_001,'credit':0},self.balanced()[1]])

    def test_10_unbalanced_cannot_post(self):
        entry=self.new([{'account_id':self.cash,'debit':100,'credit':0},{'account_id':self.capital,'debit':0,'credit':95}])
        with self.assertRaises(AccountingError):self.store.post(self.c1,entry)
        self.assertEqual(self.store.journal(self.c1,entry)['status'],'draft')

    def test_11_balanced_posts(self):
        entry=self.new();self.store.post(self.c1,entry)
        self.assertEqual(self.store.journal(self.c1,entry)['status'],'posted')

    def test_12_post_twice_fails(self):
        entry=self.new();self.store.post(self.c1,entry)
        with self.assertRaises(AccountingError):self.store.post(self.c1,entry)

    def test_13_posted_cannot_edit(self):
        entry=self.new();self.store.post(self.c1,entry)
        with self.assertRaises(AccountingError):self.store.replace_draft(self.c1,entry,'1405/02/01','edit',self.balanced())

    def test_14_cross_company_cannot_read(self):
        entry=self.new()
        with self.assertRaises(AccountingError):self.store.journal(self.c2,entry)

    def test_15_trial_excludes_drafts(self):
        posted=self.new();self.store.post(self.c1,posted)
        self.new(self.balanced(600))
        trial=self.store.trial_balance(self.c1,self.fy)
        self.assertEqual(sum(x['debit'] for x in trial),1000)
        self.assertEqual(sum(x['credit'] for x in trial),1000)

    def test_16_reverse_offsets(self):
        posted=self.new();self.store.post(self.c1,posted)
        reverse=self.store.reverse(self.c1,posted,'1405/02/03')
        self.assertEqual(self.store.journal(self.c1,reverse)['status'],'posted')
        self.assertTrue(all(r['debit']==r['credit'] for r in self.store.trial_balance(self.c1,self.fy) if r['debit'] or r['credit']))

    def test_17_no_double_reverse(self):
        posted=self.new();self.store.post(self.c1,posted)
        self.store.reverse(self.c1,posted,'1405/02/03')
        with self.assertRaises(AccountingError):self.store.reverse(self.c1,posted,'1405/02/04')

    def test_18_export_csv_bom(self):
        entry=self.new();self.store.post(self.c1,entry)
        path=self.root/'trial.csv';self.store.export_trial_csv(self.c1,self.fy,path)
        raw=path.read_bytes();self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        with open(path,encoding='utf-8-sig') as f:
            rows=list(csv.reader(f))
        self.assertEqual(len(rows),3)

    def test_19_backup_restore_readable(self):
        entry=self.new();self.store.post(self.c1,entry)
        target=self.root/'backup.sqlite3';self.store.backup(target)
        with closing(sqlite3.connect(str(target))) as check:
            self.assertEqual(check.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0],1)
            self.assertEqual(check.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_20_backup_same_file_rejected(self):
        with self.assertRaises(AccountingError):self.store.backup(self.root/'test.sqlite3')

    def test_21_jalali_known_dates(self):
        self.assertEqual(parse_jalali('۱۴۰۵/۰۱/۰۱'),date(2026,3,21))
        self.assertEqual(parse_jalali('1403/01/01'),date(2024,3,20))
        self.assertEqual(display_jalali(date(2026,10,27)),'1405/08/05')

    def test_22_reject_invalid_jalali(self):
        for bad in ('1405/07/31','1405/12/30','۱۴۰۵/۱۳/۰۱','hello'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):parse_jalali(bad)

    def test_23_parse_persian_rial(self):
        self.assertEqual(rial_number('۱٬۲۰۰٬۰۰۰'),1200000)
        with self.assertRaises(ValueError):rial_number('1.50')

    def test_24_closed_year_rejects_new(self):
        with self.store._write() as conn:conn.execute('UPDATE fiscal_years SET is_closed=1 WHERE id=?',(self.fy,))
        with self.assertRaises(AccountingError):self.new()

    def test_25_direct_sql_cannot_change_posted(self):
        entry=self.new();self.store.post(self.c1,entry)
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:conn.execute('DELETE FROM journal_lines WHERE entry_id=?',(entry,))

    def test_26_failed_draft_atomic(self):
        before=len(self.store.journals(self.c1,self.fy))
        with self.assertRaises(AccountingError):self.new([{'account_id':self.cash,'debit':100,'credit':0},{'account_id':self.other,'credit':100,'debit':0}])
        self.assertEqual(len(self.store.journals(self.c1,self.fy)),before)

    def test_27_change_draft(self):
        entry=self.new();self.store.replace_draft(self.c1,entry,'1405/02/04','اصلاح',self.balanced(300))
        d=self.store.journal(self.c1,entry)
        self.assertEqual(d['lines'][0]['debit_rial'],300)
        self.assertEqual(d['description'],'اصلاح')

    def test_28_year_with_journals_dates_immutable(self):
        self.new()
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:conn.execute("UPDATE fiscal_years SET end_date='2027-03-21' WHERE id=?",(self.fy,))

    def test_29_audit_log(self):
        entry=self.new();self.store.post(self.c1,entry)
        with closing(self.store._connection()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events WHERE company_id=? AND target_type='journal'",(self.c1,)).fetchone()[0],2)

    def test_account_hierarchy_sql_rejects_orphan_nonroot(self):
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute("INSERT INTO accounts(company_id,code,title,level,nature) VALUES (?, '999', 'Orphan', 3, 'debit')",(self.c1,))

    def test_account_hierarchy_sql_rejects_postable_parent(self):
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute("INSERT INTO accounts(company_id,code,title,level,nature,parent_id) VALUES (?, '1101019','Child', 4, 'debit', ?)",(self.c1,self.cash))

    def test_account_hierarchy_sql_rejects_invalid_reparent(self):
        root = next(a for a in self.store.accounts(self.c1) if a['code']=='1')
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE accounts SET parent_id=? WHERE id=?',(root['id'],self.cash))
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE accounts SET level=4,is_postable=1 WHERE id=?',(root['id'],))

    def test_account_hierarchy_sql_rejects_reparent_of_used_account(self):
        entry=self.new(); self.store.post(self.c1,entry)
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE accounts SET level=3 WHERE id=?',(self.cash,))
        self.assertEqual(self.store.journal(self.c1,entry)['status'],'posted')

    def test_line_update_rejects_nonpostable_account(self):
        entry=self.new()
        parent=next(a['id'] for a in self.store.accounts(self.c1) if a['code']=='1101')
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE journal_lines SET account_id=? WHERE entry_id=? AND row_no=1',(parent,entry))
        self.assertEqual(self.store.journal(self.c1,entry)['lines'][0]['account_id'],self.cash)

    def test_line_update_rejects_inactive_account(self):
        entry=self.new()
        with self.store._write() as conn:
            conn.execute('UPDATE accounts SET is_active=0 WHERE id=?',(self.cash,))
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE journal_lines SET account_id=? WHERE entry_id=? AND row_no=2',(self.cash,entry))

    def test_post_rejects_deactivated_account(self):
        entry=self.new()
        with self.store._write() as conn:
            conn.execute('UPDATE accounts SET is_active=0 WHERE id=?',(self.cash,))
        with self.assertRaises(AccountingError): self.store.post(self.c1,entry)
        self.assertEqual(self.store.journal(self.c1,entry)['status'],'draft')

    def test_direct_sql_rejects_oversized_line(self):
        entry=self.new()
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE journal_lines SET debit_rial=? WHERE entry_id=? AND row_no=1',(9000000000000001,entry))
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('INSERT INTO journal_lines(entry_id,account_id,row_no,debit_rial) VALUES (?,?,?,?)',
                             (entry,self.cash,3,9000000000000001))

    def test_30_roundtrip_calendar_samples(self):
        for item in (date(2000,1,1),date(2020,2,29),date(2026,12,31),date(2030,3,20)):
            self.assertEqual(jalali_to_gregorian(*gregorian_to_jalali(item)),item)

if __name__=='__main__':unittest.main(verbosity=2)
