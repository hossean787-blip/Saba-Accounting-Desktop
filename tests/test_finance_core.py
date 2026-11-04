"""Finance v0.4 acceptance and edge-case tests (independent fictional data)."""
import csv
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from saba_accounting.finance import FinanceStore, AccountingError

class FinanceAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'finance.sqlite3'
        self.store=FinanceStore(self.path)
        self.c=self.store.create_company('آزمایش صورت مالی')
        self.y1=self.store.create_fiscal_year(self.c,'1405','1405/01/01','1405/12/29')
        self.y2=self.store.create_fiscal_year(self.c,'1406','1406/01/01','1406/12/29')
        self.a=self.account('1','asset')
        self.l=self.account('2','liability')
        self.e=self.account('3','equity')
        self.r=self.account('4','revenue')
        self.x=self.account('5','expense')
        self.cost=self.account('6','cost')
        self.retained=self.account('39','equity')
    def account(self, prefix, cl):
        # Root grouping: one extra equity account uses the existing equity root.
        roots=[r for r in self.store.accounts(self.c) if r['level']==1 and r['account_class']==cl]
        root=roots[0]['id'] if roots else self.store.create_account(self.c,prefix,'گروه '+cl,1,account_class=cl)
        stem=prefix if not roots else prefix+'0'
        a=self.store.create_account(self.c,stem+'1','کل',2,parent_id=root)
        b=self.store.create_account(self.c,stem+'11','معین',3,parent_id=a)
        return self.store.create_account(self.c,stem+'111','تفصیلی',4,parent_id=b,is_postable=True)
    def doc(self, debit,credit,money,day='1405/02/01',year=None):
        ident=self.store.new_draft(self.c,year or self.y1,day,'ثبت آزمایشی',[
            {'account_id':debit,'debit':money}, {'account_id':credit,'credit':money}])
        self.store.post(self.c,ident)
        return ident
    def seed(self):
        self.doc(self.a,self.e,1000)
        self.doc(self.a,self.r,900)
        self.doc(self.cost,self.a,400)
        self.doc(self.x,self.a,200)
    def close(self):
        return self.store.close_fiscal_year(self.c,self.y1,self.y2,self.retained)

    def test_reconcile_journal_trial_and_ledger(self):
        self.seed()
        report=self.store.reconcile_accounting_reports(self.c,self.y1)
        self.assertTrue(report['ok'],report)
        self.assertEqual(report['totals']['journal'],{'debit':2500,'credit':2500})
        self.assertEqual(report['totals']['journal'],report['totals']['ledger'])

    def test_reconcile_ignores_unposted_draft(self):
        self.seed()
        self.store.new_draft(self.c,self.y1,'1405/02/02','پیش‌نویس',[
          {'account_id':self.a,'debit':500},{'account_id':self.e,'credit':500}])
        self.assertEqual(self.store.reconcile_accounting_reports(self.c,self.y1)['totals']['journal']['debit'],2500)

    def test_reconcile_closed_year_both_modes(self):
        self.seed()
        before=self.store.reconcile_accounting_reports(self.c,self.y1)
        self.close()
        after=self.store.reconcile_accounting_reports(self.c,self.y1)
        including=self.store.reconcile_accounting_reports(self.c,self.y1,include_closing=True)
        self.assertTrue(before['ok'] and after['ok'] and including['ok'])
        self.assertEqual(after['totals'],before['totals'])
        self.assertGreater(including['totals']['journal']['debit'],after['totals']['journal']['debit'])

    def test_reconcile_rejects_foreign_year_and_exports_utf8(self):
        self.seed()
        other=self.store.create_company('شرکت جدا')
        with self.assertRaises(AccountingError):
            self.store.reconcile_accounting_reports(other,self.y1)
        path=Path(self.temp.name)/'reconciliation.csv'
        result=self.store.export_reconciliation_csv(self.c,self.y1,path)
        self.assertTrue(result['ok'])
        self.assertEqual(path.read_bytes()[:3],b'\xef\xbb\xbf')
        self.assertIn('دفتر روزنامه',path.read_text(encoding='utf-8-sig'))

    def test_01_migrated_finance_schema(self):
        with closing(self.store._connection()) as conn:
            cols=[r['name'] for r in conn.execute('PRAGMA table_info(journal_entries)')]
            self.assertIn('entry_kind',cols)
            self.assertIn('correction_of_id',cols)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],4)

    def test_02_floating_detail_is_booked(self):
        detail=self.store.add_floating_detail(self.c,'T-1','طرف قرارداد','person')
        ident=self.store.new_draft(self.c,self.y1,'1405/02/02','بدهکار شخص',[
            {'account_id':self.a,'debit':250,'detail_id':detail},
            {'account_id':self.e,'credit':250}])
        self.store.post(self.c,ident)
        self.assertEqual(self.store.journal(self.c,ident)['lines'][0]['detail_id'],detail)
        self.assertEqual(self.store.floating_ledger(self.c,self.y1,detail)[0]['debit_rial'],250)

    def test_03_foreign_company_detail_denied(self):
        other=self.store.create_company('شرکت دیگر')
        detail=self.store.add_floating_detail(other,'T-1','دیگری','person')
        with self.assertRaises(AccountingError):
            self.store.new_draft(self.c,self.y1,'1405/02/02','نباید ذخیره شود',[
              {'account_id':self.a,'debit':100,'detail_id':detail},
              {'account_id':self.e,'credit':100}])

    def test_04_detail_required_on_post(self):
        self.store.require_floating_detail(self.c,self.a,True)
        ident=self.store.new_draft(self.c,self.y1,'1405/02/01','بدون بعد',[
            {'account_id':self.a,'debit':100}, {'account_id':self.e,'credit':100}])
        with self.assertRaises(AccountingError):self.store.post(self.c,ident)
        self.assertEqual(self.store.journal(self.c,ident)['status'],'draft')

    def test_floating_detail_update_checks_company_and_active_status(self):
        detail=self.store.add_floating_detail(self.c,'X-1','تفصیلی معتبر','person')
        outsider=self.store.create_company('شرکت دوم')
        foreign_detail=self.store.add_floating_detail(outsider,'X-2','تفصیلی نامعتبر','person')
        entry=self.store.new_draft(self.c,self.y1,'1405/02/02','آزمون تغییر تفصیلی',[
            {'account_id':self.a,'debit':100,'detail_id':detail},
            {'account_id':self.e,'credit':100}])
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE journal_lines SET detail_id=? WHERE entry_id=? AND row_no=1',(foreign_detail,entry))
        with self.store._write() as conn:
            conn.execute('UPDATE floating_details SET is_active=0 WHERE id=?',(detail,))
        with self.assertRaises(AccountingError):
            with self.store._write() as conn:
                conn.execute('UPDATE journal_lines SET entry_id=entry_id WHERE entry_id=? AND row_no=1',(entry,))
        self.assertEqual(self.store.journal(self.c,entry)['lines'][0]['detail_id'],detail)

    def test_05_close_full_lifecycle_and_equal_balances(self):
        self.seed()
        pre=self.store.statements(self.c,self.y1)
        self.assertEqual(pre['net_profit'],300)
        preview=self.store.closing_preview(self.c,self.y1,self.y2,self.retained)
        self.assertEqual(preview['profit'],300)
        result=self.close()
        self.assertEqual(result['profit'],300)
        self.assertTrue(Path(result['backup']).exists())
        self.assertEqual(self.store.statements(self.c,self.y1)['net_profit'],300)
        self.assertEqual(self.store.statements(self.c,self.y1)['assets']['total'],1300)
        self.assertEqual(self.store.trial_balance(self.c,self.y1)[0]['debit'],1900)
        raw=self.store.trial_balance(self.c,self.y1,include_closing=True)
        self.assertEqual(sum(r['debit']-r['credit'] for r in raw),0)
        self.assertTrue(all(r['debit']==r['credit'] for r in raw))
        next_r=self.store.statements(self.c,self.y2)
        self.assertEqual(next_r['net_profit'],0)
        self.assertEqual(next_r['assets']['total'],1300)
        self.assertEqual(next_r['balance_difference'],0)
        self.assertEqual(next_r['equity']['total'],1300)
        self.assertTrue(self.store._year(self.c,self.y1)['is_closed'])
        self.assertIsNotNone(self.store.closure_info(self.c,self.y1))
        self.assertTrue(result['opening_id'])

    def test_06_close_empty_year_blocked(self):
        with self.assertRaises(AccountingError):self.close()
        self.assertFalse(self.store._year(self.c,self.y1)['is_closed'])

    def test_07_close_with_draft_blocked(self):
        self.seed()
        self.store.new_draft(self.c,self.y1,'1405/03/01','پیش‌نویس',[
            {'account_id':self.a,'debit':10}, {'account_id':self.e,'credit':10}])
        with self.assertRaises(AccountingError):self.close()

    def test_08_duplicate_close_blocked(self):
        self.seed();self.close()
        with self.assertRaises(AccountingError):self.close()

    def test_09_close_rejects_next_year_with_documents(self):
        self.seed();self.doc(self.a,self.e,100,day='1406/02/01',year=self.y2)
        with self.assertRaises(AccountingError):self.close()

    def test_10_close_does_not_allow_original_year_changes(self):
        self.seed();self.close()
        with self.assertRaises(AccountingError):self.doc(self.a,self.e,200)
        with self.assertRaises(AccountingError):self.store.new_draft(self.c,self.y1,'1405/12/29','بسته',[
            {'account_id':self.a,'debit':20},{'account_id':self.e,'credit':20}])

    def test_11_prevent_reverse_opening_and_closing(self):
        self.seed();res=self.close()
        with self.assertRaises(AccountingError):self.store.reverse(self.c,res['opening_id'],'1406/01/01')

    def test_12_adjustment_has_audit_and_posts(self):
        ident=self.store.create_adjustment(self.c,self.y1,'1405/05/01','اصلاح مبلغ حساب',[
            {'account_id':self.a,'debit':85},{'account_id':self.e,'credit':85}])
        self.assertEqual(self.store.journal(self.c,ident)['entry_kind'],'adjustment')
        self.assertEqual(self.store.journal(self.c,ident)['status'],'posted')

    def test_13_correction_atomic_and_linked(self):
        ident=self.doc(self.a,self.e,100)
        result=self.store.correct_posted(self.c,ident,'1405/02/03','اصلاح مبلغ سند',[
            {'account_id':self.a,'debit':200},{'account_id':self.e,'credit':200}])
        self.assertEqual(self.store.journal(self.c,result['corrected_id'])['correction_of_id'],ident)
        bal={r['id']:r for r in self.store.trial_balance(self.c,self.y1)}
        self.assertEqual(bal[self.a]['debit']-bal[self.a]['credit'],200)

    def test_14_correction_failure_keeps_source_and_no_partial_undo(self):
        ident=self.doc(self.a,self.e,100)
        size=len(self.store.journals(self.c,self.y1))
        with self.assertRaises(AccountingError):self.store.correct_posted(self.c,ident,'1405/02/03','اصلاح مبلغ سند',[
            {'account_id':self.a,'debit':200},{'account_id':self.e,'credit':199}])
        self.assertEqual(len(self.store.journals(self.c,self.y1)),size)
        self.assertEqual(self.store.journal(self.c,ident)['status'],'posted')

    def test_15_levels_roll_up(self):
        self.seed()
        for level in (1,2,3,4):
            tb=self.store.trial_balance_levels(self.c,self.y1,level)
            self.assertEqual(sum(row['debit'] for row in tb),2500)
            self.assertEqual(sum(row['credit'] for row in tb),2500)

    def test_16_general_journal_csv(self):
        self.seed();path=Path(self.temp.name)/'journal.csv'
        self.store.export_general_journal_csv(self.c,self.y1,path)
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn('شماره سند',path.read_text('utf-8-sig'))

    def test_17_wrong_company_close_fails(self):
        self.seed();other=self.store.create_company('دیگر')
        other_year=self.store.create_fiscal_year(other,'1406','1406/01/01','1406/12/29')
        with self.assertRaises(AccountingError):self.store.close_fiscal_year(self.c,self.y1,other_year,self.retained)

    def test_18_retained_must_be_equity(self):
        self.seed()
        with self.assertRaises(AccountingError):self.store.closing_preview(self.c,self.y1,self.y2,self.a)

    def test_19_no_duplicate_correction(self):
        ident=self.doc(self.a,self.e,100)
        payload=[{'account_id':self.a,'debit':200},{'account_id':self.e,'credit':200}]
        self.store.correct_posted(self.c,ident,'1405/02/03','اصلاح مبلغ سند',payload)
        with self.assertRaises(AccountingError):self.store.correct_posted(self.c,ident,'1405/02/04','اصلاح مجدد سند',payload)

    def test_20_preserve_floating_dimension_on_year_open(self):
        detail=self.store.add_floating_detail(self.c,'P02','مشتری فرضی','person')
        self.store.require_floating_detail(self.c,self.a,True)
        eid=self.store.new_draft(self.c,self.y1,'1405/02/01','سرمایه از شخص',[
            {'account_id':self.a,'debit':1000,'detail_id':detail},
            {'account_id':self.e,'credit':1000}]);self.store.post(self.c,eid)
        self.close()
        r=self.store.floating_ledger(self.c,self.y2,detail)
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]['debit_rial'],1000)

