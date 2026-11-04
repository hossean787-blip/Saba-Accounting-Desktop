"""Compact operator screens for optional experimental business modules.
All input is validated by ERPStore and its SQLite constraints.
"""
import tkinter as tk
from tkinter import ttk, filedialog
from .erp import ERPStore


def show_erp(ui):
    """Render a simple Persian ERP operations panel inside the existing desktop shell."""
    ui._clear('عملیات یکپارچه — آزمایشی', 'ثبت گردش‌های نمونه و اسناد حسابداری خودکار؛ برای استفاده عملیاتی تأیید نشده')
    if not ui.company_id or not ui.year_id:
        ui._warning();return
    from .ui import WHITE, MUTED
    company=ui.company_id
    year=ui.year_id
    store=ui.store
    actions=['نگاشت حساب سیستمی','تعریف شخص','تعریف بانک یا صندوق','ثبت دریافت/پرداخت','ثبت چک',
             'تعریف انبار','تعریف کالا/خدمت','ثبت خرید','ثبت فروش','تعریف کارمند','ثبت حقوق',
             'تعریف دارایی','محاسبه استهلاک','تعریف فرمول تولید','ثبت تولید','تعریف پروژه',
             'ثبت هزینه پروژه','بودجه حساب','صدور فهرست مالیاتی محلی','گزارش وضعیت']
    toolbar=tk.Frame(ui.content,bg=ui.content.cget('bg'));toolbar.pack(fill='x',pady=(0,12))
    selector=ttk.Combobox(toolbar,values=actions,state='readonly',width=35,justify='right')
    selector.pack(side='right',padx=5);selector.current(0)
    ui._label(toolbar,'عملیات:',10,bg=toolbar.cget('bg')).pack(side='right',padx=8)
    holder=ui._card(ui.content);holder.pack(fill='both',expand=True)
    form=tk.Frame(holder,bg=WHITE);form.pack(fill='both',expand=True,padx=24,pady=16)

    def choices(table):
        if table=='accounts':
            data=store.accounts(company,True)
            return [(str(r['code'])+' · '+str(r['title'])+' [#'+str(r['id'])+']',r['id']) for r in data]
        if table=='parties':data=store.parties(company)
        elif table=='cashboxes':data=store.cashboxes(company)
        elif table=='warehouses':data=store.warehouses(company)
        elif table=='items':data=store.items(company)
        else:
            data=store.reference_choices(company, table)
        return [(str(r.get('code',r.get('personnel_code',r.get('name',r.get('title',r['id'])))))+
                ' · '+str(r.get('title',r.get('name',''))) +' [#'+str(r['id'])+']',r['id']) for r in data]

    types={'تاریخ':'date','طرف حساب':'parties','صندوق/بانک':'cashboxes','حساب':'accounts',
           'حساب دوم':'accounts','انبار':'warehouses','کالا/خدمت':'items','کالای تولیدی':'items',
           'ماده اولیه':'items','کارمند':'employees','دارایی':'assets','پروژه':'projects'}
    specs={
      'نگاشت حساب سیستمی':[('کلید',list(ERPStore.ACCOUNT_KEYS)),('حساب','accounts')],
      'تعریف شخص':[('کد','text'),('نام','text'),('نوع',['customer','supplier','employee','mixed','other'])],
      'تعریف بانک یا صندوق':[('نام','text'),('نوع',['bank','cash','pos']),('حساب','accounts')],
      'ثبت دریافت/پرداخت':[('تاریخ','date'),('صندوق/بانک','cashboxes'),('نوع',['receipt','payment']),('مبلغ','int'),('حساب دوم','accounts'),('شناسه مرجع','text')],
      'ثبت چک':[('شماره چک','text'),('بانک','text'),('تاریخ','date'),('مبلغ','int'),('نوع',['received','issued'])],
      'تعریف انبار':[('نام','text')],
      'تعریف کالا/خدمت':[('کد','text'),('نام','text'),('نوع',['good','service'])],
      'ثبت خرید':[('تاریخ','date'),('شناسه مرجع','text'),('طرف حساب','parties'),('انبار','warehouses'),('ردیف‌ها','lines')],
      'ثبت فروش':[('تاریخ','date'),('شناسه مرجع','text'),('طرف حساب','parties'),('انبار','warehouses'),('ردیف‌ها','lines')],
      'تعریف کارمند':[('کد','text'),('نام','text')],
      'ثبت حقوق':[('تاریخ','date'),('کارمند','employees'),('دوره','text'),('ناخالص','int'),('کسورات','zero')],
      'تعریف دارایی':[('کد','text'),('نام','text'),('بهای تمام‌شده','int'),('ارزش اسقاط','zero'),('عمر ماهانه','int')],
      'محاسبه استهلاک':[('تاریخ','date'),('دارایی','assets'),('دوره','text')],
      'تعریف فرمول تولید':[('کالای تولیدی','items'),('ماده اولیه','items'),('مقدار','int')],
      'ثبت تولید':[('تاریخ','date'),('کالای تولیدی','items'),('مقدار','int'),('انبار','warehouses'),('شناسه مرجع','text')],
      'تعریف پروژه':[('کد','text'),('نام','text'),('بودجه','zero')],
      'ثبت هزینه پروژه':[('تاریخ','date'),('پروژه','projects'),('مبلغ','int'),('حساب','accounts'),('حساب دوم','accounts')],
      'بودجه حساب':[('حساب','accounts'),('بودجه','zero')],
      'صدور فهرست مالیاتی محلی':[], 'گزارش وضعیت':[]
    }
    def paint(event=None):
        for child in form.winfo_children():child.destroy()
        action=selector.get()
        ui._label(form,action,13,bg=WHITE,bold=True).pack(anchor='e',pady=(0,10))
        fields=[]
        for label,field_type in specs[action]:
            line=tk.Frame(form,bg=WHITE);line.pack(fill='x',pady=4)
            ui._label(line,label,10,MUTED,bg=WHITE).pack(side='right',padx=10)
            if field_type in ('accounts','parties','warehouses','cashboxes','items','employees','assets','projects'):
                options=choices(field_type)
                inp=ttk.Combobox(line,state='readonly',justify='right',values=[o[0] for o in options],width=47)
                if options:inp.current(0)
                inp.option_ids=options
            elif isinstance(field_type,list):
                inp=ttk.Combobox(line,state='readonly',justify='right',values=field_type,width=47)
                inp.current(0)
            elif field_type=='lines':
                inp=tk.Text(line,height=4,width=55,font=('Tahoma',10))
                inp.insert('1.0','1,1,100000,0')
            else:
                inp=tk.Entry(line,justify='right',width=49,font=('Tahoma',10))
                if field_type=='date':inp.insert(0,'۱۴۰۵/۰۲/۰۵')
                if field_type=='zero':inp.insert(0,'0')
            inp.pack(side='right',padx=10)
            fields.append((label,field_type,inp))
        if action in ('ثبت فروش','ثبت خرید'):
            ui._label(form,'هر ردیف: شناسه کالا، تعداد، مبلغ واحد ریالی، نرخ مالیات به واحد یک‌صدم درصد؛ نمونه: 1,2,500000,0',
                      9,MUTED,bg=WHITE,wraplength=650).pack(anchor='e',pady=6)
        if action=='گزارش وضعیت':
            try:
                rows=store.overview(company)
                check=store.integrity_report(company)
                ui._label(form,'کنترل یکپارچگی داده: '+('موفق' if check['ok'] else 'دارای مغایرت'),10,bg=WHITE).pack(anchor='e')
                for key,val in rows.items():ui._label(form,key+' : '+str(val),10,bg=WHITE).pack(anchor='e',pady=2)
            except Exception as e:ui._error(e)
        if action=='صدور فهرست مالیاتی محلی':
            ui._label(form,'این فقط فهرست داخلی فاکتورهاست و به سامانه مؤدیان ارسال نمی‌شود.',
                      10,MUTED,bg=WHITE).pack(anchor='e')
        def parse():
            values=[]
            for label,field_type,inp in fields:
                if field_type=='lines':
                    parsed=[]
                    for ln in inp.get('1.0','end').splitlines():
                        if not ln.strip():continue
                        bits=[int(x.strip()) for x in ln.split(',')]
                        if len(bits)!=4:raise ValueError('هر ردیف فاکتور باید چهار ستون داشته باشد.')
                        parsed.append(dict(zip(('item_id','qty','unit_price_rial','tax_rate_bps'),bits)))
                    values.append(parsed)
                elif field_type in ('accounts','parties','warehouses','cashboxes','items','employees','assets','projects'):
                    index=inp.current()
                    if index<0:raise ValueError('ابتدا اطلاعات پایه '+label+' را تعریف کنید.')
                    values.append(inp.option_ids[index][1])
                elif field_type in ('int','zero'):
                    values.append(int(inp.get().strip()))
                else:values.append(inp.get().strip())
            return values
        def save():
            try:
                x=parse();result=None
                if action=='نگاشت حساب سیستمی':result=store.configure(company,**{x[0]:x[1]})
                elif action=='تعریف شخص':result=store.create_party(company,*x)
                elif action=='تعریف بانک یا صندوق':result=store.create_cashbox(company,*x)
                elif action=='ثبت دریافت/پرداخت':result=store.cash_flow(company,year,*x)
                elif action=='ثبت چک':result=store.register_check(company,*x)
                elif action=='تعریف انبار':result=store.create_warehouse(company,*x)
                elif action=='تعریف کالا/خدمت':result=store.create_item(company,*x)
                elif action=='ثبت خرید':result=store.invoice(company,year,x[0],'purchase',x[1],x[2],x[3],x[4])
                elif action=='ثبت فروش':result=store.invoice(company,year,x[0],'sale',x[1],x[2],x[3],x[4])
                elif action=='تعریف کارمند':result=store.create_employee(company,*x)
                elif action=='ثبت حقوق':result=store.payroll(company,year,*x)
                elif action=='تعریف دارایی':result=store.create_asset(company,*x)
                elif action=='محاسبه استهلاک':result=store.depreciate(company,year,*x)
                elif action=='تعریف فرمول تولید':result=store.bom_add(company,*x)
                elif action=='ثبت تولید':result=store.produce(company,year,*x)
                elif action=='تعریف پروژه':result=store.create_project(company,*x)
                elif action=='ثبت هزینه پروژه':result=store.project_cost(company,year,*x)
                elif action=='بودجه حساب':result=store.set_budget(company,year,*x)
                elif action=='صدور فهرست مالیاتی محلی':
                    file=filedialog.asksaveasfilename(filetypes=[('CSV','*.csv')],defaultextension='.csv')
                    if not file:return
                    result=store.tax_export(company,file)
                elif action=='گزارش وضعیت':
                    paint();return
                from tkinter import messagebox
                messagebox.showinfo('ثبت عملیات', 'عملیات انجام شد'+('؛ شناسه: '+str(result) if result is not None else ''))
                paint()
            except Exception as exc:ui._error(exc)
        ui._button(form,'ثبت / اجرا',save,True).pack(anchor='e',pady=10)
    selector.bind('<<ComboboxSelected>>',paint)
    paint()
