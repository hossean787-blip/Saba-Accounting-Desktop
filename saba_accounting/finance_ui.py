"""Functional financial-control workbench for Saba v0.4 Tk desktop."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import date
from .jalali import display_jalali, fmt_rial
from .storage import AccountingError


def show_finance(ui):
    ui._clear('مرکز کنترل حسابداری مالی',
              'پایان سال، تفصیلی شناور و اسناد اصلاحی؛ گزارش‌ها داخلی‌اند و جایگزین دفاتر قانونی نیستند')
    if not ui.company_id or not ui.year_id:
        return ui._warning()
    from .ui import WHITE, BG, MUTED, TEXT, ACCENT, GOOD
    company,year,store=ui.company_id,ui.year_id,ui.store
    tabs=ttk.Notebook(ui.content)
    tabs.pack(fill='both',expand=True)
    def add_tab(name):
        frame=tk.Frame(tabs,bg=BG)
        tabs.add(frame,text=ui._rtl(name) if hasattr(ui,'_rtl') else name)
        return frame

    # Year-end panel: choose next empty fiscal year and a postable equity account.
    yr=add_tab('بستن و افتتاح سال مالی')
    c=ui._card(yr);c.pack(fill='x',padx=4,pady=12)
    ui._label(c,'فرآیند اختتامیه سه‌مرحله‌ای',14,bold=True,bg=WHITE).pack(anchor='e',padx=22,pady=(18,4))
    ui._label(c,'۱) انتقال حساب‌های موقت به سود انباشته   ۲) سند اختتامیه دائمی‌ها   ۳) سند افتتاحیه سال بعد',10,MUTED,bg=WHITE).pack(anchor='e',padx=22,pady=(0,16))
    values=store.fiscal_years(company)
    others=[r for r in values if r['id']!=year]
    equity=[]
    accounts=store.accounts(company)
    lookup={a['id']:a for a in accounts}
    for acct in accounts:
        if not acct['is_postable']:continue
        node=acct
        while node['parent_id'] is not None:node=lookup[node['parent_id']]
        if node['account_class']=='equity':equity.append(acct)
    sel=tk.Frame(c,bg=WHITE);sel.pack(anchor='e',fill='x',padx=22,pady=7)
    ui._label(sel,'سال مالی بعد',10,bg=WHITE).pack(side='right',padx=8)
    next_cb=ttk.Combobox(sel,values=[str(r['code']) for r in others],state='readonly',width=15,justify='right')
    if others:next_cb.current(0)
    next_cb.pack(side='right',padx=7)
    ui._label(sel,'حساب سود و زیان انباشته',10,bg=WHITE).pack(side='right',padx=8)
    retained_cb=ttk.Combobox(sel,values=[r['code']+' | '+r['title'] for r in equity],state='readonly',width=29,justify='right')
    if equity:
        preferred=next((i for i,a in enumerate(equity) if 'انباشته' in a['title']),0)
        retained_cb.current(preferred)
    retained_cb.pack(side='right',padx=7)
    status=tk.StringVar(value='ابتدا شرایط بستن سال را بررسی کنید. با تکمیل عملیات، سال جاری قفل می‌شود.')
    ui._label(c,status.get(),10,MUTED,bg=WHITE,wraplength=800).pack(anchor='e',padx=22,pady=(8,4))
    result_area=tk.Frame(c,bg=WHITE);result_area.pack(anchor='e',fill='x',padx=22,pady=(0,17))
    out=ui._label(result_area,'',10,GOOD,bg=WHITE,wraplength=800)
    out.pack(anchor='e')
    def selected():
        if next_cb.current()<0 or retained_cb.current()<0:
            raise AccountingError('ابتدا سال مالی بعد و حساب سود انباشته را انتخاب کنید.')
        return others[next_cb.current()]['id'],equity[retained_cb.current()]['id']
    # Full journal preview remains read-only until the final confirmation.
    preview_signature = [None]
    def preview():
        try:
            ny,ret=selected()
            p=store.closing_preview_details(company,year,ny,ret)
            popup=tk.Toplevel(ui.root)
            popup.title('پیش‌نمایش اسناد پایان سال — بدون ثبت')
            popup.geometry('1060x680')
            popup.minsize(800,500)
            popup.configure(bg=BG)
            ui._label(popup,'پیش‌نمایش سندهای پایان سال — فقط خواندنی',15,bold=True).pack(anchor='e',padx=20,pady=(18,6))
            ui._label(popup,'سال {} ← {} | سود/زیان: {} ریال | هیچ سندی با این پیش‌نمایش ثبت نمی‌شود'.format(
                p['current_year'],p['next_year'],fmt_rial(p['profit'])),10,MUTED).pack(anchor='e',padx=20,pady=(0,10))
            notebook=ttk.Notebook(popup)
            notebook.pack(fill='both',expand=True,padx=16,pady=8)
            for journal in p['journals']:
                panel=tk.Frame(notebook,bg=BG)
                notebook.add(panel,text=ui._rtl(journal['title']))
                ui._label(panel,'{} | تاریخ {} | {} ردیف'.format(journal['title'],display_jalali(journal['date']),len(journal['rows'])),
                          11,bold=True).pack(anchor='e',padx=12,pady=12)
                holder=tk.Frame(panel,bg=BG)
                holder.pack(fill='both',expand=True,padx=12,pady=6)
                columns=('account','detail','party','center','debit','credit')
                table=ttk.Treeview(holder,columns=columns,show='headings',height=14)
                headings={'account':'حساب','detail':'تفصیلی شناور','party':'طرف حساب',
                          'center':'مرکز هزینه','debit':'بدهکار (ریال)','credit':'بستانکار (ریال)'}
                widths={'account':280,'detail':170,'party':125,'center':125,'debit':120,'credit':120}
                for key in columns:
                    table.heading(key,text=ui._rtl(headings[key]))
                    table.column(key,width=widths[key],anchor='e',minwidth=70)
                scroll=ttk.Scrollbar(holder,orient='vertical',command=table.yview)
                table.configure(yscrollcommand=scroll.set)
                scroll.pack(side='right',fill='y')
                table.pack(side='left',fill='both',expand=True)
                for row_item in journal['rows']:
                    table.insert('','end',values=(
                        row_item['account_code']+' | '+row_item['account_title'],
                        row_item['detail_title'],row_item['party_title'],row_item['cost_center_title'],
                        fmt_rial(row_item['debit']),fmt_rial(row_item['credit'])))
                ui._label(panel,'جمع بدهکار: {} ریال | جمع بستانکار: {} ریال'.format(
                    fmt_rial(journal['total_debit']),fmt_rial(journal['total_credit'])),11,GOOD,bold=True).pack(anchor='e',padx=18,pady=12)
            ui._button(popup,'بستن پیش‌نمایش',popup.destroy).pack(anchor='e',padx=20,pady=14)
            preview_signature[0]=(ny,ret)
            out.configure(text='پیش‌نمایش هر سه سند نمایش داده شد. برای ثبت، تأیید نهایی جداگانه لازم است.')
        except Exception as exc:
            preview_signature[0]=None
            ui._error(exc)
    def do_close():
        try:
            ny,ret=selected()
            if preview_signature[0]!=(ny,ret):
                raise AccountingError('ابتدا پیش‌نمایش سه سند را برای سال و حساب انتخاب‌شده مشاهده کنید.')
            # Revalidate from current database state immediately before irreversible action.
            p=store.closing_preview_details(company,year,ny,ret)
            msg=('سال جاری بسته می‌شود و اسناد قطعی در دو سال مالی ثبت می‌شوند.\n'
                 'پیشنهاد: پیش از ادامه از اطلاعات خود نسخه پشتیبان داشته باشید.\n'
                 'سود/زیان: {} ریال\nآیا مطمئن هستید؟').format(fmt_rial(p['profit']))
            if not messagebox.askyesno('تأیید نهایی عملیات حساس',msg):return
            r=store.close_fiscal_year(company,year,ny,ret)
            preview_signature[0]=None
            messagebox.showinfo('پایان سال ثبت شد','اسناد بستن و افتتاحیه ایجاد شدند.\nپشتیبان: '+r['backup'])
            ui.refresh_years();ui.show('کنترل مالی')
        except Exception as exc:ui._error(exc)
    btn=tk.Frame(c,bg=WHITE);btn.pack(anchor='e',padx=22,pady=(0,16))
    def print_closing_preview():
        path=filedialog.asksaveasfilename(defaultextension='.html',filetypes=[('HTML','*.html')],initialfile='پیش‌نمایش-پایان-سال.html')
        if not path:return
        try:
            ny,ret=selected()
            store.export_closing_preview_html(company,year,ny,ret,path)
            messagebox.showinfo('خروجی','پیش‌نمایش چاپی بدون ثبت سند ذخیره شد.')
        except Exception as exc:ui._error(exc)
    ui._button(btn,'نسخه چاپی سه سند HTML',print_closing_preview).pack(side='right',padx=4)
    ui._button(btn,'مشاهده ردیف‌های سه سند (بدون تغییر)',preview).pack(side='right',padx=4)
    ui._button(btn,'ثبت قطعی اختتامیه و افتتاحیه',do_close,True).pack(side='right',padx=4)
    old=store.closure_info(company,year)
    if old:ui._label(yr,'این سال مالی بسته شده است. سند افتتاحیه: '+str(old['opening_entry_id']),11,GOOD,True).pack(anchor='e',padx=16)
    info=ui._card(yr);info.pack(fill='x',padx=4,pady=8)
    ui._label(info,'کنترل‌های لازم پیش از بستن سال',12,bg=WHITE,bold=True).pack(anchor='e',padx=18,pady=(12,4))
    ui._label(info,'• تعیین تکلیف تمام پیش‌نویس‌ها     • طبقه‌بندی حساب‌های دارای مانده     • خالی‌بودن سال بعد\n• تعیین حساب انباشته در حقوق مالکانه     • کنترل ترازنامه و مغایرت انبار/خزانه',10,MUTED,bg=WHITE).pack(anchor='e',padx=18,pady=(0,16))

    # Floating details and ledger.
    dtab=add_tab('تفصیلی شناور')
    cc=ui._card(dtab);cc.pack(fill='x',padx=4,pady=12)
    ui._label(cc,'ایجاد تفصیلی شناور',13,bold=True,bg=WHITE).pack(anchor='e',padx=20,pady=15)
    row=tk.Frame(cc,bg=WHITE);row.pack(anchor='e',padx=18,pady=(0,18))
    code=tk.Entry(row,width=13,justify='right');code.pack(side='right',padx=5,ipady=6)
    ui._label(row,'کد',9,MUTED,bg=WHITE).pack(side='right',padx=5)
    title=tk.Entry(row,width=29,justify='right');title.pack(side='right',padx=5,ipady=6)
    ui._label(row,'عنوان',9,MUTED,bg=WHITE).pack(side='right',padx=5)
    kinds=[('person','شخص'),('project','پروژه'),('bank','بانک'),('contract','قرارداد'),('employee','کارمند'),('asset','دارایی'),('other','سایر')]
    kind=ttk.Combobox(row,values=[x[1] for x in kinds],state='readonly',width=12,justify='right')
    kind.current(0);kind.pack(side='right',padx=5)
    listing=ui._card(dtab);listing.pack(fill='both',expand=True,padx=4,pady=10)
    table=ui._make_table(listing,[('code','کد'),('title','عنوان'),('kind','نوع')],[120,300,145])
    def refresh():
        for i in table.get_children():table.delete(i)
        for r in store.floating_details(company):table.insert('','end',iid=str(r['id']),values=(r['code'],r['title'],r['detail_type']))
    def save():
        try:store.add_floating_detail(company,code.get(),title.get(),kinds[kind.current()][0]);code.delete(0,'end');title.delete(0,'end');refresh()
        except Exception as exc:ui._error(exc)
    ui._button(row,'ثبت تفصیلی',save,True).pack(side='right',padx=12)
    refresh()
    ctl=tk.Frame(dtab,bg=BG);ctl.pack(fill='x',padx=4,pady=(0,6))
    def view():
        try:
            if not table.selection():raise AccountingError('یک تفصیلی را انتخاب کنید.')
            detail_id=int(table.selection()[0]);items=store.floating_ledger(company,year,detail_id)
            win=tk.Toplevel(ui.root);win.configure(bg=WHITE);win.title('گردش تفصیلی شناور');win.geometry('850x540')
            t=ui._make_table(win,[('date','تاریخ'),('code','کد حساب'),('desc','شرح'),('debit','بدهکار'),('credit','بستانکار')])
            for v in items:t.insert('','end',values=(display_jalali(v['entry_date']),v['code'],v['description'],fmt_rial(v['debit_rial']),fmt_rial(v['credit_rial'])))
        except Exception as exc:ui._error(exc)
    ui._button(ctl,'مشاهده گردش تفصیلی انتخاب‌شده',view,True).pack(side='right')

    # Financial report panel.
    rt=add_tab('دفاتر و ترازها')
    rep=ui._card(rt);rep.pack(fill='x',padx=4,pady=12)
    ui._label(rep,'گزارش چندسطحی حساب‌ها و دفتر روزنامه',13,bg=WHITE,bold=True).pack(anchor='e',padx=18,pady=15)
    toolbar=tk.Frame(rep,bg=WHITE);toolbar.pack(anchor='e',padx=18,pady=(0,16))
    ui._label(toolbar,'سطح گزارش',10,bg=WHITE).pack(side='right',padx=5)
    levels=[('گروه',1),('کل',2),('معین',3),('تفصیلی',4)]
    level=ttk.Combobox(toolbar,values=[x[0] for x in levels],state='readonly',width=15,justify='right')
    level.current(3);level.pack(side='right',padx=8)
    trial=ui._card(rt);trial.pack(fill='both',expand=True,padx=4,pady=10)
    tb=ui._make_table(trial,[('code','کد'),('title','عنوان حساب'),('debit','بدهکار'),('credit','بستانکار'),('balance','مانده خالص')],[100,240,145,145,145])
    def render():
        try:
            for x in tb.get_children():tb.delete(x)
            for x in store.trial_balance_levels(company,year,levels[level.current()][1]):
                tb.insert('','end',values=(x['code'],x['title'],fmt_rial(x['debit']),fmt_rial(x['credit']),fmt_rial(x['debit']-x['credit'])))
        except Exception as exc:ui._error(exc)
    def csv_trial():
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='تراز-چندسطحی.csv')
        if path:
            try:store.export_trial_levels_csv(company,year,levels[level.current()][1],path);messagebox.showinfo('خروجی','فایل خروجی ذخیره شد.')
            except Exception as exc:ui._error(exc)
    def csv_journal():
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='دفتر-روزنامه.csv')
        if path:
            try:store.export_general_journal_csv(company,year,path);messagebox.showinfo('خروجی','دفتر روزنامه ذخیره شد.')
            except Exception as exc:ui._error(exc)
    ui._button(toolbar,'نمایش تراز',render,True).pack(side='right',padx=4)
    ui._button(toolbar,'خروجی تراز CSV',csv_trial).pack(side='right',padx=4)
    ui._button(toolbar,'دفتر روزنامه CSV',csv_journal).pack(side='right',padx=4)
    def six():
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='تراز-شش-ستونی.csv')
        if path:
            try:store.export_trial_six_csv(company,year,path,level=levels[level.current()][1]);messagebox.showinfo('خروجی','گزارش شش‌ستونی ذخیره شد.')
            except Exception as exc:ui._error(exc)
    def print_journal():
        path=filedialog.asksaveasfilename(defaultextension='.html',filetypes=[('HTML','*.html')],initialfile='دفتر-روزنامه.html')
        if path:
            try:store.export_general_journal_html(company,year,path);messagebox.showinfo('خروجی','نسخه چاپی دفتر روزنامه ذخیره شد.')
            except Exception as exc:ui._error(exc)
    ui._button(toolbar,'تراز شش‌ستونی CSV',six).pack(side='right',padx=4)
    ui._button(toolbar,'نسخه چاپی دفتر HTML',print_journal).pack(side='right',padx=4)
    def reconciliation():
        try:
            result=store.reconcile_accounting_reports(company,year)
            msg=('تطبیق دفتر روزنامه، تراز آزمایشی و دفتر حساب موفق بود.' if result['ok']
                 else 'مغایرت در گزارش‌ها وجود دارد؛ فایل کنترل را بررسی کنید.')
            msg+='\nتعداد حساب‌ها: '+str(result['account_count'])
            msg+='\nجمع بدهکار: '+fmt_rial(result['totals']['journal']['debit'])
            msg+='\nجمع بستانکار: '+fmt_rial(result['totals']['journal']['credit'])
            messagebox.showinfo('نتیجه کنترل گزارش‌ها',msg) if result['ok'] else messagebox.showwarning('مغایرت گزارش‌ها',msg)
        except Exception as exc:ui._error(exc)
    def reconciliation_csv():
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='تطبیق-گزارش‌های-حسابداری.csv')
        if path:
            try:
                result=store.export_reconciliation_csv(company,year,path)
                messagebox.showinfo('خروجی','گزارش تطبیق ذخیره شد.' if result['ok'] else 'گزارش مغایرت ذخیره شد.')
            except Exception as exc:ui._error(exc)
    ui._button(toolbar,'کنترل تطبیق گزارش‌ها',reconciliation).pack(side='right',padx=4)
    ui._button(toolbar,'خروجی کنترل CSV',reconciliation_csv).pack(side='right',padx=4)
    def full_check():
        try:
            result=store.full_integrity_report(company,year)
            details='\n'.join('{}: {} سند'.format(r['source'],r['document_count']) for r in result['sources'])
            msg=('کنترل حسابداری و زیرسیستم‌ها موفق بود.' if result['ok'] else
                 'مغایرت شناسایی شد؛ برای اصلاح اطلاعات به بررسی نیاز است.')
            (messagebox.showinfo if result['ok'] else messagebox.showwarning)(
                'کنترل یکپارچگی',msg+'\n'+details)
        except Exception as exc:ui._error(exc)
    ui._button(toolbar,'کنترل یکپارچگی خزانه/فروش/انبار',full_check).pack(side='right',padx=4)
    render()

    at=add_tab('اصلاح اسناد')
    info=ui._card(at);info.pack(fill='x',padx=4,pady=12)
    ui._label(info,'سند اصلاحی و اصلاح سند قطعی',14,bold=True,bg=WHITE).pack(anchor='e',padx=20,pady=(20,9))
    ui._label(info,'در اصلاح سند قطعی، سند اصلی تغییر نمی‌کند؛ یک سند برگشت و یک سند جایگزین در یک تراکنش ثبت می‌شود.',10,MUTED,bg=WHITE).pack(anchor='e',padx=20,pady=(0,14))
    def new_adj():ui.page_journal_form(as_adjustment=True)
    ui._button(info,'ایجاد سند اصلاحی مستقل',new_adj,True).pack(anchor='e',padx=20,pady=(0,15))
    docs=[d for d in store.journals(company,year) if d['status']=='posted']
    select=ttk.Combobox(info,values=[str(d['serial_no'])+' | '+d['description'] for d in docs],state='readonly',width=50,justify='right')
    if docs:select.current(0)
    select.pack(anchor='e',padx=20,pady=6)
    def correction():
        try:
            if select.current()<0:raise AccountingError('سند قابل اصلاح یافت نشد.')
            ui.page_journal_form(correction_of=docs[select.current()]['id'])
        except Exception as exc:ui._error(exc)
    ui._button(info,'اصلاح سند انتخاب‌شده با ثبت برگشت و جایگزین',correction).pack(anchor='e',padx=20,pady=(6,20))

    locks=add_tab('قفل دوره و رویدادها')
    card=ui._card(locks);card.pack(fill='x',padx=4,pady=12)
    ui._label(card,'قفل دوره حسابداری',13,bold=True,bg=WHITE).pack(anchor='e',padx=20,pady=(16,4))
    ui._label(card,'پس از قفل، قطعی‌کردن سند در این بازه ممنوع می‌شود. رفع قفل از رابط کاربری ارائه نشده است.',10,MUTED,bg=WHITE).pack(anchor='e',padx=20,pady=(0,12))
    r=tk.Frame(card,bg=WHITE);r.pack(anchor='e',padx=20,pady=(0,18))
    current=next((y for y in values if y['id']==year),None)
    ui._label(r,'از تاریخ شمسی',10,bg=WHITE).pack(side='right',padx=6)
    begin=tk.Entry(r,width=15,justify='right');begin.insert(0,display_jalali(current['start_date']) if current else '')
    begin.pack(side='right',padx=5,ipady=6)
    ui._label(r,'تا تاریخ',10,bg=WHITE).pack(side='right',padx=6)
    finish=tk.Entry(r,width=15,justify='right');finish.insert(0,display_jalali(current['end_date']) if current else '')
    finish.pack(side='right',padx=5,ipady=6)
    def do_lock():
        if not messagebox.askyesno('تأیید قفل دوره','در این بازه ثبت قطعی سند مسدود خواهد شد. ادامه می‌دهید؟'):return
        try:
            n=store.lock_period(company,year,begin.get(),finish.get())
            messagebox.showinfo('قفل ثبت شد','قفل دوره شماره {} ایجاد شد.'.format(n))
            ui.show('کنترل مالی')
        except Exception as exc:ui._error(exc)
    ui._button(r,'فعال‌سازی قفل دوره',do_lock,True).pack(side='right',padx=8)
    logs=ui._card(locks);logs.pack(fill='both',expand=True,padx=4,pady=10)
    ui._label(logs,'تاریخچه رویدادهای مالی',12,bold=True,bg=WHITE).pack(anchor='e',padx=16,pady=(14,2))
    table_events=ui._make_table(logs,[('time','زمان'),('event','رویداد'),('target','نوع'),('id','شناسه'),('note','شرح')],
                                  [160,115,115,80,300],height=9)
    events=store.audit_events(company, 100)
    for event in events:
        table_events.insert('','end',values=(event['event_time'],event['event_type'],event['target_type'],event['target_id'],event['note']))


    # Encrypted backup is the safe default. Plain backup remains available only
    # for controlled migration/diagnostics and is clearly marked unsafe.
    safety=add_tab('پشتیبان و بازیابی')
    bc=ui._card(safety);bc.pack(fill='x',padx=6,pady=14)
    ui._label(bc,'پشتیبان رمزگذاری‌شده و قابل بازیابی',13,bg=WHITE,bold=True).pack(anchor='e',padx=16,pady=12)
    ui._label(bc,'عبارت بازیابی ذخیره نمی‌شود؛ آن را در محل امن و جداگانه نگهداری کنید.',10,MUTED,bg=WHITE).pack(anchor='e',padx=16,pady=8)
    def make_encrypted_backup():
        path=filedialog.asksaveasfilename(defaultextension='.sabaenc',filetypes=[('Saba encrypted backup','*.sabaenc')],initialfile='saba-backup.sabaenc')
        if not path:return
        password=simpledialog.askstring('عبارت بازیابی','عبارت بازیابی (حداقل ۱۲ نویسه):',show='*',parent=ui.root)
        if password is None:return
        repeat=simpledialog.askstring('تکرار عبارت','عبارت بازیابی را تکرار کنید:',show='*',parent=ui.root)
        if repeat != password:return ui._error('تکرار عبارت بازیابی مطابقت ندارد.')
        try:
            result=store.encrypted_backup(path,password,company_id=company)
            messagebox.showinfo('پشتیبان امن','پشتیبان رمزگذاری‌شده ایجاد شد.\nرسید: '+result['receipt'])
        except Exception as exc:ui._error(exc)
    ui._button(bc,'ساخت پشتیبان رمزگذاری‌شده',make_encrypted_backup,True).pack(anchor='e',padx=16,pady=10)
    ui._label(bc,'گزینه زیر plaintext است و فقط برای مهاجرت کنترل‌شده استفاده شود.',9,MUTED,bg=WHITE).pack(anchor='e',padx=16,pady=(12,2))
    def make_verified_backup():
        path=filedialog.asksaveasfilename(defaultextension='.sqlite3',filetypes=[('SQLite','*.sqlite3')],initialfile='saba-backup.sqlite3')
        if not path:return
        try:
            result=store.verified_backup(path,company_id=company)
            messagebox.showinfo('پشتیبان آزمایشی','نسخه معتبر ایجاد شد.\nرسید: '+result['receipt'])
        except Exception as exc:ui._error(exc)
    ui._button(bc,'ساخت پشتیبان plaintext و رسید',make_verified_backup).pack(anchor='e',padx=16,pady=10)