if __name__=='__main__':unittest.main(verbosity=2)

# Additional tests beyond the base lifecycle guard financial edge cases.
class FinanceGuards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=FinanceStore(Path(self.tmp.name)/'test.sqlite3')
        self.cid=self.s.create_company('مؤسسه آموزشی')
        self.yr=self.s.create_fiscal_year(self.cid,'1405','1405/01/01','1405/12/29')
        def a(code,cl):
            group=self.s.create_account(self.cid,code,'گروه',1,account_class=cl)
            gl=self.s.create_account(self.cid,code+'1','کل',2,parent_id=group)
            sl=self.s.create_account(self.cid,code+'11','معین',3,parent_id=gl)
            return self.s.create_account(self.cid,code+'111','تفصیلی',4,parent_id=sl,is_postable=True)
        self.asset=a('1','asset');self.equity=a('3','equity')
    def test_21_reversal_preserves_detail(self):
        det=self.s.add_floating_detail(self.cid,'C1','مشتری','person')
        i=self.s.new_draft(self.cid,self.yr,'1405/02/01','اصل',[
            {'account_id':self.asset,'debit':100,'detail_id':det},
            {'account_id':self.equity,'credit':100}])
        self.s.post(self.cid,i)
        r=self.s.reverse(self.cid,i,'1405/02/03')
        self.assertEqual(self.s.journal(self.cid,r)['lines'][0]['detail_id'],det)
        self.assertEqual(sum(z['debit_rial']-z['credit_rial'] for z in self.s.floating_ledger(self.cid,self.yr,det)),0)
    def test_22_failing_adjustment_does_not_leave_draft(self):
        with self.assertRaises(AccountingError):self.s.create_adjustment(self.cid,self.yr,'1405/03/01','اصلاح نامعتبر',[
            {'account_id':self.asset,'debit':200}, {'account_id':self.equity,'credit':199}])
        self.assertEqual(self.s.journals(self.cid,self.yr),[])
