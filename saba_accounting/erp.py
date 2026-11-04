"""Independent modular business workflows on the audited accounting journal.
Experimental, single-user and offline; not production tax / payroll software.
Transactions are committed with journal posting or rolled back in full.
"""
import csv
import json
import sqlite3
from pathlib import Path
from contextlib import closing

from .storage import AccountingStore, AccountingError
from .jalali import parse_jalali


class ERPStore(AccountingStore):
    ACCOUNT_KEYS = ('cash_account','receivable_account','payable_account','inventory_account',
                    'cogs_account','sales_account','vat_input_account','vat_output_account',
                    'payroll_expense_account','payroll_payable_account','payroll_deduction_account',
                    'depreciation_expense_account','accumulated_depreciation_account',
                    'finished_goods_account')

    def __init__(self, file_path):
        old_path=Path(file_path)
        migrating=old_path.exists() and old_path.stat().st_size>0
        super().__init__(file_path)
        with closing(self._connection()) as conn:
            prior=conn.execute('PRAGMA user_version').fetchone()[0]
            if migrating and prior<3:
                snapshot=self.path.with_suffix('.pre_v03.sqlite3')
                if not snapshot.exists():
                    with closing(sqlite3.connect(str(snapshot))) as dest:conn.backup(dest)
            # One transaction for schema creation and version marker.
            conn.executescript(Path(__file__).with_name('erp_schema.sql').read_text('utf-8'))
            conn.execute('PRAGMA user_version=3')
            conn.commit()

    def reference_choices(self, company_id, category):
        """Read-only, company-scoped ERP selector rows for the desktop UI."""
        tables = {
            'employees': 'erp_employees',
            'assets': 'erp_assets',
            'projects': 'erp_projects',
        }
        if category not in tables:
            raise AccountingError('نوع داده مرجع نامعتبر است.')
        with closing(self._connection()) as conn:
            return [dict(row) for row in conn.execute(
                'SELECT * FROM ' + tables[category] + ' WHERE company_id=? ORDER BY id',
                (company_id,))]

    @staticmethod
    def _row(conn, sql, args=()):
        return conn.execute(sql, args).fetchone()

    @staticmethod
    def _require(row, message):
        if row is None:
            raise AccountingError(message)
        return row

    @staticmethod
    def _positive(value, caption='مقدار'):
        if isinstance(value, bool) or not isinstance(value, int) or value<=0 or value>9_000_000_000_000_000:
            raise AccountingError(caption+' باید عدد صحیح مثبت در محدوده مجاز باشد.')
        return value

    @staticmethod
    def _nonnegative(value, caption='مبلغ'):
        if isinstance(value, bool) or not isinstance(value,int) or value<0 or value>9_000_000_000_000_000:
            raise AccountingError(caption+' باید عدد صحیح غیرمنفی باشد.')
        return value

    def _check_year(self, conn, company_id, year_id, jalali_date):
        day=parse_jalali(jalali_date).isoformat()
        year=self._require(self._row(conn,'SELECT * FROM fiscal_years WHERE company_id=? AND id=?',
                      (company_id,year_id)),'سال مالی نامعتبر است.')
        if year['is_closed'] or not (year['start_date']<=day<=year['end_date']):
            raise AccountingError('تاریخ باید در محدوده سال مالی باز باشد.')
        return day

    def _account(self, conn, company_id, ident):
        return self._require(self._row(conn,'SELECT * FROM accounts WHERE id=? AND company_id=? AND is_postable=1 AND is_active=1',
                             (ident,company_id)),'حساب معین‌شده باید تفصیلی فعال متعلق به همین شرکت باشد.')

    def _entity(self, conn, table, company_id, ident):
        if table not in ('parties','erp_cashboxes','erp_items','erp_employees',
                         'erp_assets','erp_warehouses','erp_projects'):
            raise AccountingError('نوع موجودیت نامعتبر است.')
        return self._require(self._row(conn,'SELECT * FROM '+table+' WHERE company_id=? AND id=?',
                                       (company_id,ident)),'موجودیت در شرکت انتخابی یافت نشد.')

    def _settings(self, conn, company_id, *needed):
        conf=self._require(self._row(conn,'SELECT * FROM erp_config WHERE company_id=?',(company_id,)),
                           'ابتدا نگاشت حساب‌های سیستمی را انجام دهید.')
        for key in needed:
            if key not in self.ACCOUNT_KEYS or conf[key] is None:
                raise AccountingError('حساب سیستمی «'+key+'» تعریف نشده است.')
            self._account(conn,company_id,conf[key])
        return conf

    @staticmethod
    def _line(account, debit=0, credit=0):
        return {'account_id':account,'debit':debit,'credit':credit}

    def _journal(self, conn, company_id, year_id, day, description, source, lines):
        if len(lines)<2:
            raise AccountingError('سند باید حداقل دو ردیف داشته باشد.')
        if sum(l.get('debit',0)-l.get('credit',0) for l in lines)!=0:
            raise AccountingError('سند خودکار تراز نیست.')
        for line in lines:self._account(conn,company_id,line['account_id'])
        serial=self._row(conn,'SELECT COALESCE(MAX(serial_no),0)+1 FROM journal_entries WHERE company_id=? AND fiscal_year_id=?',
                         (company_id,year_id))[0]
        cur=conn.execute('''INSERT INTO journal_entries(company_id,fiscal_year_id,serial_no,entry_date,description,
                            source_module,source_type,source_id) VALUES (?,?,?,?,?,?,?,?)''',
                         (company_id,year_id,serial,day,description,*source))
        self._insert_lines(conn,cur.lastrowid,lines)
        conn.execute("UPDATE journal_entries SET status='posted',posted_at=datetime('now') WHERE id=?",(cur.lastrowid,))
        self._audit(conn,company_id,'AUTO_POST','journal',cur.lastrowid,source[0] or '')
        return cur.lastrowid

    @staticmethod
    def _log(conn,company_id,action,kind,ident,detail=''):
        conn.execute('INSERT INTO erp_audit_log(company_id,action,entity_kind,entity_id,detail) VALUES (?,?,?,?,?)',
                     (company_id,action,kind,str(ident),detail))

    def configure(self, company_id, **accounts):
        if not accounts or not set(accounts).issubset(set(self.ACCOUNT_KEYS)):
            raise AccountingError('کلید نگاشت حساب نامعتبر است.')
        with self._write() as conn:
            self._require(self._row(conn,'SELECT id FROM companies WHERE id=?',(company_id,)), 'شرکت نامعتبر است.')
            for key,account in accounts.items():
                if account is not None:self._account(conn,company_id,account)
            conn.execute('INSERT OR IGNORE INTO erp_config(company_id) VALUES (?)',(company_id,))
            conn.execute('UPDATE erp_config SET '+','.join(k+'=?' for k in accounts)+' WHERE company_id=?',
                         list(accounts.values())+[company_id])
            self._log(conn,company_id,'CONFIG','erp_config',company_id,','.join(accounts.keys()))

    def config(self,company_id):
        return self._read_one('SELECT * FROM erp_config WHERE company_id=?',(company_id,)) or {}

    def reverse(self,company_id,original_id,jalali_day,explanation='سند برگشت'):
        entry=self._require(self._read_one('SELECT * FROM journal_entries WHERE company_id=? AND id=?',
                           (company_id,original_id)),'سند معتبر یافت نشد.')
        if entry['source_module'] is not None:
            raise AccountingError('برگشت مستقیم سند خودکار مجاز نیست؛ باید گردش زیرسیستم اصلاح شود. گردش برگشت زیرسیستم هنوز پیاده‌سازی نشده است.')
        return super().reverse(company_id,original_id,jalali_day,explanation)

    def create_party(self,company_id,code,name,kind='mixed'):
        if kind not in ('customer','supplier','employee','other','mixed') or not str(code).strip() or not str(name).strip():
            raise AccountingError('اطلاعات شخص نامعتبر است.')
        with self._write() as conn:
            cur=conn.execute('INSERT INTO parties(company_id,code,name,party_kind) VALUES (?,?,?,?)',
                             (company_id,str(code).strip(),str(name).strip(),kind))
            self._log(conn,company_id,'CREATE','party',cur.lastrowid)
        return cur.lastrowid

    def parties(self,company_id):
        return self._read_all('SELECT * FROM parties WHERE company_id=? ORDER BY code',(company_id,))

    def create_cashbox(self,company_id,name,kind,gl_account_id):
        if kind not in ('cash','bank','pos') or not str(name).strip():raise AccountingError('نوع یا نام صندوق/بانک نامعتبر است.')
        with self._write() as conn:
            self._account(conn,company_id,gl_account_id)
            cur=conn.execute('INSERT INTO erp_cashboxes(company_id,name,kind,gl_account_id) VALUES (?,?,?,?)',
                             (company_id,str(name).strip(),kind,gl_account_id))
            self._log(conn,company_id,'CREATE','cashbox',cur.lastrowid)
        return cur.lastrowid

    def cashboxes(self,company_id):return self._read_all('SELECT * FROM erp_cashboxes WHERE company_id=?',(company_id,))

    def cash_flow(self,company_id,year_id,date,cashbox_id,direction,amount,other_account,reference,party_id=None):
        self._positive(amount,'مبلغ دریافت/پرداخت')
        if direction not in ('receipt','payment') or not str(reference).strip():raise AccountingError('نوع عملیات یا شناسه مرجع نامعتبر است.')
        with self._write() as conn:
            day=self._check_year(conn,company_id,year_id,date)
            box=self._entity(conn,'erp_cashboxes',company_id,cashbox_id)
            self._account(conn,company_id,other_account)
            if party_id is not None:self._entity(conn,'parties',company_id,party_id)
            if box['gl_account_id']==other_account:raise AccountingError('حساب صندوق و طرف مقابل نمی‌تواند یکی باشد.')
            source=('treasury',direction,str(reference))
            lines=([self._line(box['gl_account_id'],debit=amount),self._line(other_account,credit=amount)]
                   if direction=='receipt' else
                   [self._line(other_account,debit=amount),self._line(box['gl_account_id'],credit=amount)])
            journal=self._journal(conn,company_id,year_id,day,direction+' '+str(reference),source,lines)
            cur=conn.execute('''INSERT INTO erp_cash_flows(company_id,fiscal_year_id,cashbox_id,direction,amount_rial,
                    other_account_id,party_id,movement_date,reference,entry_id) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (company_id,year_id,cashbox_id,direction,amount,other_account,party_id,day,str(reference),journal))
            self._log(conn,company_id,'POST','cash_flow',cur.lastrowid)
        return cur.lastrowid

    def register_check(self,company_id,number,bank,due_date,amount,direction,party_id=None):
        self._positive(amount)
        if direction not in ('received','issued') or not number or not bank:raise AccountingError('اطلاعات چک نامعتبر است.')
        day=parse_jalali(due_date).isoformat()
        with self._write() as conn:
            if party_id is not None:self._entity(conn,'parties',company_id,party_id)
            cur=conn.execute('INSERT INTO erp_checks(company_id,number,bank_name,due_date,amount_rial,direction,party_id) VALUES (?,?,?,?,?,?,?)',
                             (company_id,str(number),str(bank),day,amount,direction,party_id))
            self._log(conn,company_id,'REGISTER','check',cur.lastrowid)
        return cur.lastrowid

    def update_check_status(self,company_id,check_id,status):
        if status not in ('cleared','returned','void'):raise AccountingError('وضعیت چک نامعتبر است.')
        with self._write() as conn:
            check=self._require(self._row(conn,'SELECT * FROM erp_checks WHERE id=? AND company_id=?',
                                         (check_id,company_id)),'چک موجود نیست.')
            if check['status']!='registered':raise AccountingError('وضعیت چک قبلاً نهایی شده است.')
            conn.execute('UPDATE erp_checks SET status=? WHERE id=?',(status,check_id))
            self._log(conn,company_id,'STATUS','check',check_id,status)
        # This registry does NOT post a clearing journal; cash flow is separate.

    def create_warehouse(self,company_id,name):
        if not str(name).strip():raise AccountingError('نام انبار الزامی است.')
        with self._write() as conn:
            cur=conn.execute('INSERT INTO erp_warehouses(company_id,name) VALUES (?,?)',(company_id,str(name).strip()))
            self._log(conn,company_id,'CREATE','warehouse',cur.lastrowid)
        return cur.lastrowid

    def warehouses(self,company_id):return self._read_all('SELECT * FROM erp_warehouses WHERE company_id=?',(company_id,))

    def create_item(self,company_id,code,title,kind='good'):
        if kind not in ('good','service') or not str(code).strip() or not str(title).strip():
            raise AccountingError('اطلاعات کالا/خدمت نامعتبر است.')
        with self._write() as conn:
            cur=conn.execute('INSERT INTO erp_items(company_id,code,title,kind) VALUES (?,?,?,?)',
                             (company_id,str(code).strip(),str(title).strip(),kind))
            self._log(conn,company_id,'CREATE','item',cur.lastrowid)
        return cur.lastrowid

    def items(self,company_id):return self._read_all('SELECT * FROM erp_items WHERE company_id=? ORDER BY code',(company_id,))

    @staticmethod
    def _stock_qty(conn,company_id,warehouse_id,item_id):
        return conn.execute('''SELECT COALESCE(SUM(qty_change),0) FROM erp_stock_movements
                               WHERE company_id=? AND warehouse_id=? AND item_id=?''',
                            (company_id,warehouse_id,item_id)).fetchone()[0]

    def _apply_stock(self,conn,company_id,item_id,warehouse_id,qty_delta,value_delta,source_kind,source_id):
        item=self._entity(conn,'erp_items',company_id,item_id)
        self._entity(conn,'erp_warehouses',company_id,warehouse_id)
        if item['kind']!='good':raise AccountingError('خدمت موجودی انبار ندارد.')
        if item['qty']+qty_delta<0 or item['value_rial']+value_delta<0:
            raise AccountingError('موجودی یا ارزش ریالی کالا منفی می‌شود.')
        if self._stock_qty(conn,company_id,warehouse_id,item_id)+qty_delta<0:
            raise AccountingError('موجودی انبار انتخابی کافی نیست.')
        conn.execute('UPDATE erp_items SET qty=qty+?,value_rial=value_rial+? WHERE id=?',(qty_delta,value_delta,item_id))
        conn.execute('''INSERT INTO erp_stock_movements(company_id,item_id,warehouse_id,qty_change,value_change_rial,source_kind,source_id)
                        VALUES (?,?,?,?,?,?,?)''',(company_id,item_id,warehouse_id,qty_delta,value_delta,source_kind,source_id))

    def stock_report(self,company_id):
        return self._read_all('SELECT code,title,kind,qty,value_rial FROM erp_items WHERE company_id=? ORDER BY code',(company_id,))

    def invoice(self,company_id,year_id,date,direction,reference,party_id,warehouse_id,lines):
        """lines=[{item_id,qty,unit_price_rial,tax_rate_bps}] (tax rate is caller input, not prescribed rate)."""
        if direction not in ('sale','purchase') or not str(reference).strip() or not lines:
            raise AccountingError('نوع، مرجع یا ردیف‌های فاکتور نامعتبر است.')
        if len(lines)>500:raise AccountingError('حداکثر ۵۰۰ ردیف مجاز است.')
        with self._write() as conn:
            day=self._check_year(conn,company_id,year_id,date)
            self._entity(conn,'parties',company_id,party_id)
            if warehouse_id is not None:self._entity(conn,'erp_warehouses',company_id,warehouse_id)
            keys=(('inventory_account','cogs_account','payable_account','vat_input_account') if direction=='purchase' else
                  ('inventory_account','cogs_account','receivable_account','sales_account','vat_output_account'))
            conf=self._settings(conn,company_id,*keys)
            details=[];subtotal=0;tax=0;cost=0
            grouped={}
            for line in lines:
                item=self._entity(conn,'erp_items',company_id,int(line['item_id']))
                qty=self._positive(line['qty'],'تعداد')
                unit=self._nonnegative(line['unit_price_rial'],'قیمت واحد')
                rate=line.get('tax_rate_bps',0)
                if not isinstance(rate,int) or isinstance(rate,bool) or not 0<=rate<=10000:
                    raise AccountingError('نرخ مالیات باید عدد صحیح در واحد یک‌صدم درصد باشد.')
                if item['kind']=='good' and warehouse_id is None:raise AccountingError('کالا باید انبار داشته باشد.')
                value=qty*unit
                if value>9_000_000_000_000_000:raise AccountingError('مبلغ ردیف خارج از محدوده است.')
                vat=(value*rate+5000)//10000
                details.append([item,qty,unit,rate,vat,0]);subtotal+=value;tax+=vat
                if item['kind']=='good':grouped[item['id']]=grouped.get(item['id'],0)+qty
            if direction=='sale':
                for item_id,needed in grouped.items():
                    item=self._entity(conn,'erp_items',company_id,item_id)
                    if item['qty']<needed or self._stock_qty(conn,company_id,warehouse_id,item_id)<needed:
                        raise AccountingError('موجودی کالا کافی نیست.')
                for detail in details:
                    item,qty,unit,rate,vat,_=detail
                    if item['kind']=='good':
                        # Deterministic total weighted-average, integral rial rounding.
                        available=item['qty']; total_value=item['value_rial']
                                # Each invoice line uses snapshot avg; aggregate reconciliation on final line below.
                        detail[5]=(qty*total_value+available//2)//available
                        cost+=detail[5]
                # Ensure total line cost never exceeds stock value for grouped quantities.
                for item_id,needed in grouped.items():
                    item=self._entity(conn,'erp_items',company_id,item_id)
                    ids=[i for i,d in enumerate(details) if d[0]['id']==item_id]
                    desired=(needed*item['value_rial']+item['qty']//2)//item['qty']
                    if needed==item['qty']:desired=item['value_rial']
                    prior=sum(details[i][5] for i in ids)
                    details[ids[-1]][5]+=desired-prior
                    cost+=desired-prior
            total=subtotal+tax
            if total<=0:raise AccountingError('جمع فاکتور باید مثبت باشد.')
            stock_value=sum(d[1]*d[2] for d in details if d[0]['kind']=='good')
            services_value=subtotal-stock_value
            if direction=='purchase':
                gl=[self._line(conf['payable_account'],credit=total)]
                if stock_value:gl.append(self._line(conf['inventory_account'],debit=stock_value))
                if services_value:gl.append(self._line(conf['cogs_account'],debit=services_value))
                if tax:gl.append(self._line(conf['vat_input_account'],debit=tax))
            else:
                gl=[self._line(conf['receivable_account'],debit=total),
                    self._line(conf['sales_account'],credit=subtotal)]
                if tax:gl.append(self._line(conf['vat_output_account'],credit=tax))
                if cost:
                    gl.extend([self._line(conf['cogs_account'],debit=cost),
                               self._line(conf['inventory_account'],credit=cost)])
            # SQLite posting checks are executed prior to business rows: same write transaction.
            journal=self._journal(conn,company_id,year_id,day,'فاکتور '+str(reference),
                                  ('trade',direction,str(reference)),gl)
            cur=conn.execute('''INSERT INTO erp_invoices(company_id,year_id,direction,external_ref,invoice_date,party_id,
                         warehouse_id,subtotal_rial,tax_rial,total_rial,entry_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                         (company_id,year_id,direction,str(reference),day,party_id,warehouse_id,subtotal,tax,total,journal))
            invoice_id=cur.lastrowid
            for item,qty,unit,rate,vat,line_cost in details:
                conn.execute('INSERT INTO erp_invoice_lines(invoice_id,item_id,qty,unit_price_rial,tax_rate_bps,tax_rial,cost_rial) VALUES (?,?,?,?,?,?,?)',
                             (invoice_id,item['id'],qty,unit,rate,vat,line_cost))
                if item['kind']=='good':
                    change=qty if direction=='purchase' else -qty
                    value=qty*unit if direction=='purchase' else -line_cost
                    self._apply_stock(conn,company_id,item['id'],warehouse_id,change,value,'invoice',invoice_id)
            if direction=='sale':
                payload={'format':'Saba-local-preview-v1','invoice_id':invoice_id,'date':day,'party_id':party_id,
                         'subtotal_rial':subtotal,'vat_rial':tax,'total_rial':total,'source':'local-not-tax-authority'}
                conn.execute('INSERT INTO erp_tax_outbox(company_id,invoice_id,payload_json) VALUES (?,?,?)',
                             (company_id,invoice_id,json.dumps(payload,ensure_ascii=False)))
            self._log(conn,company_id,'POST','invoice',invoice_id,direction)
        return invoice_id

    def invoices(self,company_id):
        return self._read_all('SELECT * FROM erp_invoices WHERE company_id=? ORDER BY id DESC',(company_id,))

    def tax_export(self,company_id,path):
        """Local inventory of invoices; expressly NOT official tax API payload or authenticated submission."""
        rows=self._read_all('''SELECT t.id,i.external_ref,i.invoice_date,i.total_rial,t.state
                    FROM erp_tax_outbox t JOIN erp_invoices i ON i.id=t.invoice_id
                    WHERE t.company_id=? ORDER BY t.id''',(company_id,))
        with open(path,'w',encoding='utf-8-sig',newline='') as fh:
            writer=csv.writer(fh);writer.writerow(['شناسه محلی','شماره فاکتور','تاریخ میلادی','جمع ریال','وضعیت داخلی (ارسال‌نشده)'])
            for r in rows:writer.writerow([r['id'],r['external_ref'],r['invoice_date'],r['total_rial'],r['state']])
        return len(rows)

    def create_employee(self,company_id,code,name):
        if not str(code).strip() or not str(name).strip():raise AccountingError('کد یا نام پرسنل نامعتبر است.')
        with self._write() as conn:
            cur=conn.execute('INSERT INTO erp_employees(company_id,personnel_code,name) VALUES (?,?,?)',
                             (company_id,str(code).strip(),str(name).strip()))
            self._log(conn,company_id,'CREATE','employee',cur.lastrowid)
        return cur.lastrowid

    def payroll(self,company_id,year_id,date,employee_id,period,gross,deductions):
        self._positive(gross,'حقوق ناخالص');self._nonnegative(deductions,'کسورات')
        if deductions>gross:raise AccountingError('کسورات بیشتر از ناخالص است.')
        if not str(period).strip():raise AccountingError('دوره حقوق لازم است.')
        with self._write() as conn:
            day=self._check_year(conn,company_id,year_id,date)
            self._entity(conn,'erp_employees',company_id,employee_id)
            conf=self._settings(conn,company_id,'payroll_expense_account','payroll_payable_account')
            if gross==deductions:raise AccountingError('حقوق خالص باید مثبت باشد.')
            lines=[self._line(conf['payroll_expense_account'],debit=gross),
                   self._line(conf['payroll_payable_account'],credit=gross-deductions)]
            if deductions:
                withheld=self._settings(conn,company_id,'payroll_deduction_account')['payroll_deduction_account']
                lines.append(self._line(withheld,credit=deductions))
            journal=self._journal(conn,company_id,year_id,day,'حقوق '+str(period)+' '+str(employee_id),
                                  ('payroll','payroll',str(employee_id)+':'+str(period)),lines)
            cur=conn.execute('''INSERT INTO erp_payroll(company_id,employee_id,period,gross_rial,deduction_rial,net_rial,entry_id)
                                VALUES (?,?,?,?,?,?,?)''',(company_id,employee_id,str(period),gross,deductions,gross-deductions,journal))
            self._log(conn,company_id,'POST','payroll',cur.lastrowid)
        return cur.lastrowid

    def create_asset(self,company_id,code,title,cost,salvage,life_months):
        self._positive(cost);self._nonnegative(salvage)
        self._positive(life_months,'عمر مفید')
        if salvage>=cost or life_months>1200 or not code or not title:raise AccountingError('مشخصات دارایی نامعتبر است.')
        with self._write() as conn:
            cur=conn.execute('''INSERT INTO erp_assets(company_id,code,title,cost_rial,salvage_rial,life_months)
                  VALUES (?,?,?,?,?,?)''',(company_id,str(code),str(title),cost,salvage,life_months))
            self._log(conn,company_id,'CREATE','asset',cur.lastrowid)
        return cur.lastrowid

    def depreciate(self,company_id,year_id,date,asset_id,period):
        with self._write() as conn:
            day=self._check_year(conn,company_id,year_id,date)
            a=self._entity(conn,'erp_assets',company_id,asset_id)
            conf=self._settings(conn,company_id,'depreciation_expense_account','accumulated_depreciation_account')
            if a['months_posted']>=a['life_months']:raise AccountingError('استهلاک دارایی تکمیل شده است.')
            base=a['cost_rial']-a['salvage_rial']
            amount=((a['months_posted']+1)*base)//a['life_months']-a['depreciated_rial']
            if amount<=0:raise AccountingError('استهلاک این ماه کمتر از یک ریال است.')
            lines=[self._line(conf['depreciation_expense_account'],debit=amount),
                   self._line(conf['accumulated_depreciation_account'],credit=amount)]
            j=self._journal(conn,company_id,year_id,day,'استهلاک '+a['title']+' '+str(period),
                            ('assets','depreciation',str(asset_id)+':'+str(period)),lines)
            cur=conn.execute('INSERT INTO erp_depreciation(asset_id,period,expense_rial,entry_id) VALUES (?,?,?,?)',
                             (asset_id,str(period),amount,j))
            conn.execute('UPDATE erp_assets SET months_posted=months_posted+1,depreciated_rial=depreciated_rial+? WHERE id=?',
                         (amount,asset_id))
            self._log(conn,company_id,'POST','depreciation',cur.lastrowid)
        return cur.lastrowid

    def bom_add(self,company_id,finished_item,material_item,quantity):
        self._positive(quantity,'مقدار مواد')
        if finished_item==material_item:raise AccountingError('مصرف خود کالا در فرمول مجاز نیست.')
        with self._write() as conn:
            for ident in (finished_item,material_item):
                item=self._entity(conn,'erp_items',company_id,ident)
                if item['kind']!='good':raise AccountingError('فرمول ساخت فقط برای کالا است.')
            cur=conn.execute('INSERT INTO erp_boms(company_id,finished_item_id,material_item_id,material_qty) VALUES (?,?,?,?)',
                             (company_id,finished_item,material_item,quantity))
            self._log(conn,company_id,'CREATE','bom',cur.lastrowid)
        return cur.lastrowid

    def produce(self,company_id,year_id,date,finished_item,quantity,warehouse_id,reference):
        self._positive(quantity)
        if not reference:raise AccountingError('مرجع تولید لازم است.')
        with self._write() as conn:
            day=self._check_year(conn,company_id,year_id,date)
            finished=self._entity(conn,'erp_items',company_id,finished_item)
            self._entity(conn,'erp_warehouses',company_id,warehouse_id)
            if finished['kind']!='good':raise AccountingError('خروجی تولید باید کالا باشد.')
            conf=self._settings(conn,company_id,'inventory_account')
            bom=conn.execute('SELECT * FROM erp_boms WHERE company_id=? AND finished_item_id=?',(company_id,finished_item)).fetchall()
            if not bom:raise AccountingError('فرمول تولید تعریف نشده است.')
            total=0;inputs=[]
            for b in bom:
                source=self._entity(conn,'erp_items',company_id,b['material_item_id'])
                needed=b['material_qty']*quantity
                if needed>source['qty'] or needed>self._stock_qty(conn,company_id,warehouse_id,source['id']):
                    raise AccountingError('موجودی مواد اولیه کافی نیست.')
                val=(needed*source['value_rial']+source['qty']//2)//source['qty']
                if needed==source['qty']:val=source['value_rial']
                if val<=0:raise AccountingError('مواد اولیه ارزش ریالی مثبت ندارند.')
                total+=val;inputs.append((source['id'],needed,val))
            # At this prototype stage all warehouse valuation uses a single GL inventory account.
            # The production entry nets to zero in GL; stock movements carry the cost transfer.
            gl=[self._line(conf['inventory_account'],debit=total),
                self._line(conf['inventory_account'],credit=total)]
            j=self._journal(conn,company_id,year_id,day,'تولید '+str(reference),('production','order',str(reference)),gl)
            cur=conn.execute('INSERT INTO erp_production(company_id,finished_item_id,quantity,cost_rial,external_ref,entry_id) VALUES (?,?,?,?,?,?)',
                             (company_id,finished_item,quantity,total,str(reference),j))
            order=cur.lastrowid
            for item_id,needed,val in inputs:self._apply_stock(conn,company_id,item_id,warehouse_id,-needed,-val,'production',order)
            self._apply_stock(conn,company_id,finished_item,warehouse_id,quantity,total,'production',order)
            self._log(conn,company_id,'POST','production',order)
        return order

    def create_project(self,company_id,code,title,budget):
        self._nonnegative(budget)
        if not str(code).strip() or not str(title).strip():raise AccountingError('کد/عنوان پروژه الزامی است.')
        with self._write() as conn:
            cur=conn.execute('INSERT INTO erp_projects(company_id,code,title,budget_rial) VALUES (?,?,?,?)',
                             (company_id,str(code),str(title),budget))
            self._log(conn,company_id,'CREATE','project',cur.lastrowid)
        return cur.lastrowid

    def project_cost(self,company_id,year_id,date,project_id,amount,expense_account,credit_account):
        self._positive(amount)
        with self._write() as conn:
            day=self._check_year(conn,company_id,year_id,date)
            self._entity(conn,'erp_projects',company_id,project_id)
            self._account(conn,company_id,expense_account);self._account(conn,company_id,credit_account)
            if expense_account==credit_account:raise AccountingError('حساب‌های بدهکار و بستانکار یکسان هستند.')
            # No contract progress recognition, withholding or certified statements yet.
            ref='project-'+str(project_id)+'-'+str(self._row(conn,'SELECT COALESCE(MAX(id),0)+1 FROM erp_project_costs')[0])
            j=self._journal(conn,company_id,year_id,day,'هزینه پروژه '+str(project_id),('projects','cost',ref),
                            [self._line(expense_account,debit=amount),self._line(credit_account,credit=amount)])
            cur=conn.execute('INSERT INTO erp_project_costs(company_id,project_id,amount_rial,entry_id) VALUES (?,?,?,?)',
                             (company_id,project_id,amount,j))
            self._log(conn,company_id,'POST','project_cost',cur.lastrowid)
        return cur.lastrowid

    def set_budget(self,company_id,year_id,account_id,amount):
        self._nonnegative(amount)
        with self._write() as conn:
            self._require(self._row(conn,'SELECT id FROM fiscal_years WHERE id=? AND company_id=?',(year_id,company_id)),
                          'سال مالی نامعتبر است.')
            self._account(conn,company_id,account_id)
            conn.execute('''INSERT INTO erp_budgets(company_id,year_id,account_id,amount_rial) VALUES (?,?,?,?)
                            ON CONFLICT(company_id,year_id,account_id) DO UPDATE SET amount_rial=excluded.amount_rial''',
                         (company_id,year_id,account_id,amount))
            self._log(conn,company_id,'SET','budget',account_id,str(amount))

    def budgets(self,company_id,year_id):
        return self._read_all('''SELECT b.*,a.code,a.title FROM erp_budgets b JOIN accounts a ON a.id=b.account_id
                          WHERE b.company_id=? AND b.year_id=? ORDER BY a.code''',(company_id,year_id))

    def overview(self,company_id):
        tables={'cash_flows':'erp_cash_flows','checks':'erp_checks','items':'erp_items','invoices':'erp_invoices',
                'employees':'erp_employees','payroll':'erp_payroll','assets':'erp_assets','depreciation':'erp_depreciation',
                'production':'erp_production','projects':'erp_projects','tax_outbox':'erp_tax_outbox'}
        result={}
        with closing(self._connection()) as conn:
            for key,table in tables.items():
                if table=='erp_depreciation':
                    q='SELECT COUNT(*) FROM erp_depreciation d JOIN erp_assets a ON a.id=d.asset_id WHERE a.company_id=?'
                else:q='SELECT COUNT(*) FROM '+table+' WHERE company_id=?'
                result[key]=conn.execute(q,(company_id,)).fetchone()[0]
        return result

    def integrity_report(self, company_id):
        """Read-only reconciliation of transactional state; does not certify statutory compliance."""
        self._require(self._read_one('SELECT id FROM companies WHERE id=?',(company_id,)),'شرکت معتبر نیست.')
        with closing(self._connection()) as conn:
            sqlite_ok=conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            foreign_key_issues=len(conn.execute('PRAGMA foreign_key_check').fetchall())
            issues=[]
            for item in conn.execute('SELECT id,code,qty,value_rial FROM erp_items WHERE company_id=?',(company_id,)):
                qty,value=conn.execute('''SELECT COALESCE(SUM(qty_change),0),COALESCE(SUM(value_change_rial),0)
                        FROM erp_stock_movements WHERE company_id=? AND item_id=?''',(company_id,item['id'])).fetchone()
                if qty!=item['qty'] or value!=item['value_rial']:
                    issues.append('Item stock mismatch '+item['code'])
            for row in conn.execute('''SELECT j.id,COALESCE(SUM(l.debit_rial-l.credit_rial),0) balance
                      FROM journal_entries j LEFT JOIN journal_lines l ON l.entry_id=j.id
                      WHERE j.company_id=? AND j.status='posted' GROUP BY j.id''',(company_id,)):
                if row['balance']!=0:issues.append('Unbalanced journal '+str(row['id']))
            # Documents posted through ERP must still resolve to posted journals for the same company.
            for table,column in [('erp_cash_flows','entry_id'),('erp_invoices','entry_id'),
                                 ('erp_payroll','entry_id'),('erp_production','entry_id'),
                                 ('erp_project_costs','entry_id')]:
                invalid=conn.execute('''SELECT COUNT(*) FROM '''+table+''' d LEFT JOIN journal_entries j
                          ON j.id=d.entry_id AND j.company_id=d.company_id
                          WHERE d.company_id=? AND (j.id IS NULL OR j.status!='posted')''',(company_id,)).fetchone()[0]
                if invalid:issues.append(table+' has '+str(invalid)+' unposted/mis-scoped journals')
            invalid=conn.execute('''SELECT COUNT(*) FROM erp_depreciation d JOIN erp_assets a ON a.id=d.asset_id
                LEFT JOIN journal_entries j ON j.id=d.entry_id AND j.company_id=a.company_id
                WHERE a.company_id=? AND (j.id IS NULL OR j.status!='posted')''',(company_id,)).fetchone()[0]
            if invalid:issues.append('erp_depreciation has '+str(invalid)+' unposted journals')
        return {'sqlite_integrity_ok':sqlite_ok,'foreign_key_issues':foreign_key_issues,
                'business_issues':issues,'ok':sqlite_ok and foreign_key_issues==0 and not issues}
