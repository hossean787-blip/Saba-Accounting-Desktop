"""Real accounting assertions for v0.2. No Sepidar data is used."""
import csv
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from saba_accounting.storage import AccountingStore, AccountingError

class StatementAndLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.store=AccountingStore(self.folder/'main.sqlite3')
        self.cid=self.store.create_company('آزمون')
        self.other=self.store.create_company('شرکت دوم')
        self.fy=self.store.create_fiscal_year(self.cid,'1405','1405/01/01','1405/12/29')
        self.fy_other=self.store.create_fiscal_year(self.other,'1405','1405/01/01','1405/12/29')
        def acct(code,cl,nature):
            root=self.store.create_account(self.cid,code,cl,1,nature=nature,account_class=cl)
            sec=self.store.create_account(self.cid,code+'1','کل',2,parent_id=root)
            th=self.store.create_account(self.cid,code+'11','معین',3,parent_id=sec)
            leaf=self.store.create_account(self.cid,code+'111','تفصیلی',4,parent_id=th,is_postable=True)
            return root,sec,th,leaf
        self.asset=acct('1','asset','debit')
        self.equity=acct('3','equity','credit')
        self.revenue=acct('4','revenue','credit')
        self.cost=acct('5','cost','debit')
        self.expense=acct('6','expense','debit')
        self.liability=acct('2','liability','credit')
        def doc(day, debit, credit, amount, desc='ثبت'):
            entry=self.store.new_draft(self.cid,self.fy,day,desc,[
                {'account_id':debit,'debit':amount,'credit':0},
                {'account_id':credit,'debit':0,'credit':amount}])
            self.store.post(self.cid,entry)
            return entry
        self.doc=doc
        self.first=self.doc('1405/02/02',self.asset[3],self.equity[3],1000,'سرمایه')
        self.sale=self.doc('1405/02/03',self.asset[3],self.revenue[3],900,'فروش')
        self.material=self.doc('1405/02/04',self.cost[3],self.asset[3],400,'بها')
        self.operational=self.doc('1405/02/05',self.expense[3],self.asset[3],200,'هزینه')

    def test_31_income_statement_amounts(self):
        r=self.store.statements(self.cid,self.fy)
        self.assertEqual(r['revenue']['total'],900)
        self.assertEqual(r['costs']['total'],400)
        self.assertEqual(r['expenses']['total'],200)
        self.assertEqual(r['net_profit'],300)

    def test_32_balance_sheet_equation(self):
        r=self.store.statements(self.cid,self.fy)
        self.assertEqual((r['assets']['total'],r['equity']['total']), (1300,1000))
        self.assertEqual(r['balance_total'],1300)
        self.assertEqual(r['balance_difference'],0)

    def test_33_ledger_parent_aggregate(self):
        r=self.store.ledger(self.cid,self.fy,self.asset[0])
        self.assertEqual((r['debit'],r['credit'],r['closing']),(1900,600,1300))
        self.assertEqual(len(r['rows']),4)

    def test_34_ledger_midyear_opening(self):
        r=self.store.ledger(self.cid,self.fy,self.asset[2],'1405/02/04','1405/02/05')
        self.assertEqual((r['opening'],r['debit'],r['credit'],r['closing']),(1900,0,600,1300))
        self.assertEqual([x['balance'] for x in r['rows']],[1500,1300])

    def test_35_ledger_reject_wrong_company(self):
        with self.assertRaises(AccountingError):self.store.ledger(self.other,self.fy_other,self.asset[0])

    def test_36_statement_reject_wrong_company(self):
        with self.assertRaises(AccountingError):self.store.statements(self.other,self.fy)

    def test_37_unclassified_account_blocks_financial_statement(self):
        root=self.store.create_account(self.cid,'7','نامشخص',1)
        middle=self.store.create_account(self.cid,'71','کل',2,parent_id=root)
        major=self.store.create_account(self.cid,'711','معین',3,parent_id=middle)
        leaf=self.store.create_account(self.cid,'7111','تفصیلی',4,parent_id=major,is_postable=True)
        self.doc('1405/02/06',leaf,self.asset[3],75)
        with self.assertRaises(AccountingError):self.store.statements(self.cid,self.fy)
        self.store.set_root_class(self.cid,root,'expense')
        self.assertEqual(self.store.statements(self.cid,self.fy)['net_profit'],225)

    def test_38_forbid_reclassification(self):
        with self.assertRaises(AccountingError):self.store.set_root_class(self.cid,self.asset[0],'revenue')
        self.assertEqual(self.store.accounts(self.cid)[0]['account_class'],'asset')

    def test_39_ledger_csv_unicode_and_sums(self):
        path=self.folder/'daftar.csv'
        self.store.export_ledger_csv(self.cid,self.fy,self.asset[0],path)
        self.assertEqual(path.read_bytes()[:3],b'\xef\xbb\xbf')
        with open(path,encoding='utf-8-sig') as fp:rows=list(csv.reader(fp))
        self.assertEqual(len(rows),8)
        self.assertEqual(rows[-1][-2:],[str(1300),str(0)])

    def test_40_statements_csv_unicode(self):
        path=self.folder/'financial.csv'
        self.store.export_statements_csv(self.cid,self.fy,path)
        self.assertEqual(path.read_bytes()[:3],b'\xef\xbb\xbf')
        self.assertIn('سود (زیان) دوره,300',path.read_text(encoding='utf-8-sig'))

    def test_41_ledger_date_invalid(self):
        with self.assertRaises(AccountingError):self.store.ledger(self.cid,self.fy,self.asset[3],'1405/03/01','1405/02/01')
        with self.assertRaises(AccountingError):self.store.ledger(self.cid,self.fy,self.asset[3],'1404/12/01','1405/02/01')

    def test_42_draft_excluded_from_both(self):
        self.store.new_draft(self.cid,self.fy,'1405/02/06','پیش‌نویس',[
            {'account_id':self.asset[3],'debit':800,'credit':0},
            {'account_id':self.revenue[3],'debit':0,'credit':800}])
        self.assertEqual(self.store.statements(self.cid,self.fy)['net_profit'],300)
        self.assertEqual(self.store.ledger(self.cid,self.fy,self.asset[0])['closing'],1300)

    def test_43_reversal_cancel_income(self):
        self.store.reverse(self.cid,self.sale,'1405/02/10')
        self.assertEqual(self.store.statements(self.cid,self.fy)['net_profit'],-600)
        self.assertEqual(self.store.statements(self.cid,self.fy)['balance_difference'],0)

    def test_44_subaccount_ledger(self):
        self.assertEqual(self.store.ledger(self.cid,self.fy,self.asset[3])['closing'],1300)
        self.assertEqual(self.store.ledger(self.cid,self.fy,self.asset[1])['closing'],1300)

    def test_45_edit_draft_without_new_journal(self):
        doc=self.store.new_draft(self.cid,self.fy,'1405/02/06','پیش‌نویس',[
            {'account_id':self.asset[3],'debit':22,'credit':0},
            {'account_id':self.liability[3],'debit':0,'credit':22}])
        initial=len(self.store.journals(self.cid,self.fy))
        self.store.replace_draft(self.cid,doc,'1405/02/07','پیش‌نویس اصلاحی',[
            {'account_id':self.asset[3],'debit':55,'credit':0},
            {'account_id':self.liability[3],'debit':0,'credit':55}])
        self.assertEqual(len(self.store.journals(self.cid,self.fy)),initial)
        self.assertEqual(self.store.journal(self.cid,doc)['lines'][0]['debit_rial'],55)

    def test_46_failed_edit_rolls_back(self):
        doc=self.store.new_draft(self.cid,self.fy,'1405/02/06','پیش‌نویس',[
            {'account_id':self.asset[3],'debit':22,'credit':0},
            {'account_id':self.liability[3],'debit':0,'credit':22}])
        before=self.store.journal(self.cid,doc)
        with self.assertRaises(AccountingError):
            self.store.replace_draft(self.cid,doc,'1405/02/08','ویرایش خراب',[
                {'account_id':self.asset[3],'debit':30,'credit':0},
                {'account_id':self.asset[3],'debit':4,'credit':3}])
        self.assertEqual(self.store.journal(self.cid,doc)['lines'],before['lines'])

    def test_47_zero_entries_in_other_classes(self):
        self.assertEqual(self.store.statements(self.cid,self.fy)['liabilities']['total'],0)

    def test_48_restore_from_backup_after_reports(self):
        dest=self.folder/'backup.sqlite3'
        self.store.backup(dest)
        copy=AccountingStore(dest)
        self.assertEqual(copy.statements(self.cid,self.fy)['net_profit'],300)

    def test_49_no_direct_reclassification_of_nonroot(self):
        with self.assertRaises(AccountingError):self.store.set_root_class(self.cid,self.asset[1],'expense')

    def test_50_ledger_empty_account(self):
        self.assertEqual(self.store.ledger(self.cid,self.fy,self.liability[0])['rows'],[])
        self.assertEqual(self.store.ledger(self.cid,self.fy,self.liability[0])['closing'],0)

    def test_056_printed_ledger_date_filter_and_opening(self):
        output=self.folder/'ledger.html'
        report=self.store.export_ledger_html(self.cid,self.fy,self.asset[1],output,'1405/02/04','1405/02/05')
        html=output.read_text(encoding='utf-8')
        self.assertEqual((report['opening'],report['debit'],report['credit'],report['closing']), (1900,0,600,1300))
        self.assertIn('مانده ابتدای بازه',html)
        self.assertIn('1,900',html)
        self.assertIn('1,300',html)
        self.assertNotIn('سرمایه</td>',html)
        self.assertIn('1405/02/04',html)
        self.assertIn('دفتر کل',html)

    def test_057_printed_ledger_escapes_special_characters(self):
        self.doc('1405/02/08',self.asset[3],self.equity[3],3,'<script>alert("unsafe")</script>')
        output=self.folder/'safe.html'
        self.store.export_ledger_html(self.cid,self.fy,self.asset[2],output)
        content=output.read_text(encoding='utf-8')
        self.assertNotIn('<script>',content)
        self.assertIn('&lt;script&gt;',content)
        self.assertIn('دفتر معین',content)

    def test_058_printed_ledger_rejects_other_company_and_invalid_period(self):
        output=self.folder/'must-not-exist.html'
        with self.assertRaises(AccountingError):
            self.store.export_ledger_html(self.other,self.fy_other,self.asset[0],output)
        with self.assertRaises(AccountingError):
            self.store.export_ledger_html(self.cid,self.fy,self.asset[0],output,'1405/03/01','1405/02/01')
        self.assertFalse(output.exists())

    def test_059_printed_ledger_drafts_excluded_and_empty_account(self):
        self.store.new_draft(self.cid,self.fy,'1405/02/09','پیش نویس نباید در گزارش بیاید',[
            {'account_id':self.asset[3],'debit':40,'credit':0},
            {'account_id':self.liability[3],'debit':0,'credit':40}])
        output=self.folder/'empty.html'
        report=self.store.export_ledger_html(self.cid,self.fy,self.liability[2],output)
        self.assertEqual(report['rows'],[])
        self.assertEqual(report['closing'],0)
        self.assertNotIn('پیش نویس نباید در گزارش بیاید',output.read_text(encoding='utf-8'))

class MigrationTests(unittest.TestCase):
    def test_51_migrates_v01_database_and_snapshots_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'prior.sqlite3'
            old_schema=Path(__file__).resolve().parent/'fixtures'/'schema_v01.sql'
            with closing(sqlite3.connect(str(file))) as conn:
                conn.executescript(old_schema.read_text(encoding='utf-8'))
                conn.execute("INSERT INTO companies(name) VALUES ('Old Co')")
                conn.execute("INSERT INTO accounts(company_id,code,title,level,nature) VALUES (1,'1','Old assets',1,'debit')")
                conn.commit()
            migrated=AccountingStore(file)
            self.assertEqual(migrated.accounts(1)[0]['account_class'],'unclassified')
            snapshot=file.with_suffix('.pre_v02.sqlite3')
            self.assertTrue(snapshot.exists())
            with closing(sqlite3.connect(str(snapshot))) as conn:
                self.assertNotIn('account_class',[x[1] for x in conn.execute('PRAGMA table_info(accounts)')])
            with closing(migrated._connection()) as conn:
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],2)

if __name__=='__main__':unittest.main(verbosity=2)