class ReportAndLocks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.s=FinanceStore(Path(self.temp.name)/'s.sqlite3')
        self.c=self.s.create_company('کارگاه آزمایشی')
        self.y=self.s.create_fiscal_year(self.c,'1405','1405/01/01','1405/12/29')
        self.a={}
        for code,cl in [('1','asset'),('3','equity'),('4','revenue')]:
            r=self.s.create_account(self.c,code,cl,1,account_class=cl)
            k=self.s.create_account(self.c,code+'1',cl,2,parent_id=r)
            m=self.s.create_account(self.c,code+'11',cl,3,parent_id=k)
            self.a[cl]=self.s.create_account(self.c,code+'111',cl,4,parent_id=m,is_postable=True)
    def doc(self,day,db,cr,amount):
        i=self.s.new_draft(self.c,self.y,day,'ثبت',[
            {'account_id':self.a[db],'debit':amount},{'account_id':self.a[cr],'credit':amount}]);self.s.post(self.c,i)
    def test_23_six_column_preserves_opening_and_movement(self):
        self.doc('1405/01/01','asset','equity',1000)
        self.doc('1405/02/01','asset','revenue',200)
        rows=self.s.trial_balance_six(self.c,self.y,'1405/02/01','1405/12/29')
        asset=next(r for r in rows if r['code']=='1111')
        self.assertEqual((asset['opening_debit'],asset['movement_debit'],asset['closing_debit']),(1000,200,1200))
    def test_24_six_column_export(self):
        path=Path(self.temp.name)/'6.csv'
        self.s.export_trial_six_csv(self.c,self.y,path)
        self.assertIn('ابتدای دوره بدهکار',path.read_text('utf-8-sig'))
    def test_25_period_lock_rejects_post(self):
        self.s.lock_period(self.c,self.y,'1405/02/01','1405/02/30')
        i=self.s.new_draft(self.c,self.y,'1405/02/12','دوره قفل',[
            {'account_id':self.a['asset'],'debit':100},{'account_id':self.a['equity'],'credit':100}])
        with self.assertRaises(AccountingError):self.s.post(self.c,i)
        self.doc('1405/03/01','asset','equity',100)
    def test_26_html_safe_escaped(self):
        self.doc('1405/02/01','asset','equity',100)
        path=Path(self.temp.name)/'s.html'
        self.s.export_statement_html(self.c,self.y,path)
        self.assertIn('lang="fa"',path.read_text('utf-8'))
        self.assertIn('اختلاف ترازنامه',path.read_text('utf-8'))
    def test_27_html_journal(self):
        self.doc('1405/02/01','asset','equity',100)
        path=Path(self.temp.name)/'journal.html'
        self.s.export_general_journal_html(self.c,self.y,path)
        self.assertIn('دفتر روزنامه داخلی',path.read_text('utf-8'))
