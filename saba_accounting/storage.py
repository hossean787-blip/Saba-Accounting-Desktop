"""SQLite accounting services. Monetary amounts are integer rials.
Each mutating operation commits atomically or rolls back; default API is local single-user.
"""
import csv
import os
import sqlite3
import tempfile
from contextlib import contextmanager, closing
from pathlib import Path

from .jalali import parse_jalali, display_jalali

SCHEMA_PATH = Path(__file__).with_name('schema.sql')

class AccountingError(ValueError):
    pass

class AccountingStore:
    def __init__(self, file_path):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Safe additive migration. Keep a one-time rollback snapshot for pre-v0.2 data.
        with closing(self._connection()) as conn:
            existing = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
            if existing:
                cols = [r['name'] for r in conn.execute('PRAGMA table_info(accounts)')]
                if 'account_class' not in cols:
                    snapshot = self.path.with_suffix('.pre_v02.sqlite3')
                    if not snapshot.exists():
                        with closing(sqlite3.connect(str(snapshot))) as dest:
                            conn.backup(dest)
            conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
            cols = [r['name'] for r in conn.execute('PRAGMA table_info(accounts)')]
            if 'account_class' not in cols:
                conn.execute("ALTER TABLE accounts ADD COLUMN account_class TEXT NOT NULL DEFAULT 'unclassified'")
            conn.execute('PRAGMA user_version = 2')
            conn.commit()

    def _connection(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 10000')
        return conn

    @contextmanager
    def _write(self):
        conn = self._connection()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise AccountingError('عملیات با کنترل‌های پایگاه داده سازگار نیست: ' + str(exc)) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _read_all(self, query, args=()):
        with closing(self._connection()) as conn:
            return [dict(r) for r in conn.execute(query, args).fetchall()]

    def _read_one(self, query, args=()):
        with closing(self._connection()) as conn:
            row = conn.execute(query, args).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _audit(conn, company_id, event_type, target_type, target_id, note=''):
        conn.execute('INSERT INTO audit_events(company_id,event_type,target_type,target_id,note) VALUES (?,?,?,?,?)',
                     (company_id, event_type, target_type, str(target_id), note))

    def create_company(self, name):
        name = name.strip()
        if not name:
            raise AccountingError('نام شرکت خالی است.')
        with self._write() as conn:
            cur = conn.execute('INSERT INTO companies(name) VALUES (?)', (name,))
            ident = cur.lastrowid
            self._audit(conn, ident, 'CREATE', 'company', ident)
        return ident

    def companies(self):
        return self._read_all('SELECT id,name FROM companies ORDER BY id DESC')

    def audit_events(self, company_id, limit=100):
        """Company-scoped audit view; avoids exposing raw SQL/private storage APIs."""
        limit = max(1, min(int(limit), 1000))
        if not self._read_one('SELECT id FROM companies WHERE id=?', (company_id,)):
            raise AccountingError('شرکت معتبر نیست.')
        return self._read_all(
            'SELECT event_time,event_type,target_type,target_id,note '
            'FROM audit_events WHERE company_id=? ORDER BY id DESC LIMIT ?',
            (company_id, limit))

    def create_fiscal_year(self, company_id, code, start_jalali, end_jalali):
        if not str(code).strip():
            raise AccountingError('کد سال مالی الزامی است.')
        start, end = parse_jalali(start_jalali), parse_jalali(end_jalali)
        if start > end:
            raise AccountingError('تاریخ شروع پس از پایان است.')
        if (end - start).days > 370:
            raise AccountingError('طول سال مالی نمی‌تواند بیشتر از ۳۷۱ روز باشد.')
        with self._write() as conn:
            if conn.execute('SELECT 1 FROM fiscal_years WHERE company_id=? AND start_date<=? AND end_date>=?',
                            (company_id,end.isoformat(),start.isoformat())).fetchone():
                raise AccountingError('بازه سال مالی با سال موجود تداخل دارد.')
            cur = conn.execute('INSERT INTO fiscal_years(company_id,code,start_date,end_date) VALUES (?,?,?,?)',
                               (company_id,str(code).strip(),start.isoformat(),end.isoformat()))
            self._audit(conn, company_id, 'CREATE', 'fiscal_year',cur.lastrowid)
        return cur.lastrowid

    def fiscal_years(self, company_id):
        return self._read_all('SELECT * FROM fiscal_years WHERE company_id=? ORDER BY start_date DESC',(company_id,))

    def create_account(self, company_id, code, title, level, nature='both', parent_id=None, is_postable=False, account_class='unclassified'):
        code, title, level = str(code).strip(), title.strip(), int(level)
        if not code or not title or not (1<=level<=4):
            raise AccountingError('کد، عنوان یا سطح حساب نامعتبر است.')
        if (level==1 and parent_id is not None) or (level>1 and parent_id is None):
            raise AccountingError('حساب سطح اول بدون والد و سطوح دیگر با والد معتبر ثبت می‌شوند.')
        if is_postable and level != 4:
            raise AccountingError('در نسخه فعلی فقط حساب تفصیلی سطح چهار قابل ثبت است.')
        if nature not in ('debit','credit','both'):
            raise AccountingError('ماهیت حساب نامعتبر است.')
        if account_class not in ('unclassified','asset','liability','equity','revenue','expense','cost'):
            raise AccountingError('طبقه حساب نامعتبر است.')
        if level != 1 and account_class != 'unclassified':
            raise AccountingError('طبقه‌بندی فقط در سطح گروه حساب تعریف می‌شود.')
        with self._write() as conn:
            if parent_id is not None:
                parent = conn.execute('SELECT * FROM accounts WHERE id=? AND company_id=?', (parent_id,company_id)).fetchone()
                if not parent or parent['level'] != level-1 or parent['is_postable']:
                    raise AccountingError('حساب والد معتبر و غیرقابل ثبت انتخاب کنید.')
            cur = conn.execute('INSERT INTO accounts(company_id,code,title,parent_id,level,nature,is_postable,account_class) VALUES (?,?,?,?,?,?,?,?)',
                               (company_id,code,title,parent_id,level,nature,int(is_postable),account_class))
            self._audit(conn, company_id, 'CREATE','account',cur.lastrowid)
        return cur.lastrowid

    def accounts(self, company_id, postable_only=False):
        # Optional clause is a fixed boolean choice, never user SQL.
        return self._read_all('SELECT id,company_id,code,title,parent_id,level,nature,is_postable,is_active,account_class FROM accounts WHERE company_id=?' +  # nosec B608
                              (' AND is_postable=1 AND is_active=1' if postable_only else '')+' ORDER BY code', (company_id,))

    def new_draft(self, company_id, year_id, jalali_day, description, lines, source=None):
        entry_date = parse_jalali(jalali_day).isoformat()
        if len(lines)<2:
            raise AccountingError('سند باید حداقل دو ردیف داشته باشد.')
        with self._write() as conn:
            year = conn.execute('SELECT * FROM fiscal_years WHERE id=? AND company_id=?',(year_id,company_id)).fetchone()
            if not year or year['is_closed'] or not (year['start_date']<=entry_date<=year['end_date']):
                raise AccountingError('سال مالی بسته است یا تاریخ خارج از محدوده سال مالی است.')
            serial = conn.execute('SELECT COALESCE(MAX(serial_no),0)+1 FROM journal_entries WHERE company_id=? AND fiscal_year_id=?',
                                  (company_id,year_id)).fetchone()[0]
            source = source or (None,None,None)
            cur=conn.execute('INSERT INTO journal_entries(company_id,fiscal_year_id,serial_no,entry_date,description,source_module,source_type,source_id) VALUES (?,?,?,?,?,?,?,?)',
                             (company_id,year_id,serial,entry_date,description.strip(),*source))
            ident = cur.lastrowid
            self._insert_lines(conn, ident, lines)
            self._audit(conn,company_id,'CREATE','journal',ident)
        return ident

    @staticmethod
    def _insert_lines(conn, entry_id, lines):
        # Schema compatibility is constant for the connection/database. Query
        # once per document, not once per line (large journals may have hundreds).
        cols={r['name'] for r in conn.execute('PRAGMA table_info(journal_lines)')}
        has_detail = 'detail_id' in cols
        for i, line in enumerate(lines,1):
            account_id = int(line['account_id'])
            debit = int(line.get('debit',0))
            credit = int(line.get('credit',0))
            if debit<0 or credit<0 or debit>9_000_000_000_000_000 or credit>9_000_000_000_000_000:
                raise AccountingError('مبلغ ریالی نامعتبر است.')
            if not ((debit>0) != (credit>0)):
                raise AccountingError('در هر ردیف فقط بدهکار یا بستانکار باید مثبت باشد.')
            # v0.4 optional analytic dimensions; legacy AccountingStore stays usable.
            if has_detail:
                conn.execute('''INSERT INTO journal_lines(entry_id,account_id,row_no,debit_rial,credit_rial,narration,party_id,cost_center_id,detail_id)
                                VALUES (?,?,?,?,?,?,?,?,?)''',
                             (entry_id,account_id,i,debit,credit,line.get('narration',''),
                              line.get('party_id'),line.get('cost_center_id'),line.get('detail_id')))
            else:
                conn.execute('''INSERT INTO journal_lines(entry_id,account_id,row_no,debit_rial,credit_rial,narration,party_id,cost_center_id)
                                VALUES (?,?,?,?,?,?,?,?)''',
                             (entry_id,account_id,i,debit,credit,line.get('narration',''),
                              line.get('party_id'),line.get('cost_center_id')))

    def replace_draft(self, company_id, entry_id, jalali_day, description, lines):
        date_iso = parse_jalali(jalali_day).isoformat()
        with self._write() as conn:
            header = conn.execute('''SELECT j.*,f.start_date,f.end_date,f.is_closed FROM journal_entries j
                JOIN fiscal_years f ON f.id=j.fiscal_year_id WHERE j.id=? AND j.company_id=?''',(entry_id,company_id)).fetchone()
            if not header or header['status']!='draft' or header['is_closed'] or not (header['start_date']<=date_iso<=header['end_date']):
                raise AccountingError('سند پیش‌نویس قابل ویرایش در سال مالی باز پیدا نشد.')
            if len(lines)<2:
                raise AccountingError('سند باید حداقل دو ردیف داشته باشد.')
            conn.execute('DELETE FROM journal_lines WHERE entry_id=?',(entry_id,))
            conn.execute('UPDATE journal_entries SET entry_date=?,description=? WHERE id=?',(date_iso,description.strip(),entry_id))
            self._insert_lines(conn,entry_id,lines)
            self._audit(conn,company_id,'UPDATE','journal',entry_id)

    def post(self, company_id, entry_id):
        with self._write() as conn:
            header = conn.execute('SELECT status FROM journal_entries WHERE id=? AND company_id=?',(entry_id,company_id)).fetchone()
            if not header or header['status']!='draft':
                raise AccountingError('سند پیش‌نویس معتبر پیدا نشد.')
            try:
                conn.execute("UPDATE journal_entries SET status='posted',posted_at=datetime('now') WHERE id=?",(entry_id,))
            except sqlite3.IntegrityError as exc:
                raise AccountingError('امکان قطعی‌کردن سند وجود ندارد: '+str(exc)) from exc
            self._audit(conn,company_id,'POST','journal',entry_id)

    def reverse(self, company_id, original_id, jalali_day, explanation='سند برگشت'):
        """Creates and posts one balanced reversal inside one transaction."""
        day = parse_jalali(jalali_day).isoformat()
        with self._write() as conn:
            src = conn.execute('SELECT * FROM journal_entries WHERE id=? AND company_id=? AND status=\'posted\'',(original_id,company_id)).fetchone()
            if not src:
                raise AccountingError('سند قطعی اصلی پیدا نشد.')
            fy = conn.execute('SELECT * FROM fiscal_years WHERE id=?',(src['fiscal_year_id'],)).fetchone()
            if fy['is_closed'] or not(fy['start_date']<=day<=fy['end_date']):
                raise AccountingError('تاریخ برگشت باید در سال مالی باز سند باشد.')
            if conn.execute("SELECT id FROM journal_entries WHERE reversal_of_id=? AND status='posted'",(original_id,)).fetchone():
                raise AccountingError('سند قبلاً برگشت خورده است.')
            lines=conn.execute('SELECT * FROM journal_lines WHERE entry_id=? ORDER BY row_no',(original_id,)).fetchall()
            serial=conn.execute('SELECT COALESCE(MAX(serial_no),0)+1 FROM journal_entries WHERE company_id=? AND fiscal_year_id=?',(company_id,fy['id'])).fetchone()[0]
            cur=conn.execute('INSERT INTO journal_entries(company_id,fiscal_year_id,serial_no,entry_date,description,reversal_of_id) VALUES (?,?,?,?,?,?)',
                        (company_id,fy['id'],serial,day,explanation,original_id))
            ident=cur.lastrowid
            self._insert_lines(conn,ident,[{'account_id':r['account_id'],'debit':r['credit_rial'],'credit':r['debit_rial'],'narration':r['narration']} for r in lines])
            conn.execute("UPDATE journal_entries SET status='posted',posted_at=datetime('now') WHERE id=?",(ident,))
            self._audit(conn,company_id,'REVERSE','journal',ident,'original {}'.format(original_id))
        return ident

    def journals(self, company_id, year_id):
        return self._read_all('''SELECT j.id,j.serial_no,j.entry_date,j.description,j.status,
         COALESCE((SELECT SUM(debit_rial) FROM journal_lines WHERE entry_id=j.id),0) total
         FROM journal_entries j WHERE company_id=? AND fiscal_year_id=? ORDER BY serial_no DESC''',(company_id,year_id))

    def journal(self, company_id, entry_id):
        hdr=self._read_one('SELECT * FROM journal_entries WHERE id=? AND company_id=?',(entry_id,company_id))
        if not hdr:
            raise AccountingError('سند یافت نشد.')
        hdr['lines']=self._read_all('''SELECT l.*,a.code,a.title FROM journal_lines l JOIN accounts a ON a.id=l.account_id
            WHERE l.entry_id=? ORDER BY l.row_no''',(entry_id,))
        return hdr

    def trial_balance(self, company_id, year_id):
        if not self._read_one('SELECT id FROM fiscal_years WHERE id=? AND company_id=?',(year_id,company_id)):
            raise AccountingError('سال مالی معتبر نیست.')
        return self._read_all('''SELECT a.id,a.code,a.title,a.level,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=? THEN l.debit_rial ELSE 0 END),0) AS debit,
          COALESCE(SUM(CASE WHEN j.status='posted' AND j.fiscal_year_id=? THEN l.credit_rial ELSE 0 END),0) AS credit
          FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id
          LEFT JOIN journal_entries j ON j.id=l.entry_id
          WHERE a.company_id=? AND a.is_postable=1
          GROUP BY a.id ORDER BY a.code''',(year_id,year_id,company_id))

    def trial_balance_detailed(self, company_id, year_id, level=4, columns=6,
                               start_jalali=None, end_jalali=None):
        '''Aggregated trial balance; all amounts integer rials, posted entries only.

        2: closing debit/credit; 4: period movement + closing;
        6: opening + period + closing; 8: opening + period +
        fiscal-year cumulative turnover + closing.
        '''
        if level not in (1, 2, 3, 4) or columns not in (2, 4, 6, 8):
            raise AccountingError('سطح یا تعداد ستون تراز نامعتبر است.')
        year = self._year(company_id, year_id)
        start = parse_jalali(start_jalali).isoformat() if start_jalali else year['start_date']
        end = parse_jalali(end_jalali).isoformat() if end_jalali else year['end_date']
        if not (year['start_date'] <= start <= end <= year['end_date']):
            raise AccountingError('بازه گزارش باید داخل سال مالی و به ترتیب باشد.')
        accounts = self.accounts(company_id)
        by_id = {account['id']: account for account in accounts}
        amounts = {a['id']: [0, 0, 0, 0] for a in accounts}
        movements = self._read_all('''SELECT l.account_id, j.entry_date,
              SUM(l.debit_rial) debit, SUM(l.credit_rial) credit
            FROM journal_lines l JOIN journal_entries j ON j.id=l.entry_id
            WHERE j.company_id=? AND j.fiscal_year_id=? AND j.status='posted'
              AND j.entry_date<=? GROUP BY l.account_id,j.entry_date''',
            (company_id, year_id, end))
        for item in movements:
            account = by_id.get(item['account_id'])
            if account is None:
                raise AccountingError('حساب ردیف سند در شرکت یافت نشد.')
            if account['level'] != 4 or not account['is_postable']:
                raise AccountingError('سند به حساب غیرقابل ثبت متصل است.')
            cursor = account
            visited = set()
            while cursor:
                if cursor['id'] in visited:
                    raise AccountingError('چرخه در درختواره حساب‌ها شناسایی شد.')
                visited.add(cursor['id'])
                sums = amounts[cursor['id']]
                pos = 0 if item['entry_date'] < start else 2
                sums[pos] += item['debit']
                sums[pos + 1] += item['credit']
                parent_id = cursor['parent_id']
                if parent_id is not None and parent_id not in by_id:
                    raise AccountingError('والد حساب معتبر نیست.')
                cursor = by_id.get(parent_id)
        results = []
        for account in accounts:
            if account['level'] != level:
                continue
            opening_debit, opening_credit, period_debit, period_credit = amounts[account['id']]
            balance = opening_debit - opening_credit + period_debit - period_credit
            results.append(dict(id=account['id'], code=account['code'],
                title=account['title'], level=level,
                opening_debit=opening_debit, opening_credit=opening_credit,
                period_debit=period_debit, period_credit=period_credit,
                cumulative_debit=opening_debit + period_debit,
                cumulative_credit=opening_credit + period_credit,
                closing_debit=max(balance, 0), closing_credit=max(-balance, 0)))
        return dict(company_id=company_id, year_id=year_id, level=level,
                    columns=columns, start=start, end=end, rows=results)

    @staticmethod
    def _trial_headers(columns):
        fields = {
            2: ('closing_debit', 'closing_credit'),
            4: ('period_debit', 'period_credit', 'closing_debit', 'closing_credit'),
            6: ('opening_debit', 'opening_credit', 'period_debit', 'period_credit',
                'closing_debit', 'closing_credit'),
            8: ('opening_debit', 'opening_credit', 'period_debit', 'period_credit',
                'cumulative_debit', 'cumulative_credit', 'closing_debit', 'closing_credit'),
        }
        labels = {
            'opening_debit': 'گردش تا قبل از بازه - بدهکار',
            'opening_credit': 'گردش تا قبل از بازه - بستانکار',
            'period_debit': 'گردش دوره - بدهکار',
            'period_credit': 'گردش دوره - بستانکار',
            'cumulative_debit': 'گردش تجمعی تا پایان بازه - بدهکار',
            'cumulative_credit': 'گردش تجمعی تا پایان بازه - بستانکار',
            'closing_debit': 'مانده پایان بازه - بدهکار',
            'closing_credit': 'مانده پایان بازه - بستانکار',
        }
        return [(key, labels[key]) for key in fields[columns]]

    def export_trial_detailed_csv(self, company_id, year_id, output, level=4,
                                  columns=6, start_jalali=None, end_jalali=None):
        data = self.trial_balance_detailed(company_id, year_id, level, columns,
                                           start_jalali, end_jalali)
        fields = self._trial_headers(columns)
        with open(output, 'w', newline='', encoding='utf-8-sig') as fp:
            writer = csv.writer(fp)
            writer.writerow(['کد حساب', 'عنوان'] + [label for _, label in fields])
            for item in data['rows']:
                writer.writerow([item['code'], item['title']] + [item[key] for key, _ in fields])
            writer.writerow(['جمع', ''] + [sum(item[key] for item in data['rows']) for key, _ in fields])
        return data

    def export_trial_detailed_html(self, company_id, year_id, output, level=4,
                                   columns=6, start_jalali=None, end_jalali=None):
        from html import escape
        data = self.trial_balance_detailed(company_id, year_id, level, columns,
                                           start_jalali, end_jalali)
        fields = self._trial_headers(columns)
        company = self._read_one('SELECT name FROM companies WHERE id=?', (company_id,))
        title = 'تراز آزمایشی {} ستونی - سطح {}'.format(columns, level)
        header = '<tr><th>کد حساب</th><th>عنوان حساب</th>' + ''.join(
            '<th>{}</th>'.format(escape(label)) for _, label in fields) + '</tr>'
        body = []
        for item in data['rows']:
            body.append('<tr><td>{}</td><td>{}</td>{}</tr>'.format(
                escape(str(item['code'])), escape(str(item['title'])), ''.join(
                    '<td>{:,}</td>'.format(item[key]) for key, _ in fields)))
        totals = '<tr class="sum"><td>جمع</td><td></td>{}</tr>'.format(''.join(
            '<td>{:,}</td>'.format(sum(item[key] for item in data['rows']))
            for key, _ in fields))
        html = '''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>{title}</title><style>body{{font:12px Tahoma, sans-serif;margin:24px;color:#203247}}
h1{{font-size:20px}}.meta{{margin-bottom:18px}}table{{border-collapse:collapse;width:100%;font-size:11px}}
th,td{{border:1px solid #8ea6be;padding:7px;text-align:right}}
th{{background:#dbe9f6}}tr:nth-child(even){{background:#f5f8fc}}
.sum{{background:#d4e6f6!important;font-weight:bold}}td{{white-space:nowrap}}
@page{{size:landscape;margin:10mm}}@media print{{body{{margin:0}}}}</style></head>
<body><h1>{title}</h1><div class="meta">شرکت: {company} | سال مالی: {year} |
 از {start} تا {end}</div><table><thead>{header}</thead><tbody>{body}{totals}</tbody>
</table></body></html>'''.format(title=escape(title), company=escape(company['name']),
            year=escape(str(year_id)), start=escape(start_jalali or data['start']),
            end=escape(end_jalali or data['end']), header=header, body=''.join(body), totals=totals)
        Path(output).write_text(html, encoding='utf-8')
        return data

    def dashboard(self, company_id, year_id):
        rows = self.trial_balance(company_id,year_id)
        posted = self._read_one("SELECT COUNT(*) n FROM journal_entries WHERE company_id=? AND fiscal_year_id=? AND status='posted'",(company_id,year_id))['n']
        drafts = self._read_one("SELECT COUNT(*) n FROM journal_entries WHERE company_id=? AND fiscal_year_id=? AND status='draft'",(company_id,year_id))['n']
        return {'posted':posted, 'drafts':drafts,'debit':sum(r['debit'] for r in rows),'credit':sum(r['credit'] for r in rows)}

    def export_trial_csv(self, company_id, year_id, output):
        rows=self.trial_balance(company_id,year_id)
        with open(output,'w',newline='',encoding='utf-8-sig') as fp:
            w=csv.writer(fp)
            w.writerow(['کد حساب','عنوان','گردش بدهکار (ریال)','گردش بستانکار (ریال)','مانده بدهکار (ریال)','مانده بستانکار (ریال)'])
            for r in rows:
                bal=r['debit']-r['credit']
                w.writerow([r['code'],r['title'],r['debit'],r['credit'],max(bal,0),max(-bal,0)])

    def backup(self, target):
        dest = Path(target)
        if self.path.resolve() == dest.resolve():
            raise AccountingError('مسیر پشتیبان و پایگاه داده باید متفاوت باشند.')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            raise AccountingError('فایل مقصد وجود دارد؛ بازنویسی پشتیبان مجاز نیست.')
        handle, temporary = tempfile.mkstemp(prefix='saba-backup-', suffix='.sqlite3',
                                             dir=str(dest.parent))
        os.close(handle)
        try:
            with closing(self._connection()) as source, closing(sqlite3.connect(temporary)) as copy:
                source.backup(copy)
            with closing(sqlite3.connect(temporary)) as check:
                integrity = check.execute('PRAGMA integrity_check').fetchone()[0]
                foreign_keys = check.execute('PRAGMA foreign_key_check').fetchall()
                if integrity != 'ok' or foreign_keys:
                    raise AccountingError('فایل پشتیبان معتبر نیست.')
            # A hard link publishes the verified snapshot atomically and never
            # replaces a file that appeared after the existence check.
            try:
                os.link(temporary, dest)
            except FileExistsError as exc:
                raise AccountingError('فایل مقصد وجود دارد؛ بازنویسی پشتیبان مجاز نیست.') from exc
        finally:
            Path(temporary).unlink(missing_ok=True)
        return str(dest)

    def set_root_class(self, company_id, root_id, account_class):
        """Classification is held only at group-level; audit every first assignment."""
        categories = ('asset','liability','equity','revenue','expense','cost')
        if account_class not in categories:
            raise AccountingError('طبقه حساب معتبر نیست.')
        with self._write() as conn:
            group = conn.execute('SELECT * FROM accounts WHERE id=? AND company_id=? AND level=1',
                                 (root_id,company_id)).fetchone()
            if not group:
                raise AccountingError('گروه حساب پیدا نشد.')
            if group['account_class'] not in ('unclassified',account_class):
                raise AccountingError('تغییر طبقه گروه ثبت‌شده مجاز نیست؛ نیازمند فرآیند اصلاح کنترل‌شده است.')
            conn.execute('UPDATE accounts SET account_class=? WHERE id=?',(account_class,root_id))
            self._audit(conn,company_id,'CLASSIFY','account',root_id,account_class)

    def _year(self, company_id, year_id):
        year = self._read_one('SELECT * FROM fiscal_years WHERE id=? AND company_id=?',
                              (year_id,company_id))
        if not year:
            raise AccountingError('سال مالی متعلق به این شرکت نیست.')
        return year

    def ledger(self, company_id, year_id, account_id, start_jalali=None, end_jalali=None):
        """Chronological ledger across all postable descendants. Opening precedes filter."""
        year = self._year(company_id,year_id)
        selected = self._read_one('SELECT * FROM accounts WHERE id=? AND company_id=?',
                                  (account_id,company_id))
        if not selected:
            raise AccountingError('حساب متعلق به شرکت نیست.')
        start = parse_jalali(start_jalali).isoformat() if start_jalali else year['start_date']
        end = parse_jalali(end_jalali).isoformat() if end_jalali else year['end_date']
        if not(year['start_date']<=start<=end<=year['end_date']):
            raise AccountingError('بازه گزارش باید داخل سال مالی و به ترتیب باشد.')
        query = '''WITH RECURSIVE subtree(id) AS (
          SELECT id FROM accounts WHERE id=? AND company_id=?
          UNION ALL SELECT a.id FROM accounts a JOIN subtree p ON a.parent_id=p.id
          WHERE a.company_id=?
        )
        SELECT j.id entry_id, j.serial_no, j.entry_date, j.description,
               l.row_no, l.narration, a.code account_code, a.title account_title,
               l.debit_rial debit, l.credit_rial credit
        FROM journal_lines l
        JOIN journal_entries j ON j.id=l.entry_id
        JOIN accounts a ON a.id=l.account_id
        WHERE l.account_id IN (SELECT id FROM subtree)
          AND j.company_id=? AND j.fiscal_year_id=? AND j.status='posted'
          AND j.entry_date<=?
        ORDER BY j.entry_date,j.serial_no,l.row_no,l.id'''
        rows=self._read_all(query,(account_id,company_id,company_id,company_id,year_id,end))
        opening=0
        result=[]
        balance=0
        for row in rows:
            balance+=row['debit']-row['credit']
            if row['entry_date']<start:
                opening=balance
            else:
                row['balance']=balance
                result.append(row)
        return {'account':selected,'opening':opening,'rows':result,
                'debit':sum(r['debit'] for r in result),
                'credit':sum(r['credit'] for r in result),
                'closing':balance,'start':start,'end':end}

    def export_ledger_csv(self, company_id, year_id, account_id, path, start_jalali=None, end_jalali=None):
        report=self.ledger(company_id,year_id,account_id,start_jalali,end_jalali)
        with open(path,'w',newline='',encoding='utf-8-sig') as fp:
            writer=csv.writer(fp)
            writer.writerow(['حساب',report['account']['code'],report['account']['title']])
            writer.writerow(['مانده ابتدای بازه (بدهکار منهای بستانکار)',report['opening']])
            writer.writerow(['تاریخ','شماره سند','کد حساب','عنوان حساب','شرح سند','شرح ردیف','بدهکار','بستانکار','مانده بدهکار','مانده بستانکار'])
            for r in report['rows']:
                writer.writerow([display_jalali(r['entry_date']),r['serial_no'],r['account_code'],r['account_title'],r['description'],r['narration'],r['debit'],r['credit'],max(r['balance'],0),max(-r['balance'],0)])
            writer.writerow(['جمع گردش','','','','','',report['debit'],report['credit'],max(report['closing'],0),max(-report['closing'],0)])
        return report

    def export_ledger_html(self, company_id, year_id, account_id, path,
                           start_jalali=None, end_jalali=None):
        '''Printable, escaped RTL ledger for any account tree level, with date filter.

        The opening figure includes all posted movements before the chosen start;
        only the selected interval appears in the printed detail rows.
        '''
        from html import escape
        report = self.ledger(company_id, year_id, account_id, start_jalali, end_jalali)
        account = report['account']
        company = self._read_one('SELECT name FROM companies WHERE id=?', (company_id,))
        year = self._year(company_id, year_id)
        def e(value):
            return escape(str(value if value is not None else ''), quote=True)
        def money(value):
            return format(value, ',')
        def line(values, css=''):
            return '<tr' + (' class="'+css+'"' if css else '') + '>' + ''.join(
                '<td>'+e(value)+'</td>' for value in values) + '</tr>'
        body = line(['مانده ابتدای بازه', '', '', '', '', '',
                     '', money(report['opening']) if report['opening'] >= 0 else '('+money(-report['opening'])+')'], 'highlight')
        for row in report['rows']:
            body += line([display_jalali(row['entry_date']), row['serial_no'],
                          row['account_code'], row['description'], row['narration'],
                          money(row['debit']), money(row['credit']),
                          money(row['balance']) if row['balance'] >= 0 else '('+money(-row['balance'])+')'])
        # Final column in ordinary rows is signed balance; opening uses same convention.
        # Keep totals unambiguous by explicitly labeling debit and credit movement.
        body += line(['جمع گردش', '', '', '', '', money(report['debit']),
                      money(report['credit']), money(report['closing']) if report['closing'] >= 0
                      else '('+money(-report['closing'])+')'], 'total')
        title = 'دفتر ' + ('معین' if account['level']==3 else 'کل' if account['level']==2 else 'حساب')
        html = '''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>{title}</title><style>
@page{{size:A4 landscape;margin:12mm}}
body{{font-family:Tahoma,'Segoe UI',sans-serif;direction:rtl;color:#19293a;margin:20px;background:#eef2f6}}
main{{max-width:1180px;margin:auto;background:#fff;padding:26px;border:1px solid #dbe3eb}}
h1{{font-size:21px;margin:0;color:#234e70}}.sub{{font-size:12px;color:#42566d;margin:6px 0 14px}}
.meta{{display:flex;flex-wrap:wrap;gap:10px 25px;font-size:12px;border-block:1px solid #cad7e5;padding:12px 0;margin-bottom:14px}}
table{{border-collapse:collapse;width:100%;font-size:11px;table-layout:fixed}}
th,td{{border:1px solid #cbd5e1;padding:7px 5px;text-align:right;word-break:break-word}}
th{{background:#dae9f2}}tr.highlight{{background:#f5f8fc;font-weight:bold}}tr.total{{background:#e0edf5;font-weight:bold}}
.note{{font-size:10px;color:#586a7a;margin-top:12px}}thead{{display:table-header-group}}tr{{break-inside:avoid}}
@media print{{body{{margin:0;background:#fff}}main{{border:0;padding:0}}}}
</style></head><body><main><h1>{title}</h1>
<p class="sub">حسابداری صبا | گزارش داخلی و قابل چاپ</p>
<div class="meta"><span>شرکت: {company}</span><span>سال مالی: {year}</span>
<span>حساب: {code} — {name}</span><span>از: {start}</span><span>تا: {end}</span></div>
<table><thead><tr><th>تاریخ</th><th>شماره سند</th><th>کد حساب</th><th>شرح سند</th><th>شرح ردیف</th>
<th>بدهکار (ریال)</th><th>بستانکار (ریال)</th><th>مانده بدهکار (+) / بستانکار (-)</th></tr></thead>
<tbody>{body}</tbody></table><p class="note">گزارش داخلی؛ جایگزین دفاتر قانونی یا تأیید حسابرس نیست.</p></main></body></html>'''.format(
            title=e(title),company=e(company['name']),year=e(year['code']),
            code=e(account['code']),name=e(account['title']),
            start=e(display_jalali(report['start'])),end=e(display_jalali(report['end'])),body=body)
        Path(path).write_text(html,encoding='utf-8')
        return report

    def statements(self, company_id, year_id):
        """Unclosed-period P&L and balance sheet with current result on equity side.
        Fails closed if a posted balance belongs to an unclassified root group.
        This is a preliminary accounting view, not certified financial statements.
        """
        self._year(company_id,year_id)
        accounts=self.accounts(company_id)
        lookup={a['id']:a for a in accounts}
        trial=self.trial_balance(company_id,year_id)
        byclass={key:{} for key in ('asset','liability','equity','revenue','expense','cost')}
        root_cache={}
        def root_for(account_id):
            visited=set()
            at=account_id
            while at is not None:
                if at in visited or at not in lookup:
                    raise AccountingError('ساختار کدینگ حساب‌ها ناسازگار است.')
                visited.add(at)
                account=lookup[at]
                if account['parent_id'] is None:
                    return account
                at=account['parent_id']
            raise AccountingError('گروه حساب پیدا نشد.')
        unclassified=[]
        for row in trial:
            bal=row['debit']-row['credit']
            if not (row['debit'] or row['credit']):
                continue
            root=root_cache.setdefault(row['id'],root_for(row['id']))
            kind=root['account_class']
            if kind not in byclass:
                unclassified.append(root['code']+' - '+root['title'])
                continue
            if root['id'] not in byclass[kind]:
                byclass[kind][root['id']]={'code':root['code'],'title':root['title'],'balance':0}
            byclass[kind][root['id']]['balance']+=bal
        if unclassified:
            raise AccountingError('ابتدا گروه‌های حساب زیر را در صفحه کدینگ طبقه‌بندی کنید: '+', '.join(sorted(set(unclassified))))
        def section(key,normal):
            # Normal position: 1 debit for assets/expenses, -1 for liabilities/equity/revenue.
            items=sorted(byclass[key].values(),key=lambda x:x['code'])
            items=[{'code':x['code'],'title':x['title'],'amount':x['balance']*normal} for x in items]
            return {'items':items,'total':sum(i['amount'] for i in items)}
        assets=section('asset',1)
        liabilities=section('liability',-1)
        equity=section('equity',-1)
        revenue=section('revenue',-1)
        expenses=section('expense',1)
        costs=section('cost',1)
        profit=revenue['total']-expenses['total']-costs['total']
        liabilities_equity=liabilities['total']+equity['total']+profit
        return {'assets':assets,'liabilities':liabilities,'equity':equity,
                'revenue':revenue,'expenses':expenses,'costs':costs,
                'net_profit':profit,'balance_total':liabilities_equity,
                'balance_difference':assets['total']-liabilities_equity}

    def export_statements_csv(self, company_id, year_id, path):
        report=self.statements(company_id,year_id)
        headings=[('revenue','درآمد'),('costs','بهای تمام‌شده'),('expenses','هزینه‌ها'),
                  ('assets','دارایی‌ها'),('liabilities','بدهی‌ها'),('equity','حقوق مالکانه')]
        with open(path,'w',newline='',encoding='utf-8-sig') as fp:
            w=csv.writer(fp)
            w.writerow(['گزارش اولیه صورت‌های مالی','مبلغ (ریال)'])
            for key,label in headings:
                w.writerow([label,''])
                for item in report[key]['items']:
                    w.writerow([item['code']+' - '+item['title'],item['amount']])
                w.writerow(['جمع '+label,report[key]['total']])
            w.writerow(['سود (زیان) دوره',report['net_profit']])
            w.writerow(['جمع بدهی‌ها، حقوق مالکانه و نتیجه دوره',report['balance_total']])
            w.writerow(['اختلاف ترازنامه',report['balance_difference']])
        return report
