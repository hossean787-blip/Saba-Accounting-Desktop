"""Independent v0.4 finance core. Integer rials; SQLite atomic year-end.

This code is not a legal certification, and is NOT copied from third-party binaries.
"""
from collections import defaultdict
from contextlib import closing
from datetime import date, timedelta
from html import escape as html_escape
from pathlib import Path
import csv
import sqlite3
import hashlib
import json
import os
import tempfile

from .erp import ERPStore
from .storage import AccountingError
from .jalali import parse_jalali, display_jalali

NOMINAL = {'revenue', 'expense', 'cost'}
PERMANENT = {'asset', 'liability', 'equity'}
MAX_RIAL = 9_000_000_000_000_000

class FinanceStore(ERPStore):
    def __init__(self, file_path):
        # Capture the source DB BEFORE the additive v0.4 migration, including v0.3 migrations.
        source = Path(file_path)
        exists = source.exists() and source.stat().st_size > 0
        if exists:
            with closing(sqlite3.connect(str(source))) as old:
                is_v4 = any(row[1] == 'entry_kind' for row in old.execute('PRAGMA table_info(journal_entries)'))
                if not is_v4:
                    snap = source.with_suffix('.pre_v04.sqlite3')
                    if not snap.exists():
                        with closing(sqlite3.connect(str(snap))) as dest: old.backup(dest)
        super().__init__(file_path)
        with closing(self._connection()) as conn:
            cols = {row['name'] for row in conn.execute('PRAGMA table_info(journal_entries)')}
            if 'entry_kind' not in cols:
                conn.execute("ALTER TABLE journal_entries ADD COLUMN entry_kind TEXT NOT NULL DEFAULT 'regular'")
            if 'correction_of_id' not in cols:
                conn.execute('ALTER TABLE journal_entries ADD COLUMN correction_of_id INTEGER REFERENCES journal_entries(id)')
            line_cols={row['name'] for row in conn.execute('PRAGMA table_info(journal_lines)')}
            if 'detail_id' not in line_cols:
                conn.execute('ALTER TABLE journal_lines ADD COLUMN detail_id INTEGER REFERENCES floating_details(id)')
            conn.executescript(Path(__file__).with_name('finance_schema.sql').read_text(encoding='utf-8'))
            conn.execute('PRAGMA user_version=4')
            conn.commit()

    def add_floating_detail(self, company_id, code, title, detail_type='other'):
        if detail_type not in ('person','project','bank','contract','employee','asset','other'):
            raise AccountingError('نوع تفصیلی شناور نامعتبر است.')
        if not str(code).strip() or not str(title).strip():
            raise AccountingError('کد و عنوان تفصیلی الزامی است.')
        with self._write() as conn:
            self._company(conn, company_id)
            cur=conn.execute('INSERT INTO floating_details(company_id,code,title,detail_type) VALUES (?,?,?,?)',
                             (company_id,str(code).strip(),str(title).strip(),detail_type))
            self._audit(conn,company_id,'CREATE','floating_detail',cur.lastrowid)
            return cur.lastrowid

    @staticmethod
    def _company(conn, company_id):
        if not conn.execute('SELECT 1 FROM companies WHERE id=?',(company_id,)).fetchone():
            raise AccountingError('شرکت معتبر پیدا نشد.')

    def floating_details(self, company_id):
        return self._read_all('SELECT * FROM floating_details WHERE company_id=? ORDER BY code',(company_id,))

    def require_floating_detail(self, company_id, account_id, required=True):
        with self._write() as conn:
            account=conn.execute('SELECT * FROM accounts WHERE company_id=? AND id=? AND is_postable=1',
                                 (company_id,account_id)).fetchone()
            if not account: raise AccountingError('حساب تفصیلی معتبر لازم است.')
            # Rule can be changed only before the first journal row has been recorded.
            if conn.execute('SELECT 1 FROM journal_lines WHERE account_id=? LIMIT 1',(account_id,)).fetchone():
                raise AccountingError('تغییر الزام تفصیلی برای حساب دارای گردش، به مهاجرت کنترل‌شده نیاز دارد.')
            conn.execute('INSERT INTO account_detail_rules(account_id,required) VALUES (?,?) '
                         'ON CONFLICT(account_id) DO UPDATE SET required=excluded.required',
                         (account_id,int(bool(required))))
            self._audit(conn,company_id,'CONFIG','account_detail_rule',account_id,str(bool(required)))

    def reverse(self,company_id,original_id,jalali_day,explanation='سند برگشت'):
        """Dimension-preserving and atomic reversal of an ordinary manual journal."""
        when=parse_jalali(jalali_day).isoformat()
        with self._write() as conn:
            original=conn.execute("SELECT * FROM journal_entries WHERE company_id=? AND id=? AND status='posted'",
                                  (company_id,original_id)).fetchone()
            if not original or original['entry_kind']!='regular' or original['source_module'] is not None:
                raise AccountingError('برگشت مستقیم سند سیستمی، اصلاحی یا افتتاحیه/اختتامیه مجاز نیست.')
            year=conn.execute('SELECT * FROM fiscal_years WHERE id=?',(original['fiscal_year_id'],)).fetchone()
            if year['is_closed'] or not (year['start_date']<=when<=year['end_date']):
                raise AccountingError('تاریخ برگشت باید در سال مالی باز همان سند باشد.')
            if conn.execute('SELECT 1 FROM journal_entries WHERE reversal_of_id=?',(original_id,)).fetchone():
                raise AccountingError('سند از قبل برگشت خورده است.')
            lines=conn.execute('SELECT * FROM journal_lines WHERE entry_id=? ORDER BY row_no',(original_id,)).fetchall()
            return self._insert_kind(conn,company_id,year['id'],when,explanation,
                                     [self._swap_line(x) for x in lines],
                                     'adjustment',reversal_of_id=original_id)

    def create_adjustment(self,company_id,year_id,jalali_day,reason,lines):
        if len(str(reason).strip()) < 5 or len(lines)<2:
            raise AccountingError('شرح اصلاح باید حداقل پنج حرف و حداقل دو ردیف داشته باشد.')
        when=parse_jalali(jalali_day).isoformat()
        with self._write() as conn:
            year=conn.execute('SELECT * FROM fiscal_years WHERE id=? AND company_id=?',(year_id,company_id)).fetchone()
            if not year or year['is_closed'] or not(year['start_date']<=when<=year['end_date']):
                raise AccountingError('تاریخ اصلاح خارج از سال مالی باز است.')
            ident=self._insert_kind(conn,company_id,year_id,when,reason,lines,'adjustment')
            self._audit(conn,company_id,'ADJUST','journal',ident,reason)
            return ident

    def correct_posted(self,company_id,original_id,jalali_day,reason,new_lines):
        """Atomically reverse and reissue a manual journal, preserving original.
        Both reversal and replacement post or neither does. No direct ERP corrections.
        """
        if len(str(reason).strip())<5 or len(new_lines)<2:
            raise AccountingError('شرح اصلاح و حداقل دو ردیف لازم است.')
        when=parse_jalali(jalali_day).isoformat()
        with self._write() as conn:
            orig=conn.execute("SELECT * FROM journal_entries WHERE id=? AND company_id=? AND status='posted'",
                              (original_id,company_id)).fetchone()
            if not orig or orig['source_module'] is not None or orig['entry_kind']!='regular':
                raise AccountingError('فقط اسناد دستی عادی قابل اصلاح هم‌زمان هستند.')
            fy=conn.execute('SELECT * FROM fiscal_years WHERE id=?',(orig['fiscal_year_id'],)).fetchone()
            if fy['is_closed'] or not(fy['start_date']<=when<=fy['end_date']):
                raise AccountingError('اصلاح باید در سال مالی باز و در محدوده تاریخ آن باشد.')
            if conn.execute('SELECT 1 FROM journal_entries WHERE reversal_of_id=?',(original_id,)).fetchone():
                raise AccountingError('برای این سند قبلاً برگشت ثبت شده است.')
            lines=conn.execute('SELECT * FROM journal_lines WHERE entry_id=? ORDER BY row_no',(original_id,)).fetchall()
            undo=[self._swap_line(x) for x in lines]
            rev=self._insert_kind(conn,company_id,fy['id'],when,'برگشت اصلاحی: '+reason,undo,'adjustment',reversal_of_id=original_id)
            edited=self._insert_kind(conn,company_id,fy['id'],when,'سند اصلاح‌شده: '+reason,new_lines,'adjustment',correction_of_id=original_id)
            self._audit(conn,company_id,'CORRECT','journal',edited,'original={},reversal={}'.format(original_id,rev))
            return {'reversal_id':rev,'corrected_id':edited}

    @staticmethod
    def _swap_line(row):
        return {'account_id':row['account_id'],'debit':row['credit_rial'],'credit':row['debit_rial'],
                'narration':row['narration'],'detail_id':row['detail_id'],
                'party_id':row['party_id'],'cost_center_id':row['cost_center_id']}

    def _insert_kind(self,conn,company_id,year_id,day,description,lines,kind,reversal_of_id=None,correction_of_id=None):
        serial=conn.execute('SELECT COALESCE(MAX(serial_no),0)+1 FROM journal_entries WHERE company_id=? AND fiscal_year_id=?',
                            (company_id,year_id)).fetchone()[0]
        cur=conn.execute('''INSERT INTO journal_entries(company_id,fiscal_year_id,serial_no,entry_date,description,entry_kind,reversal_of_id,correction_of_id)
                          VALUES (?,?,?,?,?,?,?,?)''',
                         (company_id,year_id,serial,day,description,kind,reversal_of_id,correction_of_id))
        ident=cur.lastrowid
        self._insert_lines(conn,ident,lines)
        conn.execute("UPDATE journal_entries SET status='posted',posted_at=datetime('now') WHERE id=?",(ident,))
        self._audit(conn,company_id,'POST_'+kind.upper(),'journal',ident)
        return ident

    @staticmethod
    def _classes(conn,company_id):
        chart={a['id']:dict(a) for a in conn.execute('SELECT * FROM accounts WHERE company_id=?',(company_id,))}
        classes={}
        for a in chart.values():
            if not a['is_postable']:continue
            root=a
            visited=set()
            while root['parent_id'] is not None:
                if root['id'] in visited:raise AccountingError('چرخه در ساختار کدینگ شناسایی شد.')
                visited.add(root['id'])
                root=chart.get(root['parent_id'])
                if root is None: raise AccountingError('حساب والد نامعتبر است.')
            classes[a['id']]=root['account_class']
        return classes

    @staticmethod
    def _balances(conn,company_id,year_id,kinds=('regular','adjustment','opening')):
        qs=','.join('?' for _ in kinds)
        return [dict(x) for x in conn.execute('''SELECT l.account_id,l.detail_id,l.party_id,l.cost_center_id,
          SUM(l.debit_rial-l.credit_rial) AS balance
          FROM journal_lines l JOIN journal_entries j ON j.id=l.entry_id
          WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted' AND j.entry_kind IN ('''+qs+''')
          GROUP BY l.account_id,l.detail_id,l.party_id,l.cost_center_id
          HAVING SUM(l.debit_rial-l.credit_rial)!=0''',(company_id,year_id,*kinds))]

    @staticmethod
    def _make_line(r,reverse=False):
        amount= -r['balance'] if reverse else r['balance']
        if abs(amount)>MAX_RIAL: raise AccountingError('گردش حساب از حد پشتیبانی‌شده فراتر است.')
        return {'account_id':r['account_id'],'detail_id':r['detail_id'],
                'party_id':r['party_id'],'cost_center_id':r['cost_center_id'],
                'debit':max(amount,0),'credit':max(-amount,0)}

    def _plan_close(self,conn,company_id,year_id,next_year_id,retained_account_id):
        fy=conn.execute('SELECT * FROM fiscal_years WHERE id=? AND company_id=?',(year_id,company_id)).fetchone()
        next_fy=conn.execute('SELECT * FROM fiscal_years WHERE id=? AND company_id=?',(next_year_id,company_id)).fetchone()
        if not fy or not next_fy or year_id==next_year_id:
            raise AccountingError('دو سال مالی معتبر و متفاوت از یک شرکت لازم است.')
        if fy['is_closed'] or next_fy['is_closed'] or conn.execute('SELECT 1 FROM fiscal_closures WHERE fiscal_year_id=?',(year_id,)).fetchone():
            raise AccountingError('سال مالی قبلاً بسته شده یا سال بعد بسته است.')
        if date.fromisoformat(fy['end_date'])+timedelta(days=1)!=date.fromisoformat(next_fy['start_date']):
            raise AccountingError('سال بعد باید دقیقاً از روز پس از پایان سال جاری شروع شود.')
        if conn.execute('SELECT 1 FROM journal_entries WHERE fiscal_year_id=? LIMIT 1',(next_year_id,)).fetchone():
            raise AccountingError('سال مالی بعد برای انتقال افتتاحیه باید خالی از سند باشد.')
        if conn.execute("SELECT 1 FROM journal_entries WHERE fiscal_year_id=? AND status!='posted' LIMIT 1",(year_id,)).fetchone():
            raise AccountingError('پیش از بستن سال، همه اسناد پیش‌نویس را قطعی یا تعیین تکلیف کنید.')
        if conn.execute('SELECT 1 FROM period_locks WHERE fiscal_year_id=? AND locked=1',(year_id,)).fetchone():
            raise AccountingError('قفل دوره فعال است؛ پیش از بستن سال وضعیت قفل را بررسی کنید.')
        chart=self._classes(conn,company_id)
        if retained_account_id not in chart or chart[retained_account_id]!='equity':
            raise AccountingError('حساب انتقال سود و زیان باید تفصیلی قابل ثبت از طبقه حقوق مالکانه باشد.')
        if conn.execute('SELECT 1 FROM account_detail_rules WHERE account_id=? AND required=1',(retained_account_id,)).fetchone():
            raise AccountingError('حساب سود و زیان انباشته نباید تفصیلی شناور اجباری داشته باشد.')
        raw=self._balances(conn,company_id,year_id)
        for r in raw:
            if chart.get(r['account_id']) not in NOMINAL|PERMANENT:
                raise AccountingError('برای تمامی حساب‌های دارای مانده، طبقه مالی معتبر تعریف کنید.')
        nominal=[r for r in raw if chart[r['account_id']] in NOMINAL]
        permanent=[r.copy() for r in raw if chart[r['account_id']] in PERMANENT]
        if sum(r['balance'] for r in raw)!=0:
            raise AccountingError('مانده‌های سال مالی تراز نیستند.')
        profit=-sum(r['balance'] for r in nominal)
        if profit:
            permanent.append({'account_id':retained_account_id,'balance':-profit,
                              'detail_id':None,'party_id':None,'cost_center_id':None})
        grouped=defaultdict(int)
        for r in permanent:
            k=(r['account_id'],r['detail_id'],r['party_id'],r['cost_center_id'])
            grouped[k]+=r['balance']
        permanent=[{'account_id':k[0],'detail_id':k[1],'party_id':k[2],
                    'cost_center_id':k[3],'balance':v} for k,v in grouped.items() if v]
        if sum(r['balance'] for r in permanent)!=0:
            raise AccountingError('تراز حساب‌های دائمی پس از انتقال سود و زیان برقرار نیست.')
        close_nominal=[self._make_line(r,reverse=True) for r in nominal]
        if profit:
            close_nominal.append({'account_id':retained_account_id,'debit':max(-profit,0),
                                  'credit':max(profit,0)})
        # An empty nominal close is valid. A lone amount can't be a balanced journal.
        if close_nominal and (len(close_nominal)<2 or sum(x['debit']-x['credit'] for x in close_nominal)):
            raise AccountingError('سند بستن موقت‌ها نامتوازن است.')
        closing=[self._make_line(r,reverse=True) for r in permanent]
        opening=[self._make_line(r) for r in permanent]
        if len(closing)<2 or sum(x['debit']-x['credit'] for x in closing):
            raise AccountingError('حداقل دو حساب دائمی با مانده برای ثبت اختتامیه لازم است.')
        return {'profit':profit,'temporary_lines':close_nominal,'closing_lines':closing,
                'opening_lines':opening,'end_day':fy['end_date'],'start_day':next_fy['start_date'],
                'year_code':fy['code'],'next_code':next_fy['code']}

    def closing_preview(self,company_id,year_id,next_year_id,retained_account_id):
        with closing(self._connection()) as conn:
            result=self._plan_close(conn,company_id,year_id,next_year_id,retained_account_id)
        return {'profit':result['profit'],'temporary_lines':len(result['temporary_lines']),
                'closing_lines':len(result['closing_lines']),'opening_lines':len(result['opening_lines']),
                'current_year':result['year_code'],'next_year':result['next_code']}

    def closing_preview_details(self, company_id, year_id, next_year_id, retained_account_id):
        """Read-only, dimension-preserving preview of each proposed year-end journal.

        The plan is computed afresh by the same validation path as close_fiscal_year.
        No journal is created and no year is locked.
        """
        with closing(self._connection()) as conn:
            plan = self._plan_close(conn, company_id, year_id, next_year_id, retained_account_id)
            account_ids = {r['account_id'] for key in ('temporary_lines', 'closing_lines', 'opening_lines')
                           for r in plan[key]}
            account_names = {}
            if account_ids:
                marks = ','.join('?' for _ in account_ids)
                account_names = {r['id']: (r['code'], r['title']) for r in conn.execute(
                    'SELECT id,code,title FROM accounts WHERE company_id=? AND id IN ('+marks+')',
                    (company_id, *sorted(account_ids)))}
            detail_names = {}
            for table, label in (('floating_details','detail_id'), ('parties','party_id'),
                                 ('cost_centers','cost_center_id')):
                # The IDs remain separate because they belong to different dimensions.
                ids={r[label] for key in ('temporary_lines','closing_lines','opening_lines')
                     for r in plan[key] if r.get(label) is not None}
                if ids:
                    marks=','.join('?' for _ in ids)
                    detail_names[label]={r['id']: r['title'] for r in conn.execute(
                        'SELECT id,'+('name' if table=='parties' else 'title')+' AS title FROM '+table+' WHERE company_id=? AND id IN ('+marks+')',
                        (company_id,*sorted(ids)))}
                else:
                    detail_names[label]={}
        journals=[]
        for kind, title, day in (
            ('temporary_lines','بستن حساب‌های موقت',plan['end_day']),
            ('closing_lines','سند اختتامیه',plan['end_day']),
            ('opening_lines','سند افتتاحیه',plan['start_day'])):
            rows=[]
            for item in plan[kind]:
                code, name=account_names[item['account_id']]
                rows.append({**item,'account_code':code,'account_title':name,
                             'detail_title':detail_names['detail_id'].get(item.get('detail_id'),''),
                             'party_title':detail_names['party_id'].get(item.get('party_id'),''),
                             'cost_center_title':detail_names['cost_center_id'].get(item.get('cost_center_id'),'')})
            journals.append({'kind':kind,'title':title,'date':day,'rows':rows,
                             'total_debit':sum(r['debit'] for r in rows),
                             'total_credit':sum(r['credit'] for r in rows)})
        return {'profit':plan['profit'],'current_year':plan['year_code'],
                'next_year':plan['next_code'],'journals':journals}

    def close_fiscal_year(self,company_id,year_id,next_year_id,retained_account_id):
        """One-transaction closing, final balance closing, next-year opening and lock.
        A local safety backup is created before any close write.
        """
        with closing(self._connection()) as conn:
            self._plan_close(conn,company_id,year_id,next_year_id,retained_account_id)
        backup_path=self.path.with_name(self.path.stem+'.pre_close_'+str(year_id)+'.sqlite3')
        if backup_path.exists():
            raise AccountingError('پشتیبان قبلی بستن سال وجود دارد؛ پیش از اقدام مجدد بررسی کنید: '+str(backup_path))
        self.backup(backup_path)
        with self._write() as conn:
            plan=self._plan_close(conn,company_id,year_id,next_year_id,retained_account_id)
            result_id=None
            if plan['temporary_lines']:
                result_id=self._insert_kind(conn,company_id,year_id,plan['end_day'],
                    'بستن حساب‌های موقت سال '+str(plan['year_code']),plan['temporary_lines'],'result_close')
            close_id=self._insert_kind(conn,company_id,year_id,plan['end_day'],
                'سند اختتامیه سال '+str(plan['year_code']),plan['closing_lines'],'balance_close')
            opening_id=self._insert_kind(conn,company_id,next_year_id,plan['start_day'],
                'سند افتتاحیه انتقالی از سال '+str(plan['year_code']),plan['opening_lines'],'opening')
            conn.execute('INSERT INTO fiscal_closures(company_id,fiscal_year_id,next_year_id,retained_account_id,result_entry_id,close_entry_id,opening_entry_id,profit_rial) VALUES (?,?,?,?,?,?,?,?)',
                         (company_id,year_id,next_year_id,retained_account_id,result_id,close_id,opening_id,plan['profit']))
            self._verify_closure_in_connection(conn,company_id,year_id,next_year_id,
                result_id,close_id,opening_id,plan['profit'])
            conn.execute('UPDATE fiscal_years SET is_closed=1 WHERE id=? AND company_id=?',(year_id,company_id))
            self._audit(conn,company_id,'YEAR_CLOSED','fiscal_year',year_id,'opening='+str(opening_id))
            return {'result_id':result_id,'close_id':close_id,'opening_id':opening_id,
                    'profit':plan['profit'],'backup':str(backup_path)}

    @staticmethod
    def _verify_closure_in_connection(conn, company_id, year_id, next_year_id,
                                      result_id, close_id, opening_id, expected_profit):
        """Check journal existence, amounts, dimensions and exact close/open reversal.

        Run before committing the closing transaction; discrepancies abort it.
        """
        specs=((close_id,year_id,'balance_close'),(opening_id,next_year_id,'opening'))
        if result_id is not None:
            specs+=((result_id,year_id,'result_close'),)
        for entry_id, expected_year, expected_kind in specs:
            row=conn.execute("""SELECT j.company_id,j.fiscal_year_id,j.status,j.entry_kind,
                COALESCE(SUM(l.debit_rial),0) debit,COALESCE(SUM(l.credit_rial),0) credit,
                COUNT(l.id) line_count FROM journal_entries j
                LEFT JOIN journal_lines l ON l.entry_id=j.id WHERE j.id=?
                GROUP BY j.id""",(entry_id,)).fetchone()
            if (row is None or row['company_id']!=company_id or
                row['fiscal_year_id']!=expected_year or row['status']!='posted' or
                row['entry_kind']!=expected_kind or row['line_count']<2 or
                row['debit']!=row['credit']):
                raise AccountingError('سند بستن یا افتتاحیه معتبر و متوازن نیست.')
        def dimensions(entry_id):
            return {tuple(row[k] for k in ('account_id','detail_id','party_id','cost_center_id')):row['net']
                    for row in conn.execute("""SELECT account_id,detail_id,party_id,cost_center_id,
                        SUM(debit_rial-credit_rial) net FROM journal_lines
                        WHERE entry_id=? GROUP BY account_id,detail_id,party_id,cost_center_id""",(entry_id,))}
        closing=dimensions(close_id)
        opening=dimensions(opening_id)
        if set(closing)!=set(opening) or any(closing[key]!=-opening[key] for key in closing):
            raise AccountingError('ابعاد و مانده‌های اختتامیه و افتتاحیه یکسان نیستند.')
        if result_id is not None:
            classes=FinanceStore._classes(conn,company_id)
            rows=conn.execute("SELECT account_id,SUM(debit_rial-credit_rial) net FROM journal_lines WHERE entry_id=? GROUP BY account_id",(result_id,)).fetchall()
            nominal_effect=sum(r['net'] for r in rows if classes.get(r['account_id']) in NOMINAL)
            if nominal_effect != expected_profit:
                raise AccountingError('سند بستن حساب‌های موقت با سود و زیان سازگار نیست.')
        return {'ok':True,'closing_id':close_id,'opening_id':opening_id,
                'result_id':result_id,'dimensions_checked':len(closing),
                'profit_rial':expected_profit}

    def verify_fiscal_closure(self,company_id,year_id):
        """Read-only verification of a previously completed fiscal close."""
        with closing(self._connection()) as conn:
            row=conn.execute("""SELECT fc.*,fy.is_closed FROM fiscal_closures fc
                JOIN fiscal_years fy ON fy.id=fc.fiscal_year_id
                WHERE fc.company_id=? AND fc.fiscal_year_id=?""",(company_id,year_id)).fetchone()
            if row is None or not row['is_closed']:
                raise AccountingError('سال مالی بسته‌شده معتبری برای کنترل وجود ندارد.')
            return self._verify_closure_in_connection(conn,company_id,year_id,
                row['next_year_id'],row['result_entry_id'],row['close_entry_id'],
                row['opening_entry_id'],row['profit_rial'])

    def closure_info(self,company_id,year_id):
        return self._read_one('SELECT * FROM fiscal_closures WHERE company_id=? AND fiscal_year_id=?',(company_id,year_id))

    def trial_balance(self, company_id, year_id, include_closing=False):
        self._year(company_id,year_id)
        predicate='' if include_closing else " AND j.entry_kind NOT IN ('result_close','balance_close')"
        query='''SELECT a.id,a.code,a.title,a.level,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=?'''+predicate+''' THEN l.debit_rial ELSE 0 END),0) AS debit,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=?'''+predicate+''' THEN l.credit_rial ELSE 0 END),0) AS credit
          FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id
          LEFT JOIN journal_entries j ON j.id=l.entry_id
          WHERE a.company_id=? AND a.is_postable=1
          GROUP BY a.id ORDER BY a.code'''
        return self._read_all(query,(year_id,year_id,company_id))

    def trial_balance_levels(self,company_id,year_id,level=4):
        if level not in (1,2,3,4):raise AccountingError('سطح تراز باید ۱ تا ۴ باشد.')
        chart={x['id']:x for x in self.accounts(company_id)}
        agg=defaultdict(lambda:[0,0])
        for r in self.trial_balance(company_id,year_id):
            x=chart[r['id']]
            while x['level']>level:
                x=chart[x['parent_id']]
            agg[x['id']][0]+=r['debit'];agg[x['id']][1]+=r['credit']
        return [{'id':k,'code':chart[k]['code'],'title':chart[k]['title'],'level':chart[k]['level'],
                 'debit':v[0],'credit':v[1]} for k,v in sorted(agg.items(),key=lambda pair:chart[pair[0]]['code'])]

    def trial_balance_six(self,company_id,year_id,start_jalali=None,end_jalali=None,level=4):
        """Six monetary columns: opening Dr/Cr, movement Dr/Cr, closing Dr/Cr."""
        if level not in (1,2,3,4):raise AccountingError('سطح گزارش نامعتبر است.')
        year=self._year(company_id,year_id)
        start=parse_jalali(start_jalali).isoformat() if start_jalali else year['start_date']
        end=parse_jalali(end_jalali).isoformat() if end_jalali else year['end_date']
        if not(year['start_date']<=start<=end<=year['end_date']):raise AccountingError('بازه گزارش خارج از سال مالی است.')
        sql="""SELECT a.id,a.code,a.title,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=?
               AND j.entry_kind NOT IN ('result_close','balance_close') AND j.entry_date<?
               THEN l.debit_rial-l.credit_rial ELSE 0 END),0) opening,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=?
               AND j.entry_kind NOT IN ('result_close','balance_close') AND j.entry_date BETWEEN ? AND ?
               THEN l.debit_rial ELSE 0 END),0) debit,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=?
               AND j.entry_kind NOT IN ('result_close','balance_close') AND j.entry_date BETWEEN ? AND ?
               THEN l.credit_rial ELSE 0 END),0) credit
          FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id
          LEFT JOIN journal_entries j ON j.id=l.entry_id
          WHERE a.company_id=? AND a.is_postable=1 GROUP BY a.id ORDER BY a.code"""
        rows=self._read_all(sql,(year_id,start,year_id,start,end,year_id,start,end,company_id))
        chart={r['id']:r for r in self.accounts(company_id)}
        grouped=defaultdict(lambda:[0,0,0])
        for row in rows:
            node=chart[row['id']]
            while node['level']>level:node=chart[node['parent_id']]
            sums=grouped[node['id']]
            sums[0]+=row['opening'];sums[1]+=row['debit'];sums[2]+=row['credit']
        result=[]
        for account_id,vals in sorted(grouped.items(),key=lambda pair:chart[pair[0]]['code']):
            op,db,cr=vals
            bal=op+db-cr
            acc=chart[account_id]
            result.append({'code':acc['code'],'title':acc['title'],
              'opening_debit':max(op,0),'opening_credit':max(-op,0),
              'movement_debit':db,'movement_credit':cr,
              'closing_debit':max(bal,0),'closing_credit':max(-bal,0)})
        return result

    def export_trial_six_csv(self,company_id,year_id,path,start_jalali=None,end_jalali=None,level=4):
        data=self.trial_balance_six(company_id,year_id,start_jalali,end_jalali,level)
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f)
            w.writerow(['کد','عنوان','ابتدای دوره بدهکار','ابتدای دوره بستانکار','گردش بدهکار',
                         'گردش بستانکار','پایان دوره بدهکار','پایان دوره بستانکار'])
            for r in data:
                w.writerow([r[k] for k in ('code','title','opening_debit','opening_credit',
                          'movement_debit','movement_credit','closing_debit','closing_credit')])
        return str(path)

    def lock_period(self,company_id,year_id,start_jalali,end_jalali):
        year=self._year(company_id,year_id)
        start=parse_jalali(start_jalali).isoformat()
        end=parse_jalali(end_jalali).isoformat()
        if not(year['start_date']<=start<=end<=year['end_date']) or year['is_closed']:
            raise AccountingError('بازه قفل باید داخل سال مالی باز باشد.')
        with self._write() as conn:
            cur=conn.execute('INSERT INTO period_locks(company_id,fiscal_year_id,start_date,end_date,locked) VALUES (?,?,?,?,1)',
                             (company_id,year_id,start,end))
            self._audit(conn,company_id,'LOCK','period_lock',cur.lastrowid,start+'..'+end)
            return cur.lastrowid

    @staticmethod
    def _render_html(title,header,rows):
        """Print-ready local HTML; escape every dynamic field to prevent HTML injection."""
        style="""body{direction:rtl;font-family:Tahoma,'Segoe UI',sans-serif;color:#18213a;background:#f6f7fc;padding:28px}
        main{max-width:1050px;margin:auto;background:white;padding:30px;border-radius:15px}
        h1{color:#4637a3}p{color:#687b94;font-size:12px}table{width:100%;border-collapse:collapse}
        th,td{text-align:right;border-bottom:1px solid #e5eaf4;padding:9px;font-size:12px}
        th{background:#eeebff;color:#4738a7}tr:nth-child(even){background:#f9f9ff}
        @media print{body{padding:0;background:#fff}main{padding:0}}"""
        title=html_escape(str(title))
        headings=''.join('<th>'+html_escape(str(t))+'</th>' for t in header)
        body=''.join('<tr>'+''.join('<td>'+html_escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)
        return ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>'+title+'</title>'
                '<style>'+style+'</style></head><body><main><h1>'+title+'</h1>'
                '<p>گزارش داخلی حسابداری صبا — برای استفاده رسمی باید توسط حسابدار مسئول بررسی شود.</p>'
                '<table><thead><tr>'+headings+'</tr></thead><tbody>'+body+'</tbody></table></main></body></html>')

    def export_statement_html(self,company_id,year_id,path):
        report=self.statements(company_id,year_id)
        rows=[]
        for key,title in [('revenue','درآمدها'),('costs','بهای تمام‌شده'),('expenses','هزینه‌ها'),
                          ('assets','دارایی‌ها'),('liabilities','بدهی‌ها'),('equity','حقوق مالکانه')]:
            rows.append((title,''))
            rows.extend((x['code']+' - '+x['title'],format(x['amount'],',')) for x in report[key]['items'])
            rows.append(('جمع '+title,format(report[key]['total'],',')))
        rows.extend([('سود یا زیان دوره',format(report['net_profit'],',')),
                     ('اختلاف ترازنامه',format(report['balance_difference'],','))])
        Path(path).write_text(self._render_html('صورت‌های مالی داخلی',['عنوان','مبلغ ریالی'],rows),encoding='utf-8')
        return str(path)

    def export_general_journal_html(self,company_id,year_id,path):
        data=self.general_journal(company_id,year_id)
        rows=[(r['serial_no'],display_jalali(r['entry_date']),r['code'],r['title'],r['description'],
               format(r['debit_rial'],','),format(r['credit_rial'],',')) for r in data]
        Path(path).write_text(self._render_html('دفتر روزنامه داخلی',
           ['سند','تاریخ','کد','عنوان','شرح','بدهکار ریالی','بستانکار ریالی'],rows),encoding='utf-8')
        return str(path)

    def general_journal(self,company_id,year_id):
        self._year(company_id,year_id)
        return self._read_all('''SELECT j.id,j.serial_no,j.entry_date,j.description,j.entry_kind,
          a.code,a.title,l.row_no,l.narration,l.debit_rial,l.credit_rial,d.code detail_code,d.title detail_title
          FROM journal_entries j JOIN journal_lines l ON l.entry_id=j.id
          JOIN accounts a ON a.id=l.account_id
          LEFT JOIN floating_details d ON d.id=l.detail_id
          WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted'
          ORDER BY j.entry_date,j.serial_no,l.row_no''',(company_id,year_id))

    def reconcile_accounting_reports(self, company_id, year_id, include_closing=False):
        """Independently reconcile posted journal lines, trial and account ledgers.

        Closing entries are consistently included or excluded in all three views.
        This is an internal arithmetic check, not an audit certification.
        """
        self._year(company_id, year_id)
        extra = "" if include_closing else " AND j.entry_kind NOT IN ('result_close','balance_close')"
        journal = self._read_all("""SELECT a.id account_id,
            SUM(l.debit_rial) debit, SUM(l.credit_rial) credit
            FROM journal_entries j
            JOIN journal_lines l ON l.entry_id=j.id
            JOIN accounts a ON a.id=l.account_id
            WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted'
              AND a.company_id=?""" + extra + """ GROUP BY a.id""",
            (company_id, year_id, company_id))
        by_journal={r['account_id']:r for r in journal}
        trial=self.trial_balance(company_id,year_id,include_closing=include_closing)
        by_trial={r['id']:r for r in trial}
        # A separate per-account ledger aggregation, not derived from the trial.
        ledger=self._read_all("""SELECT l.account_id, SUM(l.debit_rial) debit,
            SUM(l.credit_rial) credit FROM journal_lines l
            JOIN journal_entries j ON j.id=l.entry_id
            WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted' """
            + extra + """ GROUP BY l.account_id""",(company_id,year_id))
        by_ledger={r['account_id']:r for r in ledger}
        differences=[]
        for account_id in sorted(set(by_journal)|set(by_trial)|set(by_ledger)):
            account=by_trial.get(account_id)
            values={name:(int(table.get(account_id,{}).get('debit',0)),
                          int(table.get(account_id,{}).get('credit',0)))
                    for name,table in [('journal',by_journal),('trial',by_trial),('ledger',by_ledger)]}
            if len(set(values.values()))!=1:
                differences.append({'account_id':account_id,
                    'code':account['code'] if account else '', 'values':values})
        totals={name:{'debit':sum(int(r['debit']) for r in rows),
                      'credit':sum(int(r['credit']) for r in rows)}
                for name,rows in [('journal',journal),('trial',trial),('ledger',ledger)]}
        return {'ok':not differences and len({(v['debit'],v['credit']) for v in totals.values()})==1
                and totals['journal']['debit']==totals['journal']['credit'],
                'include_closing':include_closing,'totals':totals,
                'differences':differences,'account_count':len(trial)}

    def export_reconciliation_csv(self,company_id,year_id,path,include_closing=False):
        report=self.reconcile_accounting_reports(company_id,year_id,include_closing)
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            writer=csv.writer(f)
            writer.writerow(['کنترل تطبیق گزارش‌ها','موفق' if report['ok'] else 'مغایرت'])
            writer.writerow(['گنجاندن اسناد اختتامیه','بله' if include_closing else 'خیر'])
            writer.writerow(['گزارش','بدهکار (ریال)','بستانکار (ریال)'])
            for key,title in [('journal','دفتر روزنامه'),('trial','تراز آزمایشی'),('ledger','دفتر حساب')]:
                values=report['totals'][key]
                writer.writerow([title,values['debit'],values['credit']])
            writer.writerow(['حساب‌های دارای مغایرت','شناسه حساب','جزئیات'])
            for r in report['differences']:
                writer.writerow([r['code'],r['account_id'],str(r['values'])])
        return report

    def floating_ledger(self,company_id,year_id,detail_id):
        self._year(company_id,year_id)
        detail=self._read_one('SELECT * FROM floating_details WHERE id=? AND company_id=?',(detail_id,company_id))
        if not detail:raise AccountingError('تفصیلی شناور به این شرکت تعلق ندارد.')
        return self._read_all('''SELECT j.entry_date,j.serial_no,j.description,a.code,a.title,
          l.narration,l.debit_rial,l.credit_rial FROM journal_lines l
          JOIN journal_entries j ON j.id=l.entry_id JOIN accounts a ON a.id=l.account_id
          WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted' AND l.detail_id=?
          ORDER BY j.entry_date,j.serial_no,l.row_no''',(company_id,year_id,detail_id))

    def export_general_journal_csv(self,company_id,year_id,path):
        rows=self.general_journal(company_id,year_id)
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            writer=csv.writer(f)
            writer.writerow(['شماره سند','تاریخ شمسی','نوع سند','شرح سند','کد حساب','حساب','تفصیلی شناور','شرح ردیف','بدهکار (ریال)','بستانکار (ریال)'])
            for r in rows:
                writer.writerow([r['serial_no'],display_jalali(r['entry_date']),r['entry_kind'],r['description'],
                      r['code'],r['title'],r['detail_title'] or '',r['narration'],r['debit_rial'],r['credit_rial']])
        return str(path)

    def export_closing_preview_html(self, company_id, year_id, next_year_id,
                                    retained_account_id, path):
        """Produce a read-only, escaped preview of the three year-end journals."""
        report = self.closing_preview_details(company_id, year_id, next_year_id,
                                              retained_account_id)
        rows = []
        for journal in report['journals']:
            rows.append((journal['title'], display_jalali(journal['date']), '', '', '', '', ''))
            for line in journal['rows']:
                rows.append((journal['title'], '',
                             line['account_code'] + ' - ' + line['account_title'],
                             line['detail_title'], line['party_title'],
                             format(line['debit'], ','), format(line['credit'], ',')))
            rows.append(('جمع ' + journal['title'], '', '', '', '',
                         format(journal['total_debit'], ','),
                         format(journal['total_credit'], ',')))
        content = self._render_html(
            'پیش‌نمایش اسناد پایان سال - بدون ثبت',
            ['نوع سند','تاریخ','حساب','تفصیلی شناور','طرف حساب','بدهکار (ریال)','بستانکار (ریال)'],
            rows)
        Path(path).write_text(content, encoding='utf-8')
        return str(path)

    def journal_source_summary(self, company_id, year_id):
        """Group posted entries by source, keeping documents across companies isolated."""
        self._year(company_id, year_id)
        return self._read_all("""SELECT COALESCE(j.source_module,'accounting') source,
               COUNT(DISTINCT j.id) document_count,
               COALESCE(SUM(l.debit_rial),0) debit_rial,
               COALESCE(SUM(l.credit_rial),0) credit_rial
            FROM journal_entries j JOIN journal_lines l ON l.entry_id=j.id
            WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted'
            GROUP BY COALESCE(j.source_module,'accounting')
            ORDER BY source""", (company_id, year_id))

    def full_integrity_report(self, company_id, year_id):
        """Read-only financial and ERP cross-check; not a statutory compliance audit."""
        erp = self.integrity_report(company_id)
        accounting = self.reconcile_accounting_reports(company_id, year_id)
        sources = self.journal_source_summary(company_id, year_id)
        source_imbalances = [r['source'] for r in sources
                             if r['debit_rial'] != r['credit_rial']]
        return {'ok': bool(erp['ok'] and accounting['ok'] and not source_imbalances),
                'erp': erp, 'accounting': accounting,
                'sources': sources, 'source_imbalances': source_imbalances}

    def verified_backup(self, destination, company_id=None):
        """Atomic external backup creation, integrity verification, and SHA-256 receipt.

        Prevents overwrites of pre-existing backup files. NOT encrypted.
        """
        dest = Path(destination)
        if self.path.resolve() == dest.resolve():
            raise AccountingError('فایل اصلی و نسخه پشتیبان نمی‌توانند یکی باشند.')
        if dest.exists() or dest.with_suffix(dest.suffix + '.sha256').exists():
            raise AccountingError('فایل پشتیبان یا رسید آن از قبل وجود دارد.')
        if company_id is not None:
            self._company_check_for_backup(company_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix='.saba_backup_', suffix='.sqlite3', dir=str(dest.parent))
        os.close(fd)
        tmp = Path(temp_path)
        created_destination = False
        try:
            with closing(self._connection()) as src, closing(sqlite3.connect(str(tmp))) as copy:
                src.backup(copy)
            with closing(sqlite3.connect(str(tmp))) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise AccountingError('بررسی یکپارچگی نسخه پشتیبان شکست خورد.')
                if check.execute('PRAGMA foreign_key_check').fetchall():
                    raise AccountingError('نسخه پشتیبان دارای مغایرت کلید خارجی است.')
            digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
            # Use exclusive destination creation: no accidental backup overwrite.
            with dest.open('xb') as out, tmp.open('rb') as source:
                created_destination = True
                while True:
                    chunk = source.read(1024*1024)
                    if not chunk: break
                    out.write(chunk)
            receipt = dest.with_suffix(dest.suffix + '.sha256')
            with receipt.open('x', encoding='utf-8') as proof:
                proof.write(digest + '  ' + dest.name + '\n')
            return {'path': str(dest), 'sha256': digest, 'receipt': str(receipt)}
        except Exception:
            if created_destination and dest.exists() and not dest.with_suffix(dest.suffix + '.sha256').exists():
                dest.unlink()
            raise
        finally:
            tmp.unlink(missing_ok=True)

    def _company_check_for_backup(self, company_id):
        with closing(self._connection()) as conn:
            self._company(conn, company_id)

    @staticmethod
    def verify_backup_receipt(destination):
        dest = Path(destination)
        receipt = dest.with_suffix(dest.suffix + '.sha256')
        if not dest.is_file() or not receipt.is_file():
            return False
        line = receipt.read_text(encoding='utf-8').strip().split('  ', 1)
        if len(line) != 2 or line[1] != dest.name:
            return False
        return hashlib.sha256(dest.read_bytes()).hexdigest() == line[0]

    def export_trial_levels_csv(self,company_id,year_id,level,path):
        rows=self.trial_balance_levels(company_id,year_id,level)
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f)
            w.writerow(['سطح','کد','عنوان','گردش بدهکار','گردش بستانکار','مانده بدهکار','مانده بستانکار'])
            for r in rows:
                bal=r['debit']-r['credit']
                w.writerow([level,r['code'],r['title'],r['debit'],r['credit'],max(bal,0),max(-bal,0)])
        return str(path)