class DemoYearEndAcceptance(unittest.TestCase):
    def test_28_demo_profit_and_close(self):
        from saba_accounting.demo_finance import seed_finance_demo
        with tempfile.TemporaryDirectory() as tmp:
            s=FinanceStore(Path(tmp)/'demo.sqlite3')
            conf=seed_finance_demo(s)
            self.assertEqual(s.statements(conf['company_id'],conf['current_year'])['net_profit'],conf['profit'])
            y=s.close_fiscal_year(conf['company_id'],conf['current_year'],conf['next_year'],conf['retained_account'])
            self.assertEqual(y['profit'],60_000_000)
            self.assertEqual(s.statements(conf['company_id'],conf['next_year'])['balance_difference'],0)
    def test_29_html_escapes_user_data(self):
        from saba_accounting.finance import FinanceStore
        val=FinanceStore._render_html('x<script>alert(1)</script>',['text'],[['<img src=x onerror=alert(1)>']])
        self.assertNotIn('<script>',val)
        self.assertNotIn('<img src',val)
class AuditProtection(unittest.TestCase):
    def test_30_audit_cannot_be_mutated_by_normal_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=FinanceStore(Path(tmp)/'audit.sqlite3')
            c=s.create_company('آزمون سابقه')
            with self.assertRaises(AccountingError):
                with s._write() as conn:
                    conn.execute("UPDATE audit_events SET note='altered' WHERE company_id=?",(c,))
            with self.assertRaises(AccountingError):
                with s._write() as conn:
                    conn.execute('DELETE FROM audit_events WHERE company_id=?',(c,))
