import tempfile
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from saba_accounting.erp import ERPStore, AccountingError

DATE='۱۴۰۵/۰۲/۰۵'


class ERPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'a.sqlite3'
        self.s=ERPStore(self.db)
        self.c=self.s.create_company('شرکت تست')
        self.y=self.s.create_fiscal_year(self.c,'۱۴۰۵','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
        self.a={}
        for number,(name,kind) in enumerate((('assets','asset'),('liabilities','liability'),
                    ('equity','equity'),('revenue','revenue'),('expense','expense'),('cost','cost')),1):
            g=self.s.create_account(self.c,str(number),name,1,account_class=kind)
            k=self.s.create_account(self.c,str(number)+'1',name,2,parent_id=g)
            m=self.s.create_account(self.c,str(number)+'101',name,3,parent_id=k)
            for i,key in enumerate(({'assets':['cash','ar','inventory','finished','inputvat','fixed'],
                       'liabilities':['ap','outputvat','payrollpay','payrolldeduct','accum'],
                       'equity':['capital'], 'revenue':['sales'],
                       'expense':['salaryexp','depexp','projexp'],'cost':['cogs']}[name]),1):
                self.a[key]=self.s.create_account(self.c,str(number)+'101'+str(i).zfill(2),key,4,parent_id=m,is_postable=True)
        self.s.configure(self.c,cash_account=self.a['cash'],receivable_account=self.a['ar'],
                payable_account=self.a['ap'],inventory_account=self.a['inventory'],
                cogs_account=self.a['cogs'],sales_account=self.a['sales'],
                vat_input_account=self.a['inputvat'],vat_output_account=self.a['outputvat'],
                payroll_expense_account=self.a['salaryexp'],payroll_payable_account=self.a['payrollpay'],
                payroll_deduction_account=self.a['payrolldeduct'],
                depreciation_expense_account=self.a['depexp'],
                accumulated_depreciation_account=self.a['accum'],
                finished_goods_account=self.a['finished'])
        self.vendor=self.s.create_party(self.c,'S1','تأمین‌کننده','supplier')
        self.customer=self.s.create_party(self.c,'C1','مشتری','customer')
        self.wh=self.s.create_warehouse(self.c,'انبار اصلی')
        self.item=self.s.create_item(self.c,'A1','کالای پایه')
        self.service=self.s.create_item(self.c,'SVC','خدمات','service')
        self.box=self.s.create_cashbox(self.c,'بانک اصلی','bank',self.a['cash'])

    def tearDown(self):self.tmp.cleanup()

    def _line(self,item,qty,unit,tax=0):
        return {'item_id':item,'qty':qty,'unit_price_rial':unit,'tax_rate_bps':tax}

    def _purchase(self,ref='P1',qty=10,unit=1000,tax=0):
        return self.s.invoice(self.c,self.y,DATE,'purchase',ref,self.vendor,self.wh,[self._line(self.item,qty,unit,tax)])

    def _sale(self,ref='S1',qty=4,unit=1400,tax=0):
        return self.s.invoice(self.c,self.y,DATE,'sale',ref,self.customer,self.wh,[self._line(self.item,qty,unit,tax)])

    def _assert_balanced(self):
        trial=self.s.trial_balance(self.c,self.y)
        self.assertEqual(sum(r['debit'] for r in trial),sum(r['credit'] for r in trial))

    def test_01_configuration_persists(self):
        self.assertEqual(self.s.config(self.c)['receivable_account'],self.a['ar'])

    def test_02_configuration_other_company_rejected(self):
        other=self.s.create_company('متفرقه')
        with self.assertRaises(AccountingError):self.s.configure(other,cash_account=self.a['cash'])

    def test_03_treasury_receipt_posts(self):
        self.s.cash_flow(self.c,self.y,DATE,self.box,'receipt',5000,self.a['capital'],'R01')
        self._assert_balanced()
        self.assertEqual(self.s.ledger(self.c,self.y,self.a['cash'])['closing'],5000)

    def test_04_treasury_payment_posts(self):
        self.s.cash_flow(self.c,self.y,DATE,self.box,'payment',300,self.a['projexp'],'Q01')
        self._assert_balanced()
        self.assertEqual(self.s.ledger(self.c,self.y,self.a['cash'])['closing'],-300)

    def test_05_duplicate_cash_ref_rolls_back(self):
        self.s.cash_flow(self.c,self.y,DATE,self.box,'receipt',200,self.a['capital'],'K001')
        with self.assertRaises((AccountingError,sqlite3.IntegrityError)):
            self.s.cash_flow(self.c,self.y,DATE,self.box,'receipt',200,self.a['capital'],'K001')
        self.assertEqual(len(self.s.journals(self.c,self.y)),1)

    def test_06_cash_other_company_rejected(self):
        other=self.s.create_company('دیگری'); fy=self.s.create_fiscal_year(other,'۱۴۰۵','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
        with self.assertRaises(AccountingError):
            self.s.cash_flow(other,fy,DATE,self.box,'receipt',100,self.a['capital'],'X')

    def test_07_check_register_and_clear(self):
        ident=self.s.register_check(self.c,'100','بانک تست',DATE,500,'received',self.customer)
        self.s.update_check_status(self.c,ident,'cleared')
        with self.assertRaises(AccountingError):self.s.update_check_status(self.c,ident,'void')
        self.assertEqual(len(self.s.journals(self.c,self.y)),0)

    def test_08_purchase_stock_value(self):
        self._purchase(tax=900)
        self.assertEqual(self.s.items(self.c)[0]['qty'],10)
        self.assertEqual(self.s.items(self.c)[0]['value_rial'],10000)
        self._assert_balanced()

    def test_09_purchase_tax_amount(self):
        self._purchase(tax=900)
        inv=self.s.invoices(self.c)[0]
        self.assertEqual((inv['subtotal_rial'],inv['tax_rial'],inv['total_rial']),(10000,900,10900))

    def test_10_sale_weighted_cost(self):
        self._purchase()
        self._sale()
        row=next(x for x in self.s.items(self.c) if x['id']==self.item)
        self.assertEqual((row['qty'],row['value_rial']),(6,6000))
        self._assert_balanced()
        self.assertEqual(self.s.statements(self.c,self.y)['net_profit'],1600)

    def test_11_sale_cannot_overdraw_inventory(self):
        self._purchase()
        before=len(self.s.journals(self.c,self.y))
        with self.assertRaises(AccountingError):self._sale(qty=50)
        self.assertEqual(len(self.s.journals(self.c,self.y)),before)

    def test_12_cross_company_party_rejected(self):
        other=self.s.create_company('دو'); other_party=self.s.create_party(other,'C','غریبه')
        with self.assertRaises(AccountingError):
            self.s.invoice(self.c,self.y,DATE,'sale','X',other_party,self.wh,[self._line(self.service,1,200)])

    def test_13_duplicate_invoice_no_double_stock(self):
        self._purchase()
        with self.assertRaises((AccountingError,sqlite3.IntegrityError)):self._purchase()
        row=next(x for x in self.s.items(self.c) if x['id']==self.item)
        self.assertEqual(row['qty'],10)

    def test_14_multi_line_inventory_consistent(self):
        self._purchase(qty=10,unit=7)
        self.s.invoice(self.c,self.y,DATE,'sale','S3',self.customer,self.wh,
                  [self._line(self.item,2,14),self._line(self.item,8,14)])
        row=next(x for x in self.s.items(self.c) if x['id']==self.item)
        self.assertEqual((row['qty'],row['value_rial']),(0,0))

    def test_15_services_do_not_change_stock(self):
        self.s.invoice(self.c,self.y,DATE,'sale','SV1',self.customer,None,[self._line(self.service,1,999)])
        self.assertEqual(next(x for x in self.s.items(self.c) if x['id']==self.service)['qty'],0)
        self._assert_balanced()

    def test_16_no_invoice_in_closed_year(self):
        with self.s._write() as conn:conn.execute('UPDATE fiscal_years SET is_closed=1 WHERE id=?',(self.y,))
        with self.assertRaises(AccountingError):self._purchase()

    def test_17_local_tax_csv_not_submission(self):
        self.s.invoice(self.c,self.y,DATE,'sale','T1',self.customer,None,[self._line(self.service,1,1000)])
        path=Path(self.tmp.name)/'out.csv'
        self.assertEqual(self.s.tax_export(self.c,path),1)
        self.assertIn('ارسال‌نشده',path.read_text('utf-8-sig'))

    def test_18_payroll_deductions_accounting(self):
        person=self.s.create_employee(self.c,'E1','کارمند')
        self.s.payroll(self.c,self.y,DATE,person,'1405-02',1000,100)
        self._assert_balanced()
        self.assertEqual(self.s.ledger(self.c,self.y,self.a['payrollpay'])['closing'],-900)
        self.assertEqual(self.s.ledger(self.c,self.y,self.a['payrolldeduct'])['closing'],-100)

    def test_19_payroll_duplicate_blocked(self):
        person=self.s.create_employee(self.c,'E1','کارمند')
        self.s.payroll(self.c,self.y,DATE,person,'1405-02',1000,0)
        with self.assertRaises((AccountingError,sqlite3.IntegrityError)):
            self.s.payroll(self.c,self.y,DATE,person,'1405-02',1000,0)
        self.assertEqual(len(self.s.journals(self.c,self.y)),1)

    def test_20_asset_depreciation_schedule(self):
        asset=self.s.create_asset(self.c,'X1','ماشین',1200,0,12)
        for m in range(1,13):self.s.depreciate(self.c,self.y,DATE,asset,'M'+str(m))
        with self.assertRaises(AccountingError):self.s.depreciate(self.c,self.y,DATE,asset,'M13')
        self.assertEqual(self.s.ledger(self.c,self.y,self.a['accum'])['closing'],-1200)
        self._assert_balanced()

    def test_21_asset_depreciation_duplicate(self):
        asset=self.s.create_asset(self.c,'X2','ماشین',1200,0,12)
        self.s.depreciate(self.c,self.y,DATE,asset,'M1')
        with self.assertRaises((AccountingError,sqlite3.IntegrityError)):self.s.depreciate(self.c,self.y,DATE,asset,'M1')
        self.assertEqual(len(self.s.journals(self.c,self.y)),1)

    def test_22_production_consumes_material(self):
        self._purchase(qty=10,unit=100)
        finished=self.s.create_item(self.c,'B','محصول')
        self.s.bom_add(self.c,finished,self.item,2)
        self.s.produce(self.c,self.y,DATE,finished,3,self.wh,'W1')
        rows={x['id']:x for x in self.s.items(self.c)}
        self.assertEqual((rows[self.item]['qty'],rows[self.item]['value_rial']),(4,400))
        self.assertEqual((rows[finished]['qty'],rows[finished]['value_rial']),(3,600))
        self._assert_balanced()

    def test_23_production_insufficient_input_rolls_back(self):
        self._purchase(qty=1,unit=100)
        finished=self.s.create_item(self.c,'B','محصول')
        self.s.bom_add(self.c,finished,self.item,2)
        with self.assertRaises(AccountingError):self.s.produce(self.c,self.y,DATE,finished,3,self.wh,'W1')
        self.assertEqual(len(self.s.journals(self.c,self.y)),1)

    def test_24_project_cost_and_budget(self):
        project=self.s.create_project(self.c,'P','پروژه آزمایشی',20000)
        self.s.project_cost(self.c,self.y,DATE,project,500,self.a['projexp'],self.a['ap'])
        self.s.set_budget(self.c,self.y,self.a['projexp'],1000)
        self.assertEqual(self.s.budgets(self.c,self.y)[0]['amount_rial'],1000)
        self._assert_balanced()

    def test_25_rollback_if_account_missing(self):
        with self.assertRaises(AccountingError):
            self.s.invoice(self.c,self.y,DATE,'purchase','ZZ',self.vendor,self.wh,[self._line(self.item,1,200)]) if False else \
            self.s.cash_flow(self.c,self.y,DATE,self.box,'receipt',100,9999,'NO')
        self.assertEqual(len(self.s.journals(self.c,self.y)),0)

    def test_26_database_integrity(self):
        # sqlite3.Connection's context manager commits/rolls back but does not
        # close; an explicit close is required before Windows removes temp DBs.
        with closing(self.s._connection()) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_27_already_used_cross_company_item(self):
        other=self.s.create_company('دو')
        alien=self.s.create_item(other,'A','کالا')
        with self.assertRaises(AccountingError):
            self.s.invoice(self.c,self.y,DATE,'sale','ALIEN',self.customer,self.wh,[self._line(alien,1,50)])

    def test_28_invalid_tax_rate(self):
        with self.assertRaises(AccountingError):
            self.s.invoice(self.c,self.y,DATE,'sale','TAX',self.customer,None,[self._line(self.service,1,100,11000)])

    def test_29_duplicate_production_ref(self):
        self._purchase(qty=10,unit=100)
        finished=self.s.create_item(self.c,'B','محصول')
        self.s.bom_add(self.c,finished,self.item,2)
        self.s.produce(self.c,self.y,DATE,finished,1,self.wh,'PROD')
        with self.assertRaises((AccountingError,sqlite3.IntegrityError)):
            self.s.produce(self.c,self.y,DATE,finished,1,self.wh,'PROD')
        self.assertEqual(self.s.items(self.c)[0]['qty'],8)

    def test_30_overview_scoped(self):
        self._purchase()
        self.assertEqual(self.s.overview(self.c)['invoices'],1)
        other=self.s.create_company('دو')
        self.assertEqual(self.s.overview(other)['invoices'],0)

    def test_31_stale_config_not_allowed(self):
        with self.s._write() as conn:conn.execute('UPDATE erp_config SET payable_account=NULL WHERE company_id=?',(self.c,))
        with self.assertRaises(AccountingError):self._purchase()
        self.assertEqual(len(self.s.journals(self.c,self.y)),0)

    def test_32_backup_integrity(self):
        self._purchase()
        target=Path(self.tmp.name)/'backup.db'
        self.s.backup(target)
        restore=ERPStore(target)
        self.assertEqual(restore.overview(self.c)['invoices'],1)


if __name__=='__main__':unittest.main()

class MigrationAndIntegrityTests(unittest.TestCase):
    def test_migrates_v02_with_snapshot(self):
        from saba_accounting.storage import AccountingStore
        with tempfile.TemporaryDirectory() as p:
            filename=Path(p)/'previous.db'
            old=AccountingStore(filename)
            cid=old.create_company('قدیمی')
            new=ERPStore(filename)
            self.assertEqual(new.companies()[0]['id'],cid)
            self.assertTrue(filename.with_suffix('.pre_v03.sqlite3').exists())
            self.assertTrue(new.integrity_report(cid)['ok'])
            self.assertEqual(new._read_one('PRAGMA user_version'),{'user_version':3})

    def test_finds_manually_corrupted_stock_snapshot(self):
        with tempfile.TemporaryDirectory() as p:
            s=ERPStore(Path(p)/'test.db');cid=s.create_company('امتحان')
            item=s.create_item(cid,'X1','کالای تست')
            self.assertTrue(s.integrity_report(cid)['ok'])
            with s._write() as conn:conn.execute('UPDATE erp_items SET qty=qty+1 WHERE id=?',(item,))
            self.assertFalse(s.integrity_report(cid)['ok'])

class JournalProtectionTest(unittest.TestCase):
    def test_erp_journal_cannot_be_manually_reversed(self):
        with tempfile.TemporaryDirectory() as p:
            s=ERPStore(Path(p)/'a.db')
            c=s.create_company('تست')
            y=s.create_fiscal_year(c,'۱۴۰۵','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
            root=s.create_account(c,'1','دارایی',1,account_class='asset')
            lvl2=s.create_account(c,'11','جاری',2,parent_id=root)
            lvl3=s.create_account(c,'1101','نقد',3,parent_id=lvl2)
            cash=s.create_account(c,'110101','صندوق',4,parent_id=lvl3,is_postable=True)
            other=s.create_account(c,'110102','طرف',4,parent_id=lvl3,is_postable=True)
            cb=s.create_cashbox(c,'صندوق','cash',cash)
            s.cash_flow(c,y,'۱۴۰۵/۰۲/۰۵',cb,'receipt',100,other,'REF')
            entry=s.journals(c,y)[0]['id']
            with self.assertRaises(AccountingError):s.reverse(c,entry,'۱۴۰۵/۰۲/۰۶')
            self.assertEqual(len(s.journals(c,y)),1)