class ProfitAndEmptyNominalGuards(unittest.TestCase):
    def setup_case(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        s=FinanceStore(Path(self.tmp.name)/'loss.sqlite3')
        c=s.create_company('زیان آزمایشی')
        y1=s.create_fiscal_year(c,'1405','1405/01/01','1405/12/29')
        y2=s.create_fiscal_year(c,'1406','1406/01/01','1406/12/29')
        accounts={}
        for code,cl in [('1','asset'),('2','liability'),('3','equity'),('6','expense')]:
            root=s.create_account(c,code,cl,1,account_class=cl)
            gl=s.create_account(c,code+'1',cl,2,parent_id=root)
            sub=s.create_account(c,code+'11',cl,3,parent_id=gl)
            accounts[cl]=s.create_account(c,code+'111',cl,4,parent_id=sub,is_postable=True)
        return s,c,y1,y2,accounts
    def doc(self,s,c,y,acct_a,acct_b,amount):
        i=s.new_draft(c,y,'1405/02/01','زیان آزمایشی',[
            {'account_id':acct_a,'debit':amount},{'account_id':acct_b,'credit':amount}]);s.post(c,i)
    def test_31_loss_is_carried_to_equity(self):
        s,c,y1,y2,a=self.setup_case()
        self.doc(s,c,y1,a['asset'],a['equity'],100)
        self.doc(s,c,y1,a['expense'],a['liability'],200)
        self.assertEqual(s.statements(c,y1)['net_profit'],-200)
        out=s.close_fiscal_year(c,y1,y2,a['equity'])
        self.assertEqual(out['profit'],-200)
        r=s.statements(c,y2)
        self.assertEqual(r['assets']['total'],100)
        self.assertEqual(r['equity']['total'],-100)
        self.assertEqual(r['liabilities']['total'],200)
        self.assertEqual(r['balance_difference'],0)
    def test_32_year_without_nominal_has_no_result_journal(self):
        s,c,y1,y2,a=self.setup_case()
        self.doc(s,c,y1,a['asset'],a['equity'],100)
        out=s.close_fiscal_year(c,y1,y2,a['equity'])
        self.assertIsNone(out['result_id'])
        self.assertIsNotNone(out['close_id'])
        self.assertEqual(s.statements(c,y2)['assets']['total'],100)
