"""Persian RTL-oriented Tk desktop. Python 3.8+, stdlib only."""
from datetime import date
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .jalali import display_jalali, rial_number, fmt_rial
from .storage import AccountingError
from .rtl import visual

# Sepidar-like classic accounting desktop palette, with independent Saba branding.
NAVY = '#D8E8F7'        # sidebar headers
NAVY2 = '#BBD5ED'
ACCENT = '#2C6FAD'
BG = '#EAF1F8'
WHITE = '#FFFFFF'
TEXT = '#1E3145'
MUTED = '#526C82'
GOOD = '#247748'
BORDER = '#AFCADE'
VIOLET_LIGHT = '#E6F1FB'  # historical constant used in forms
CYAN = '#5B91BE'
TOOLBAR = '#D1E5F7'
HEADER = '#9CC3E4'
PANEL = '#F2F7FC'


def _v(text):
    # Windows Tk may provide system bidi. X11 commonly needs visual fallback.
    if os.environ.get('SABA_FORCE_VISUAL_RTL') == '1' or (os.name != 'nt' and os.environ.get('SABA_NATIVE_RTL') != '1'):
        return visual(text)
    return str(text)

class SabaUI:
    def __init__(self, store):
        self.store=store
        self.root=tk.Tk()
        self.root.title('صبا - نرم‌افزار یکپارچه مالی و حسابداری | نسخه ۰.۵ آزمایشی')
        self.root.geometry('1460x900')
        self.root.minsize(1150,700)
        self.root.configure(bg=BG)
        self.company_id=None
        self.year_id=None
        self.company_items=[]
        self.year_items=[]
        self.current_page='داشبورد'
        self.lines=[]
        self._style()
        self._layout()
        self.refresh_choices()
        self.show('داشبورد')

    def _style(self):
        style=ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Treeview',rowheight=25,background=WHITE,fieldbackground=WHITE,
                        foreground=TEXT,font=('Tahoma',9),bordercolor=BORDER,relief='solid')
        style.configure('Treeview.Heading',font=('Tahoma',9,'bold'),background='#C3DCF1',
                        foreground='#214663',padding=(6,7),relief='raised',borderwidth=1)
        style.map('Treeview',background=[('selected','#A9D1F3')],foreground=[('selected','#102A45')])
        style.configure('TCombobox',padding=4,font=('Tahoma',9),fieldbackground=WHITE,background=WHITE)
        style.configure('TEntry',padding=4,font=('Tahoma',9))
        style.configure('TNotebook',background=BG,borderwidth=1,tabmargins=(3,2,0,0))
        style.configure('TNotebook.Tab',padding=(12,7),font=('Tahoma',9),background='#D4E7F6',foreground=TEXT)
        style.map('TNotebook.Tab',background=[('selected',WHITE)],foreground=[('selected','#124D82')])

    def _label(self,parent,text,size=10,fg=TEXT,bold=False,bg=None,**kwargs):
        return tk.Label(parent,text=_v(text),font=('Tahoma',size,'bold' if bold else 'normal'),
                        fg=fg,bg=(bg or parent.cget('bg')),anchor='e',justify='right',**kwargs)

    def _button(self,parent,text,cmd,primary=False,**kwargs):
        return tk.Button(parent,text=_v(text),command=cmd,
                         bg='#C0DDF3' if primary else '#EFF6FC',
                         fg='#134C7C' if primary else TEXT,
                         activebackground='#97C6E9',activeforeground='#153D5E',
                         border=1,bd=1,relief='raised',cursor='hand2',
                         font=('Tahoma',9,'bold' if primary else 'normal'),
                         padx=10,pady=5,highlightthickness=0,**kwargs)

    def _card(self,parent):
        return tk.Frame(parent,bg=WHITE,highlightthickness=1,highlightbackground=BORDER)

    _rtl=staticmethod(_v)

    # Menu model mirrors the familiar operations/list panes of classic Persian ERP.
    MODULES = [
        ('میز کار',('داشبورد','شرکت و سال مالی')),
        ('حسابداری',('کدینگ حساب‌ها','ثبت سند','فهرست اسناد','تراز آزمایشی','دفتر حساب','صورت‌های مالی','کنترل مالی')),
        ('دریافت و پرداخت',('عملیات یکپارچه',)),
        ('تأمین‌کنندگان و انبار',('عملیات یکپارچه',)),
        ('مشتریان و فروش',('عملیات یکپارچه',)),
        ('حقوق و دستمزد',('عملیات یکپارچه',)),
        ('دارایی ثابت',('عملیات یکپارچه',)),
        ('تولید و پیمانکاری',('عملیات یکپارچه',)),
    ]
    SHORTCUTS = [
        ('سند جدید','ثبت سند'),('اسناد حسابداری','فهرست اسناد'),
        ('درختواره حساب‌ها','کدینگ حساب‌ها'),('تراز آزمایشی','تراز آزمایشی'),
        ('دفتر کل و معین','دفتر حساب'),('کنترل پایان سال','کنترل مالی'),
        ('سایر عملیات','عملیات یکپارچه'),
    ]

    def _layout(self):
        # Authentic Windows accounting workflow: top menu, ribbon, right-side module tree,
        # compact report workspace and bottom status bar. Every shortcut opens a working page.
        self.menubar=tk.Frame(self.root,bg='#D0E4F4',height=30,highlightbackground='#A4C2D9',highlightthickness=1)
        self.menubar.pack(side='top',fill='x')
        self.menubar.pack_propagate(False)
        for label,page in [('عملیات','داشبورد'),('حسابداری','کدینگ حساب‌ها'),('گزارش‌ها','تراز آزمایشی'),
                           ('پنجره','فهرست اسناد'),('تنظیمات','شرکت و سال مالی')]:
            tk.Button(self.menubar,text=_v(label),command=lambda x=page:self.show(x),
                      bg='#D0E4F4',fg='#173B59',activebackground='#A9CDE8',borderwidth=0,
                      padx=13,pady=3,font=('Tahoma',9)).pack(side='right')
        self._label(self.menubar,'صبا | سامانه مالی مستقل',9,'#235B8B',True,bg='#D0E4F4').pack(side='left',padx=15)

        self.ribbon=tk.Frame(self.root,bg=TOOLBAR,height=92,highlightbackground=BORDER,highlightthickness=1)
        self.ribbon.pack(side='top',fill='x')
        self.ribbon.pack_propagate(False)
        title=tk.Frame(self.ribbon,bg=TOOLBAR,width=210)
        title.pack(side='right',fill='y',padx=(8,8))
        title.pack_propagate(False)
        self._label(title,'صــبــا',19,'#175A91',True,TOOLBAR).pack(anchor='e',pady=(13,0),padx=10)
        self._label(title,'سامانه یکپارچه مالی و اداری',8,'#597994',False,TOOLBAR).pack(anchor='e',padx=10)
        tk.Frame(self.ribbon,bg=BORDER,width=1).pack(side='right',fill='y',pady=8)
        ribbon_actions=[('▣','سند جدید','ثبت سند'),('▤','فهرست اسناد','فهرست اسناد'),
                        ('▥','حساب‌ها','کدینگ حساب‌ها'),('▦','تراز آزمایشی','تراز آزمایشی'),
                        ('▤','دفتر حساب','دفتر حساب'),('▣','پایان سال','کنترل مالی'),
                        ('▥','دریافت و پرداخت','عملیات یکپارچه')]
        for glyph,label,page in ribbon_actions:
            group=tk.Frame(self.ribbon,bg=TOOLBAR)
            group.pack(side='right',fill='y',padx=3,pady=8)
            tk.Button(group,text=glyph,command=lambda x=page:self.show(x),font=('Arial',18),
                      bg='#EAF4FD',fg='#27679B',bd=1,relief='groove',width=4,pady=2,
                      cursor='hand2').pack(pady=(0,1))
            tk.Button(group,text=_v(label),command=lambda x=page:self.show(x),font=('Tahoma',8),
                      fg='#244D6B',bg=TOOLBAR,bd=0,relief='flat',cursor='hand2').pack()
        self._label(self.ribbon,'نسخه آزمایشی',9,'#647D92',bg=TOOLBAR).pack(side='left',padx=15,pady=30)

        self.status=tk.Frame(self.root,bg='#C6DDF0',height=27,highlightthickness=1,highlightbackground=BORDER)
        self.status.pack(side='bottom',fill='x')
        self.status.pack_propagate(False)
        self.status_txt=tk.StringVar(value='آماده | نسخه آزمایشی؛ داده واقعی وارد نکنید')
        tk.Label(self.status,textvariable=self.status_txt,font=('Tahoma',8),bg='#C6DDF0',fg='#2B5574',anchor='e').pack(side='right',padx=13)
        tk.Label(self.status,text='صبا ۰.۵  •  آفلاین  •  نمونه توسعه',font=('Tahoma',8),bg='#C6DDF0',fg='#486B85').pack(side='left',padx=13)

        body=tk.Frame(self.root,bg=BG)
        body.pack(side='top',expand=True,fill='both')
        self.sidebar=tk.Frame(body,bg='#DFECF8',width=246,highlightbackground=BORDER,highlightthickness=1)
        self.sidebar.pack(side='right',fill='y')
        self.sidebar.pack_propagate(False)
        s_title=tk.Frame(self.sidebar,bg='#B8D3E9',height=36)
        s_title.pack(fill='x');s_title.pack_propagate(False)
        self._label(s_title,'سیستم‌ها',11,'#19496F',True,'#B8D3E9').pack(anchor='e',padx=14,pady=8)
        self.module_list=tk.Frame(self.sidebar,bg='#DFECF8')
        self.module_list.pack(fill='x')
        self.module_headers={}
        self.navbuttons={}
        self.module_links=tk.Frame(self.sidebar,bg='#F5FAFE')
        self.module_links.pack(fill='both',expand=True,padx=5,pady=(5,5))
        for module,_pages in self.MODULES:
            btn=tk.Button(self.module_list,text=_v('▸  '+module),
                          command=lambda m=module:self._select_module(m),
                          font=('Tahoma',10,'bold'),anchor='e',padx=12,pady=8,
                          fg='#234A69',bg='#DFECF8',activebackground='#B7D6EF',
                          relief='groove',bd=1,highlightthickness=0,cursor='hand2')
            btn.pack(fill='x',pady=1)
            self.module_headers[module]=btn
        self.sidebar_note=self._label(self.sidebar,'عملیات آزمایشی | استفاده با داده نمونه',8,'#627A90',bg='#DFECF8')
        self.sidebar_note.pack(side='bottom',pady=7)
        self.active_module=None

        self.main=tk.Frame(body,bg=BG)
        self.main.pack(side='right',expand=True,fill='both')
        self.top=tk.Frame(self.main,bg='#F3F8FD',height=51,highlightbackground=BORDER,highlightthickness=1)
        self.top.pack(side='top',fill='x');self.top.pack_propagate(False)
        header=tk.Frame(self.top,bg='#F3F8FD')
        header.pack(side='right',fill='y',padx=14)
        self._label(header,'شرکت',9,'#37556F',bg='#F3F8FD').pack(side='right',padx=4,pady=13)
        self.company_cb=ttk.Combobox(header,state='readonly',width=24,justify='right')
        self.company_cb.pack(side='right',padx=5,pady=10)
        self.company_cb.bind('<<ComboboxSelected>>',self.company_changed)
        self._label(header,'سال مالی',9,'#37556F',bg='#F3F8FD').pack(side='right',padx=4,pady=13)
        self.year_cb=ttk.Combobox(header,state='readonly',width=14,justify='right')
        self.year_cb.pack(side='right',padx=5,pady=10)
        self.year_cb.bind('<<ComboboxSelected>>',self.year_changed)
        tk.Button(self.top,text=_v('میز کار'),command=lambda:self.show('داشبورد'),
                  bg='#DEEDF8',fg='#265981',font=('Tahoma',9),padx=13,bd=1,relief='ridge').pack(side='left',padx=10,pady=9)
        self.content=tk.Frame(self.main,bg=BG)
        self.content.pack(fill='both',expand=True,padx=9,pady=9)
        self._select_module('حسابداری',navigate=False)
        self.root.bind('<Control-n>',lambda event:self.show('ثبت سند'))
        self.root.bind('<Control-l>',lambda event:self.show('فهرست اسناد'))
        self.root.bind('<Control-t>',lambda event:self.show('تراز آزمایشی'))

    def _select_module(self,module,navigate=False):
        self.active_module=module
        for name,btn in self.module_headers.items():
            active=(name==module)
            btn.configure(bg='#A7CBE7' if active else '#DFECF8',
                          fg='#123F61' if active else '#234A69',
                          text=_v(('▾  ' if active else '▸  ')+name))
        for w in self.module_links.winfo_children():w.destroy()
        self.navbuttons={}  # previous module widgets have been destroyed
        pages=next((pages for name,pages in self.MODULES if name==module),())
        operations=[p for p in pages if p in ('ثبت سند','کدینگ حساب‌ها','کنترل مالی','عملیات یکپارچه','شرکت و سال مالی')]
        listings=[p for p in pages if p not in operations]
        for title,group in [('عملیات',operations),('فهرست و گزارش',listings)]:
            if not group:continue
            tk.Label(self.module_links,text=_v(title),bg='#D6E7F5',fg='#21547C',
                     anchor='e',font=('Tahoma',9,'bold'),padx=10,pady=7).pack(fill='x')
            for page in group:
                line=tk.Button(self.module_links,text=_v('•  '+page),command=lambda x=page:self.show(x),
                               bg='#F5FAFE',fg='#294F70',activebackground='#E1EFF9',
                               anchor='e',padx=18,pady=7,bd=0,font=('Tahoma',9),cursor='hand2')
                line.pack(fill='x')
                self.navbuttons[page]=(line,line,line)
        if navigate and pages:self.show(pages[0])

    def refresh_choices(self):
        old=self.company_id
        self.company_items=self.store.companies()
        self.company_cb['values']=[_v('{} | {}'.format(x['id'],x['name'])) for x in self.company_items]
        if not self.company_items:
            self.company_id=None
            self.company_cb.set(_v('ابتدا شرکت بسازید'))
        else:
            ids=[x['id'] for x in self.company_items]
            self.company_id=old if old in ids else ids[0]
            self.company_cb.current(ids.index(self.company_id))
        self.refresh_years()

    def refresh_years(self):
        old=self.year_id
        self.year_items=self.store.fiscal_years(self.company_id) if self.company_id else []
        self.year_cb['values']=[_v('{}{}'.format(x['code'],' (بسته)' if x['is_closed'] else '')) for x in self.year_items]
        if not self.year_items:
            self.year_id=None
            self.year_cb.set(_v('سال مالی ندارید'))
        else:
            ids=[x['id'] for x in self.year_items]
            self.year_id=old if old in ids else ids[0]
            self.year_cb.current(ids.index(self.year_id))

    def company_changed(self,event=None):
        index=self.company_cb.current()
        if index>=0:
            self.company_id=self.company_items[index]['id']
            self.year_id=None
            self.refresh_years()
            self.show(self.current_page)

    def year_changed(self,event=None):
        index=self.year_cb.current()
        if index>=0:
            self.year_id=self.year_items[index]['id']
            self.show(self.current_page)

    def _clear(self,title,subtitle=''):
        for child in self.content.winfo_children():child.destroy()
        heading=tk.Frame(self.content,bg='#B9D9EF',height=58,highlightthickness=1,highlightbackground=BORDER)
        heading.pack(fill='x',pady=(0,8))
        heading.pack_propagate(False)
        title_frame=tk.Frame(heading,bg='#B9D9EF')
        title_frame.pack(side='right',fill='y',padx=14)
        self._label(title_frame,title,12,'#164D79',True,bg='#B9D9EF').pack(anchor='e',pady=(6,0))
        if subtitle:self._label(title_frame,subtitle,8,'#3D6381',bg='#B9D9EF').pack(anchor='e',pady=(2,0))
        tk.Button(heading,text=_v('بازگشت به میز کار'),command=lambda:self.show('داشبورد'),
                  bg='#E9F3FB',fg='#2A628D',font=('Tahoma',8),bd=1,relief='ridge',padx=10,pady=4).pack(side='left',padx=12,pady=12)

    def _warning(self,what='ابتدا شرکت و سال مالی را تعریف کنید.',target='شرکت و سال مالی'):
        c=self._card(self.content); c.pack(fill='x',pady=8)
        self._label(c,what,12,MUTED,bg=WHITE).pack(padx=22,pady=35,anchor='e')
        self._button(c,'انتقال به تنظیمات موردنیاز',lambda:self.show(target),True).pack(padx=20,pady=(0,20),anchor='e')

    def show(self,page):
        # Keep the right-hand module expanded for the current working form.
        active_pages=next((items for name,items in self.MODULES if name==self.active_module),())
        if page not in active_pages:
            selected=next((name for name,items in self.MODULES if page in items),None)
            if selected:self._select_module(selected,navigate=False)
        self.current_page=page
        self.status_txt.set(_v('فرم جاری: {}  |  شرکت: {}  |  سال مالی: {}  |  اطلاعات آزمایشی'.format(
            page, next((c['name'] for c in self.company_items if c['id']==self.company_id),'—'),
            next((str(y['code']) for y in self.year_items if y['id']==self.year_id),'—'))))
        for name,(b,holder,marker) in self.navbuttons.items():
            b.configure(bg='#B7D6EE' if name==page else '#F5FAFE',
                        fg='#0C4C80' if name==page else '#294F70')
        if page=='داشبورد': self.page_dashboard()
        elif page=='شرکت و سال مالی': self.page_companies()
        elif page=='کدینگ حساب‌ها': self.page_accounts()
        elif page=='ثبت سند': self.page_journal_form()
        elif page=='فهرست اسناد': self.page_journals()
        elif page=='تراز آزمایشی': self.page_trial()
        elif page=='دفتر حساب': self.page_ledger()
        elif page=='صورت‌های مالی': self.page_statements()
        elif page=='کنترل مالی':
            from .finance_ui import show_finance
            show_finance(self)
        elif page=='عملیات یکپارچه':
            from .erp_ui import show_erp
            show_erp(self)
        else: self.page_future()

    def page_dashboard(self):
        self._clear('میز کار نرم‌افزار مالی صبا','نمای آشنای نرم‌افزارهای حسابداری: عملیات، فهرست‌ها و گزارش‌ها')
        if not self.company_id or not self.year_id:
            self._warning();return
        try:summary=self.store.dashboard(self.company_id,self.year_id)
        except Exception as exc:self._error(exc);return
        strip=tk.Frame(self.content,bg='#D6E7F4',height=37,highlightbackground=BORDER,highlightthickness=1)
        strip.pack(fill='x',pady=(0,8));strip.pack_propagate(False)
        self._label(strip,'اطلاعات دوره مالی فعال',10,'#235979',True,'#D6E7F4').pack(side='right',padx=14,pady=7)
        self._label(strip,'مانده‌ها و گزارش‌ها فقط بر پایه اسناد ثبت‌شده هستند',8,MUTED,bg='#D6E7F4').pack(side='left',padx=10,pady=9)
        stats=tk.Frame(self.content,bg=BG);stats.pack(fill='x',pady=(0,10))
        for label,value in [('اسناد قطعی',str(summary['posted'])),('اسناد موقت',str(summary['drafts'])),
                            ('جمع بدهکار',fmt_rial(summary['debit'])),('جمع بستانکار',fmt_rial(summary['credit']))]:
            panel=self._card(stats);panel.pack(side='right',fill='x',expand=True,padx=3)
            tk.Frame(panel,bg='#8CB7D9',height=3).pack(fill='x')
            self._label(panel,label,9,MUTED,bg=WHITE).pack(anchor='e',padx=13,pady=(11,2))
            self._label(panel,value,15,'#174C77',True,WHITE).pack(anchor='e',padx=13,pady=(0,12))
        workspace=self._card(self.content);workspace.pack(fill='both',expand=True)
        tk.Label(workspace,text=_v('دسترسی سریع به فرم‌ها'),bg='#D3E5F3',fg='#235174',
                 font=('Tahoma',10,'bold'),anchor='e',padx=18,pady=10).pack(fill='x')
        sections=[('حسابداری', [('سند حسابداری جدید','ثبت سند'),('فهرست اسناد حسابداری','فهرست اسناد'),
                                 ('درختواره حساب‌ها','کدینگ حساب‌ها'),('تراز آزمایشی','تراز آزمایشی')]),
                  ('دفاتر و گزارش‌ها',[('دفتر حساب','دفتر حساب'),('صورت‌های مالی','صورت‌های مالی'),
                                       ('بستن سال مالی','کنترل مالی'),('مدیریت شرکت و سال','شرکت و سال مالی')]),
                  ('سایر سیستم‌ها',[('دریافت و پرداخت','عملیات یکپارچه'),('خرید و فروش','عملیات یکپارچه'),
                                    ('انبار و کالا','عملیات یکپارچه'),('سایر عملیات','عملیات یکپارچه')])]
        line=tk.Frame(workspace,bg=WHITE);line.pack(fill='both',expand=True,padx=16,pady=14)
        for title,links in sections:
            box=tk.Frame(line,bg=WHITE,highlightbackground=BORDER,highlightthickness=1)
            box.pack(side='right',fill='both',expand=True,padx=6)
            self._label(box,title,11,'#164C75',True,'#DCECF8').pack(fill='x',anchor='e',padx=0,ipadx=10,ipady=8)
            for label,page in links:
                tk.Button(box,text=_v('▪  '+label),command=lambda x=page:self.show(x),
                          bg=WHITE,fg='#295879',activebackground='#E2F0FA',anchor='e',bd=0,
                          padx=12,pady=14,font=('Tahoma',10),cursor='hand2').pack(fill='x',padx=7,pady=2)
        footer=tk.Frame(self.content,bg='#EDF5FC',highlightbackground=BORDER,highlightthickness=1)
        footer.pack(fill='x',pady=(10,0))
        difference=summary['debit']-summary['credit']
        self._label(footer,'کنترل تراز اسناد: {}'.format('بدون مغایرت' if difference==0 else fmt_rial(difference)+' ریال مغایرت'),
                    10,GOOD if difference==0 else '#B43737',True,'#EDF5FC').pack(side='right',padx=15,pady=8)
        self._label(footer,'این نسخه توسعه‌ای است و برای داده واقعی تأیید نشده است.',8,MUTED,bg='#EDF5FC').pack(side='left',padx=12)

    def page_companies(self):
        self._clear('شرکت‌ها و سال‌های مالی','پیش‌نیاز حسابداری: شرکت مستقل و بازه معتبر سال مالی')
        c=self._card(self.content);c.pack(fill='x',pady=8)
        self._label(c,'شرکت جدید',12,bg=WHITE,bold=True).pack(anchor='e',padx=20,pady=(15,5))
        row=tk.Frame(c,bg=WHITE);row.pack(anchor='e',fill='x',padx=20,pady=(0,17))
        name=tk.Entry(row,font=('Tahoma',11),justify='right',width=38,relief='solid',bd=1)
        name.pack(side='right',padx=(10,3),ipady=7)
        def add_company():
            try:
                self.company_id=self.store.create_company(name.get());self.year_id=None
                self.refresh_choices();self.page_companies()
            except Exception as e:self._error(e)
        self._button(row,'ثبت شرکت',add_company,True).pack(side='right')
        c=self._card(self.content);c.pack(fill='x',pady=8)
        self._label(c,'ایجاد سال مالی برای شرکت انتخاب‌شده',12,bg=WHITE,bold=True).pack(anchor='e',padx=20,pady=13)
        r=tk.Frame(c,bg=WHITE);r.pack(anchor='e',fill='x',padx=20,pady=(0,16))
        inputs=[]
        for caption,initial in [('کد سال مالی','۱۴۰۵'),('شروع شمسی','۱۴۰۵/۰۱/۰۱'),('پایان شمسی','۱۴۰۵/۱۲/۲۹')]:
            f=tk.Frame(r,bg=WHITE);f.pack(side='right',padx=6)
            self._label(f,caption,9,MUTED,bg=WHITE).pack(anchor='e')
            box=tk.Entry(f,font=('Tahoma',10),justify='right',width=15,relief='solid',bd=1)
            box.insert(0,initial);box.pack(ipady=6); inputs.append(box)
        def add_year():
            if not self.company_id:return self._error('ابتدا شرکت بسازید.')
            try:self.year_id=self.store.create_fiscal_year(self.company_id,*[w.get() for w in inputs]);self.refresh_years();self.page_companies()
            except Exception as e:self._error(e)
        self._button(r,'ثبت سال مالی',add_year,True).pack(side='right',padx=10,pady=10)
        if self.company_id:
            b=tk.Frame(self.content,bg=BG); b.pack(fill='x',pady=9)
            def do_backup():
                from tkinter import simpledialog
                path=filedialog.asksaveasfilename(title='پشتیبان رمزگذاری‌شده',defaultextension='.sabaenc',filetypes=[('پشتیبان رمزگذاری‌شده صبا','*.sabaenc')],initialfile='saba-backup.sabaenc')
                if path:
                    password=simpledialog.askstring('عبارت بازیابی','عبارت بازیابی (حداقل ۱۲ نویسه):',show='*',parent=self.root)
                    if password is None:return
                    repeat=simpledialog.askstring('تکرار عبارت','عبارت بازیابی را تکرار کنید:',show='*',parent=self.root)
                    if repeat != password:return self._error('تکرار عبارت بازیابی مطابقت ندارد.')
                    try:self.store.encrypted_backup(path,password,self.company_id);messagebox.showinfo('تکمیل شد','پشتیبان رمزگذاری‌شده ایجاد شد.')
                    except Exception as e:self._error(e)
            self._button(b,'تهیه پشتیبان رمزگذاری‌شده',do_backup).pack(side='right')
            years=self.store.fiscal_years(self.company_id)
            self._label(self.content,'سال‌های مالی ثبت‌شده',11,bold=True).pack(anchor='e',pady=8)
            for y in years:
                self._label(self.content,'{}     |     {} تا {}     |     {}'.format(y['code'],display_jalali(y['start_date']),display_jalali(y['end_date']),'بسته' if y['is_closed'] else 'باز'),10).pack(anchor='e',pady=3)

    def _make_table(self,parent,columns,widths=None,height=12):
        area=tk.Frame(parent,bg=WHITE)
        area.pack(fill='both',expand=True,padx=12,pady=13)
        names=[x[0] for x in columns]
        table=ttk.Treeview(area,columns=names,show='headings',height=height)
        for i,(key,label) in enumerate(columns):
            table.heading(key,text=_v(label),anchor='e')
            table.column(key,anchor='e',width=(widths[i] if widths else 120),stretch=True)
        bar=ttk.Scrollbar(area,orient='vertical',command=table.yview)
        table.configure(yscrollcommand=bar.set)
        bar.pack(side='left',fill='y')
        table.pack(side='right',fill='both',expand=True)
        return table

    def page_accounts(self):
        self._clear('کدینگ حساب‌ها','گروه ← کل ← معین ← تفصیلی؛ فعلاً ثبت سند فقط روی سطح تفصیلی')
        if not self.company_id:return self._warning('ابتدا یک شرکت تعریف کنید.')
        control=tk.Frame(self.content,bg=BG); control.pack(fill='x',pady=(0,8))
        self._button(control,'افزودن حساب',self.dialog_add_account,True).pack(side='right')
        self._button(control,'طبقه‌بندی گروه‌ها',self.dialog_classify).pack(side='right',padx=8)
        rows=self.store.accounts(self.company_id)
        card=self._card(self.content);card.pack(fill='both',expand=True)
        table=self._make_table(card,[('code','کد'),('title','عنوان حساب'),('level','سطح'),('nature','ماهیت'),('class','طبقه'),('postable','قابل ثبت')],[105,215,67,84,105,75])
        level_name={1:'گروه',2:'کل',3:'معین',4:'تفصیلی'}
        nature_name={'debit':'بدهکار','credit':'بستانکار','both':'دوطرفه'}
        for a in rows:
            table.insert('', 'end', values=(a['code'],_v('   '*(a['level']-1)+a['title']),_v(level_name[a['level']]),_v(nature_name[a['nature']]),_v(self._class_label(a['account_class']) if a['level']==1 else '—'),_v('بله' if a['is_postable'] else 'خیر')))

    def dialog_add_account(self):
        dialog=tk.Toplevel(self.root)
        dialog.title('تعریف حساب جدید');dialog.geometry('480x460');dialog.configure(bg=WHITE)
        dialog.transient(self.root);dialog.grab_set()
        fields={}
        for title,key in [('کد حساب','code'),('عنوان حساب','title')]:
            r=tk.Frame(dialog,bg=WHITE);r.pack(fill='x',padx=26,pady=7)
            self._label(r,title,10,bg=WHITE).pack(side='right',padx=7)
            ent=tk.Entry(r,justify='right',font=('Tahoma',10));ent.pack(side='right',fill='x',expand=True,ipady=5)
            fields[key]=ent
        accounts=self.store.accounts(self.company_id)
        lvl=tk.StringVar(value='1')
        frame=tk.Frame(dialog,bg=WHITE);frame.pack(fill='x',padx=26,pady=8)
        self._label(frame,'سطح',10,bg=WHITE).pack(side='right',padx=7)
        levels=ttk.Combobox(frame,values=['1','2','3','4'],textvariable=lvl,state='readonly',width=6,justify='right')
        levels.pack(side='right')
        parent_var=tk.StringVar()
        frame2=tk.Frame(dialog,bg=WHITE);frame2.pack(fill='x',padx=26,pady=8)
        self._label(frame2,'والد',10,bg=WHITE).pack(side='right',padx=7)
        parent_box=ttk.Combobox(frame2,textvariable=parent_var,state='readonly',width=30,justify='right')
        parent_box.pack(side='right')
        def update_parent(*args):
            candidates=[a for a in accounts if a['level']==int(lvl.get())-1 and not a['is_postable']]
            parent_box['values']=[_v('{} | {}'.format(a['code'],a['title'])) for a in candidates]
            parent_box.current(0) if candidates else parent_box.set(_v('بدون والد'))
        levels.bind('<<ComboboxSelected>>',update_parent)
        update_parent()
        class_names=[('unclassified','انتخاب‌نشده'),('asset','دارایی'),('liability','بدهی'),
                     ('equity','حقوق مالکانه'),('revenue','درآمد'),('expense','هزینه'),('cost','بهای تمام‌شده')]
        group_row=tk.Frame(dialog,bg=WHITE);group_row.pack(fill='x',padx=26,pady=7)
        self._label(group_row,'طبقه گروه (سطح ۱)',10,bg=WHITE).pack(side='right',padx=7)
        class_cb=ttk.Combobox(group_row,state='readonly',justify='right',width=21,values=[_v(x[1]) for x in class_names])
        class_cb.current(0);class_cb.pack(side='right')
        nature=tk.StringVar(value='both')
        r=tk.Frame(dialog,bg=WHITE);r.pack(padx=26,pady=7,fill='x')
        self._label(r,'ماهیت',10,bg=WHITE).pack(side='right',padx=7)
        nature_box=ttk.Combobox(r,values=[_v('دوطرفه'),_v('بدهکار'),_v('بستانکار')],state='readonly',width=13,justify='right')
        nature_box.current(0);nature_box.pack(side='right')
        def save():
            try:
                lv=int(lvl.get()); candidates=[a for a in accounts if a['level']==lv-1 and not a['is_postable']]
                parent=candidates[parent_box.current()]['id'] if lv>1 and parent_box.current()>=0 else None
                self.store.create_account(self.company_id,fields['code'].get(),fields['title'].get(),lv,
                    ['both','debit','credit'][nature_box.current()],parent,lv==4,
                    class_names[class_cb.current()][0] if lv==1 else 'unclassified')
                dialog.destroy();self.page_accounts()
            except Exception as e:self._error(e)
        self._button(dialog,'ثبت حساب',save,True).pack(anchor='e',padx=27,pady=10)

    @staticmethod
    def _class_label(kind):
        return dict(unclassified='تعریف‌نشده',asset='دارایی',liability='بدهی',equity='حقوق مالکانه',
                    revenue='درآمد',expense='هزینه',cost='بهای تمام‌شده').get(kind,'نامعلوم')

    def dialog_classify(self):
        if not self.company_id:return self._error('ابتدا شرکت را انتخاب کنید.')
        roots=[x for x in self.store.accounts(self.company_id) if x['level']==1]
        if not roots:return self._error('ابتدا گروه حساب تعریف کنید.')
        dlg=tk.Toplevel(self.root);dlg.title('طبقه‌بندی گروه حساب');dlg.geometry('505x225')
        dlg.configure(bg=WHITE);dlg.transient(self.root);dlg.grab_set()
        self._label(dlg,'گروه حساب',10,bg=WHITE).pack(anchor='e',padx=18,pady=8)
        grp=ttk.Combobox(dlg,state='readonly',justify='right',width=48,values=[_v(x['code']+' | '+x['title']+' | '+self._class_label(x['account_class'])) for x in roots])
        grp.current(0);grp.pack(anchor='e',padx=18)
        classes=[('asset','دارایی'),('liability','بدهی'),('equity','حقوق مالکانه'),('revenue','درآمد'),('expense','هزینه'),('cost','بهای تمام‌شده')]
        self._label(dlg,'طبقه مالی',10,bg=WHITE).pack(anchor='e',padx=18,pady=8)
        cl=ttk.Combobox(dlg,state='readonly',justify='right',values=[_v(x[1]) for x in classes])
        cl.current(0);cl.pack(anchor='e',padx=18)
        def save():
            try:
                self.store.set_root_class(self.company_id,roots[grp.current()]['id'],classes[cl.current()][0])
                dlg.destroy();self.page_accounts()
            except Exception as e:self._error(e)
        self._button(dlg,'ذخیره طبقه‌بندی',save,True).pack(anchor='e',padx=18,pady=10)

    def page_journal_form(self,entry_id=None,as_adjustment=False,correction_of=None):
        self._clear('اصلاح کنترل‌شده سند قطعی' if correction_of else ('سند اصلاحی مستقل' if as_adjustment else ('ویرایش پیش‌نویس حسابداری' if entry_id else 'ثبت سند حسابداری')), 
                    'فقط اسناد پیش‌نویس قابل ویرایش هستند؛ ثبت قطعی نیازمند تراز سند است')
        if not self.company_id or not self.year_id:return self._warning()
        accs=self.store.accounts(self.company_id,True)
        if len(accs)<2:return self._warning('برای ثبت سند، حداقل دو حساب تفصیلی قابل ثبت تعریف کنید.')
        editing=None
        if entry_id is not None or correction_of is not None:
            try:
                editing=self.store.journal(self.company_id,entry_id if entry_id is not None else correction_of)
                if correction_of is not None:
                    if editing['status']!='posted' or editing['source_module'] is not None or editing['entry_kind']!='regular':
                        raise AccountingError('فقط سند قطعی دستی عادی قابل اصلاح است.')
                elif editing['status']!='draft' or editing['fiscal_year_id']!=self.year_id:
                    raise AccountingError('فقط پیش‌نویس سال مالی انتخابی قابل ویرایش است.')
            except Exception as exc:
                self._error(exc);self.show('فهرست اسناد');return
        self.lines=([{'account_id':x['account_id'],'debit':x['debit_rial'],
                      'credit':x['credit_rial'],'narration':x['narration'],
                      'detail_id':x.get('detail_id'),'party_id':x.get('party_id'),
                      'cost_center_id':x.get('cost_center_id')}
                     for x in editing['lines']] if editing else [])
        card=self._card(self.content);card.pack(fill='x')
        meta=tk.Frame(card,bg='#DAEAF7')
        meta.pack(fill='x')
        self._label(meta,'اطلاعات سند حسابداری',10,'#235779',True,bg='#DAEAF7').pack(side='right',padx=13,pady=8)
        meta_info='شماره سند: {}     |     وضعیت: {}     |     نوع سند: {}'.format(
            editing['serial_no'] if editing else 'پس از ذخیره',
            ('قطعی' if editing['status']=='posted' else 'پیش‌نویس') if editing else 'جدید',
            'اصلاحی' if (as_adjustment or correction_of) else 'عمومی')
        self._label(meta,meta_info,9,'#456F8D',bg='#DAEAF7').pack(side='left',padx=13,pady=8)
        r=tk.Frame(card,bg=WHITE);r.pack(fill='x',padx=16,pady=13)
        self._label(r,'تاریخ شمسی:',10,bg=WHITE).pack(side='right',padx=5)
        day=tk.Entry(r,justify='right',width=15,font=('Tahoma',10)); day.insert(0,display_jalali(editing['entry_date']) if editing else display_jalali(date.today()));day.pack(side='right',padx=5,ipady=6)
        self._label(r,'شرح:',10,bg=WHITE).pack(side='right',padx=8)
        desc=tk.Entry(r,justify='right',font=('Tahoma',10));
        if editing:desc.insert(0,editing['description'])
        desc.pack(side='right',expand=True,fill='x',padx=8,ipady=6)
        tk.Label(card,text=_v('اقلام سند — ورود بدهکار و بستانکار به تفکیک حساب'),bg='#E2EFF9',fg='#21567D',font=('Tahoma',9,'bold'),anchor='e',padx=15,pady=7).pack(fill='x')
        row=tk.Frame(card,bg=WHITE);row.pack(fill='x',padx=16,pady=11)
        acc_cb=ttk.Combobox(row,values=[_v('{} | {}'.format(a['code'],a['title'])) for a in accs],state='readonly',width=30,justify='right')
        acc_cb.current(0);acc_cb.pack(side='right',padx=5)
        details=self.store.floating_details(self.company_id) if hasattr(self.store,'floating_details') else []
        self._label(row,'شناور',9,MUTED,bg=WHITE).pack(side='right',padx=3)
        detail_cb=ttk.Combobox(row,state='readonly',justify='right',width=18,
               values=[_v('بدون تفصیلی')]+[_v(d['code']+' | '+d['title']) for d in details])
        detail_cb.current(0);detail_cb.pack(side='right',padx=4)
        debit=tk.Entry(row,width=13,justify='right');debit.insert(0,'0');debit.pack(side='right',ipady=6,padx=3)
        credit=tk.Entry(row,width=13,justify='right');credit.insert(0,'0');credit.pack(side='right',ipady=6,padx=3)
        self._label(row,'بدهکار',9,MUTED,bg=WHITE).pack(side='right')
        self._label(row,' / بستانکار',9,MUTED,bg=WHITE).pack(side='right')
        lines_card=self._card(self.content);lines_card.pack(fill='both',expand=True,pady=10)
        line_table=self._make_table(lines_card,[('n','ردیف'),('account','حساب'),('detail','شناور'),('debit','بدهکار (ریال)'),('credit','بستانکار (ریال)')],[50,180,125,130,130],height=7)
        totals=self._label(self.content,'جمع بدهکار: ۰    |    جمع بستانکار: ۰',10,TEXT,True)
        totals.pack(anchor='e',pady=(1,8))
        def fill_table():
            for x in line_table.get_children():line_table.delete(x)
            for n,line in enumerate(self.lines,1):
                account=next(a for a in accs if a['id']==line['account_id'])
                detail=next((d['title'] for d in details if d['id']==line.get('detail_id')),'—')
                line_table.insert('','end',iid=str(n-1),values=(n,_v(account['code']+' - '+account['title']),_v(detail),fmt_rial(line['debit']),fmt_rial(line['credit'])))
            totals.config(text=_v('جمع بدهکار: {} ریال   |   جمع بستانکار: {} ریال'.format(fmt_rial(sum(x['debit'] for x in self.lines)),fmt_rial(sum(x['credit'] for x in self.lines)))))
        fill_table()
        def add_line():
            try:
                d,c=rial_number(debit.get()),rial_number(credit.get())
                if (d>0)==(c>0):raise AccountingError('در هر ردیف فقط یک سمت مبلغ مثبت داشته باشد.')
                self.lines.append({'account_id':accs[acc_cb.current()]['id'],'detail_id':details[detail_cb.current()-1]['id'] if detail_cb.current()>0 else None,'debit':d,'credit':c})
                debit.delete(0,'end');debit.insert(0,'0');credit.delete(0,'end');credit.insert(0,'0')
                fill_table()
            except Exception as e:self._error(e)
        self._button(row,'افزودن ردیف',add_line,True).pack(side='right',padx=5)
        controls=tk.Frame(self.content,bg=BG);controls.pack(fill='x',pady=5)
        def remove_line():
            chosen=line_table.selection()
            if chosen:
                del self.lines[int(chosen[0])];fill_table()
        def save(post=False):
            try:
                if post and (len(self.lines)<2 or sum(x['debit']-x['credit'] for x in self.lines)!=0):
                    raise AccountingError('برای قطعی‌کردن سند حداقل دو ردیف و تراز بدهکار و بستانکار لازم است.')
                if correction_of is not None:
                    if not post:raise AccountingError('اصلاح سند قطعی باید هم‌زمان با سند برگشت و جایگزین ثبت شود.')
                    result=self.store.correct_posted(self.company_id,correction_of,day.get(),desc.get(),self.lines)
                    messagebox.showinfo('اصلاح موفق','سند برگشت {} و سند جایگزین {} ثبت شدند.'.format(result['reversal_id'],result['corrected_id']))
                    self.show('فهرست اسناد');return
                if as_adjustment:
                    if not post:raise AccountingError('سند اصلاحی باید با شرح کافی به‌صورت قطعی ثبت شود.')
                    doc_id=self.store.create_adjustment(self.company_id,self.year_id,day.get(),desc.get(),self.lines)
                    messagebox.showinfo('ثبت اصلاح','سند اصلاحی شماره {} قطعی شد.'.format(doc_id))
                    self.show('فهرست اسناد');return
                if editing:
                    doc_id=editing['id']
                    self.store.replace_draft(self.company_id,doc_id,day.get(),desc.get(),self.lines)
                else:
                    doc_id=self.store.new_draft(self.company_id,self.year_id,day.get(),desc.get(),self.lines)
                if post:self.store.post(self.company_id,doc_id)
                messagebox.showinfo('ثبت موفق','سند شماره {} {} شد.'.format(doc_id,'قطعی' if post else 'پیش‌نویس'))
                self.show('فهرست اسناد')
            except Exception as e:self._error(e)
        self._button(controls,'ثبت و قطعی‌کردن',lambda:save(True),True).pack(side='right',padx=5)
        if not as_adjustment and correction_of is None:
            self._button(controls,'ذخیره تغییرات پیش‌نویس' if editing else 'ذخیره پیش‌نویس',lambda:save(False)).pack(side='right',padx=5)
        self._button(controls,'حذف ردیف انتخابی',remove_line).pack(side='right',padx=5)
        self._label(controls,'تراز سند و اعتبار حساب‌ها پیش از ثبت قطعی کنترل می‌شوند.',9,MUTED).pack(side='left',pady=6)

    def page_journals(self):
        self._clear('فهرست اسناد','کنترل، قطعی‌کردن و برگشت سند حسابداری')
        if not self.company_id or not self.year_id:return self._warning()
        docs=self.store.journals(self.company_id,self.year_id)
        card=self._card(self.content);card.pack(fill='both',expand=True)
        table=self._make_table(card,[('serial','شماره'),('date','تاریخ شمسی'),('desc','شرح'),('status','وضعیت'),('total','جمع بدهکار (ریال)')],[65,100,250,95,165])
        for d in docs:table.insert('','end',iid=str(d['id']),values=(d['serial_no'],display_jalali(d['entry_date']),_v(d['description']),_v('قطعی' if d['status']=='posted' else 'پیش‌نویس'),fmt_rial(d['total'])))
        bar=tk.Frame(self.content,bg=BG);bar.pack(fill='x',pady=12)
        def selected_doc():
            chosen=table.selection()
            if not chosen: raise AccountingError('ابتدا یک سند انتخاب کنید.')
            return int(chosen[0])
        def details():
            try:
                item=self.store.journal(self.company_id,selected_doc())
                text='شماره سند: {}\nتاریخ: {}\nشرح: {}\nوضعیت: {}\n\n'.format(item['serial_no'],display_jalali(item['entry_date']),item['description'],item['status'])
                for l in item['lines']:
                    text+='{} | {} | بدهکار: {} | بستانکار: {}\n'.format(l['code'],l['title'],fmt_rial(l['debit_rial']),fmt_rial(l['credit_rial']))
                messagebox.showinfo('جزئیات سند',text)
            except Exception as e:self._error(e)
        def post():
            try:
                ident=selected_doc()
                if messagebox.askyesno('قطعی‌کردن','آیا سند انتخابی قطعی شود؟'):
                    self.store.post(self.company_id,ident);self.page_journals()
            except Exception as e:self._error(e)
        def reverse():
            try:
                ident=selected_doc()
                if messagebox.askyesno('برگشت سند','آیا سند برگشتی با تاریخ امروز ثبت شود؟'):
                    self.store.reverse(self.company_id,ident,display_jalali(date.today()),'برگشت سند شماره {}'.format(ident))
                    self.page_journals()
            except Exception as e:self._error(e)
        self._button(bar,'جزئیات سند',details).pack(side='right',padx=4)
        def edit():
            try:
                ident=selected_doc()
                selected=self.store.journal(self.company_id,ident)
                if selected['status']!='draft':
                    raise AccountingError('سند قطعی قابل ویرایش نیست.')
                self.page_journal_form(ident)
            except Exception as e:self._error(e)
        self._button(bar,'ویرایش پیش‌نویس',edit).pack(side='right',padx=4)
        self._button(bar,'قطعی‌کردن پیش‌نویس',post,True).pack(side='right',padx=4)
        self._button(bar,'صدور سند برگشت',reverse).pack(side='right',padx=4)
        def correct():
            try:self.page_journal_form(correction_of=selected_doc())
            except Exception as e:self._error(e)
        self._button(bar,'اصلاح کنترل‌شده سند',correct).pack(side='right',padx=4)

    def page_trial(self):
        self._clear('تراز آزمایشی چندستونی', 'فقط اسناد قطعی؛ گزارش تفکیکی در سطح گروه، کل، معین و تفصیلی')
        if not self.company_id or not self.year_id:
            return self._warning()
        bar = self._card(self.content); bar.pack(fill='x', pady=(0, 8))
        filters = tk.Frame(bar, bg=WHITE); filters.pack(fill='x', padx=10, pady=8)
        self._label(filters, 'سطح', 9, bg=WHITE).pack(side='right', padx=4)
        levels = ttk.Combobox(filters, state='readonly', width=12,
                              values=[_v(x) for x in ('گروه', 'کل', 'معین', 'تفصیلی')])
        levels.current(3); levels.pack(side='right', padx=4)
        self._label(filters, 'تعداد ستون', 9, bg=WHITE).pack(side='right', padx=4)
        col_choice = ttk.Combobox(filters, state='readonly', width=7, values=('2', '4', '6', '8'))
        col_choice.current(2); col_choice.pack(side='right', padx=4)
        fiscal = self.year_items[self.year_cb.current()]
        self._label(filters, 'از تاریخ', 9, bg=WHITE).pack(side='right', padx=4)
        first = tk.Entry(filters, justify='right', width=12)
        first.insert(0, display_jalali(fiscal['start_date'])); first.pack(side='right', padx=4)
        self._label(filters, 'تا تاریخ', 9, bg=WHITE).pack(side='right', padx=4)
        last = tk.Entry(filters, justify='right', width=12)
        last.insert(0, display_jalali(fiscal['end_date'])); last.pack(side='right', padx=4)
        card = self._card(self.content); card.pack(fill='both', expand=True)
        summary = self._label(self.content, '', 10, fg=MUTED)
        summary.pack(anchor='e', pady=7)
        current = {'rows': []}

        def opts():
            return dict(level=levels.current()+1, columns=int(col_choice.get()),
                        start_jalali=first.get().strip(), end_jalali=last.get().strip())

        def refresh():
            try:
                report = self.store.trial_balance_detailed(self.company_id, self.year_id, **opts())
                fields = self.store._trial_headers(report['columns'])
                for widget in card.winfo_children():
                    widget.destroy()
                cols = [('code', 'کد حساب'), ('title', 'عنوان')] + fields
                widths = [100, 200] + [150]*len(fields)
                table = self._make_table(card, cols, widths, height=17)
                for row in report['rows']:
                    table.insert('', 'end', values=tuple([row['code'], _v(row['title'])] +
                        [fmt_rial(row[key]) for key, _ in fields]))
                current['rows'] = report['rows']
                total_debit = sum(x['closing_debit'] for x in report['rows'])
                total_credit = sum(x['closing_credit'] for x in report['rows'])
                summary.configure(text=_v('جمع مانده بدهکار: {} ریال | جمع مانده بستانکار: {} ریال'.format(
                    fmt_rial(total_debit), fmt_rial(total_credit))),
                    fg=GOOD if total_debit == total_credit else '#bb3535')
            except Exception as exc:
                self._error(exc)

        def export(kind):
            ext = '.csv' if kind == 'csv' else '.html'
            path = filedialog.asksaveasfilename(title='ذخیره تراز آزمایشی', defaultextension=ext,
                    filetypes=[('CSV', '*.csv')] if kind == 'csv' else [('HTML', '*.html')])
            if not path:
                return
            try:
                method = (self.store.export_trial_detailed_csv if kind == 'csv'
                          else self.store.export_trial_detailed_html)
                method(self.company_id, self.year_id, path, **opts())
                messagebox.showinfo('ذخیره شد', 'گزارش با موفقیت ذخیره شد.')
            except Exception as exc:
                self._error(exc)
        self._button(filters, 'نمایش گزارش', refresh, True).pack(side='right', padx=4)
        self._button(filters, 'CSV / Excel', lambda: export('csv')).pack(side='right', padx=4)
        self._button(filters, 'چاپ HTML', lambda: export('html')).pack(side='right', padx=4)
        refresh()

    def page_ledger(self):
        self._clear('دفتر حساب کل، معین و تفصیلی',
                    'گردش اسناد قطعی، مانده ابتدای بازه و مانده جاری؛ انتخاب حساب در هر سطح')
        if not self.company_id or not self.year_id:return self._warning()
        accounts=self.store.accounts(self.company_id)
        if not accounts:return self._warning('ابتدا کدینگ حساب را تعریف کنید.')
        control=self._card(self.content);control.pack(fill='x')
        row=tk.Frame(control,bg=WHITE);row.pack(fill='x',padx=12,pady=12)
        self._label(row,'حساب',9,bg=WHITE).pack(side='right',padx=6)
        choose=ttk.Combobox(row,values=[_v(a['code']+' | '+a['title']) for a in accounts],
                            state='readonly',justify='right',width=32)
        choose.current(0);choose.pack(side='right',padx=3)
        self._label(row,'از',9,bg=WHITE).pack(side='right',padx=4)
        first=tk.Entry(row,justify='right',width=12);first.insert(0,display_jalali(self.year_items[self.year_cb.current()]['start_date']));first.pack(side='right')
        self._label(row,'تا',9,bg=WHITE).pack(side='right',padx=4)
        last=tk.Entry(row,justify='right',width=12);last.insert(0,display_jalali(self.year_items[self.year_cb.current()]['end_date']));last.pack(side='right')
        summary=self._label(self.content,'حساب را انتخاب کنید و گزارش را نمایش دهید.',10,fg=MUTED)
        summary.pack(anchor='e',pady=8)
        card=self._card(self.content);card.pack(fill='both',expand=True)
        table=self._make_table(card,[('day','تاریخ'),('num','شماره'),('account','حساب'),('desc','شرح'),
                                      ('debit','بدهکار'),('credit','بستانکار'),('dbal','مانده بد'),('cbal','مانده بس')],
                               [90,55,120,170,110,110,110,110],height=13)
        def get_report():
            return self.store.ledger(self.company_id,self.year_id,accounts[choose.current()]['id'],first.get(),last.get())
        def refresh():
            try:
                rpt=get_report()
                for item in table.get_children():table.delete(item)
                for row in rpt['rows']:
                    table.insert('','end',values=(display_jalali(row['entry_date']),row['serial_no'],
                        _v(row['account_code']),_v(row['description']),fmt_rial(row['debit']),fmt_rial(row['credit']),
                        fmt_rial(max(row['balance'],0)),fmt_rial(max(-row['balance'],0))))
                summary.config(text=_v('مانده ابتدای بازه: {} | گردش بدهکار: {} | گردش بستانکار: {} | مانده پایان: {} ریال (بدهکار - بستانکار)'.format(
                    fmt_rial(rpt['opening']),fmt_rial(rpt['debit']),fmt_rial(rpt['credit']),fmt_rial(rpt['closing']))))
            except Exception as e:self._error(e)
        def export():
            try:
                rpt=get_report()
                path=filedialog.asksaveasfilename(title='خروجی دفتر حساب',defaultextension='.csv',
                                                    filetypes=[('CSV','*.csv')],initialfile='daftar.csv')
                if path:
                    self.store.export_ledger_csv(self.company_id,self.year_id,rpt['account']['id'],path,first.get(),last.get())
                    messagebox.showinfo('خروجی','فایل دفتر حساب ذخیره شد.')
            except Exception as e:self._error(e)
        self._button(row,'نمایش',refresh,True).pack(side='right',padx=5)
        self._button(row,'خروجی CSV',export).pack(side='right',padx=4)
        def export_print():
            try:
                rpt=get_report()
                path=filedialog.asksaveasfilename(title='نسخه چاپی دفتر حساب',defaultextension='.html',
                    filetypes=[('HTML','*.html')],initialfile='daftar_hesab.html')
                if path:
                    self.store.export_ledger_html(self.company_id,self.year_id,rpt['account']['id'],
                                                  path,first.get(),last.get())
                    messagebox.showinfo('ذخیره شد','گزارش چاپی HTML ساخته شد؛ با مرورگر باز و چاپ کنید.')
            except Exception as e:self._error(e)
        self._button(row,'چاپ HTML',export_print).pack(side='right',padx=4)
        refresh()

    def page_statements(self):
        self._clear('صورت‌های مالی اولیه','فقط اسناد قطعی؛ نتیجه دوره بدون بستن حساب‌های موقت لحاظ شده است')
        if not self.company_id or not self.year_id:return self._warning()
        try:
            report=self.store.statements(self.company_id,self.year_id)
        except Exception as e:
            self._warning(str(e)+'  — برای اصلاح به کدینگ حساب‌ها بروید.',target='کدینگ حساب‌ها')
            return
        ctl=tk.Frame(self.content,bg=BG);ctl.pack(fill='x',pady=(0,8))
        def export():
            path=filedialog.asksaveasfilename(title='صورت‌های مالی',defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='sorat_mali.csv')
            if path:
                try:
                    self.store.export_statements_csv(self.company_id,self.year_id,path)
                    messagebox.showinfo('ذخیره شد','گزارش ذخیره شد.')
                except Exception as e:self._error(e)
        self._button(ctl,'خروجی CSV برای اکسل',export,True).pack(side='right')
        def export_print():
            path=filedialog.asksaveasfilename(title='نسخه چاپی صورت‌های مالی',defaultextension='.html',
                    filetypes=[('HTML','*.html')],initialfile='sorat_mali.html')
            if path:
                try:
                    self.store.export_statement_html(self.company_id,self.year_id,path)
                    messagebox.showinfo('ذخیره شد','گزارش چاپی HTML ساخته شد؛ با مرورگر باز و چاپ کنید.')
                except Exception as e:self._error(e)
        self._button(ctl,'نسخه چاپی HTML',export_print).pack(side='right',padx=5)
        tabs=ttk.Notebook(self.content)
        tabs.pack(fill='both',expand=True)
        def tab(label,sections,totals):
            body=tk.Frame(tabs,bg=WHITE)
            tabs.add(body,text=_v(label))
            tbl=self._make_table(body,[('code','کد'),('name','عنوان حساب'),('value','مبلغ (ریال)')],
                                 [100,350,160],height=12)
            for key,section_label in sections:
                tbl.insert('','end',values=('',_v(section_label),''),tags=('group',))
                for item in report[key]['items']:
                    tbl.insert('','end',values=(item['code'],_v('    '+item['title']),fmt_rial(item['amount'])))
                tbl.insert('','end',values=('',_v('جمع '+section_label),fmt_rial(report[key]['total'])),tags=('total',))
            for name,val in totals:
                tbl.insert('','end',values=('',_v(name),fmt_rial(val)),tags=('total',))
            tbl.tag_configure('group',background='#ecf2fa')
            tbl.tag_configure('total',background='#e8f4ed')
        tab('سود و زیان',[('revenue','درآمد'),('costs','بهای تمام‌شده'),('expenses','هزینه')],
            [('سود / زیان دوره',report['net_profit'])])
        tab('ترازنامه',[('assets','دارایی'),('liabilities','بدهی'),('equity','حقوق مالکانه')],
            [('سود / زیان دوره (در حقوق مالکانه)',report['net_profit']),
             ('جمع بدهی و حقوق مالکانه',report['balance_total']),
             ('اختلاف ترازنامه',report['balance_difference'])])
        self._label(self.content,'این گزارش اولیه است؛ طبقه‌بندی حساب‌ها و عملیات اختتامیه باید توسط حسابدار کنترل شود.',9,MUTED).pack(anchor='e',pady=6)

    def page_future(self):
        self._clear('نقشه سیستم‌های تکمیلی','این سیستم‌ها هنوز ساخته نشده‌اند و در مراحل بعد توسعه می‌یابند')
        frame=self._card(self.content);frame.pack(fill='both',expand=True)
        modules=['دریافت و پرداخت','خرید و فروش','انبارداری','سامانه مؤدیان','حقوق و دستمزد','دارایی ثابت','تولید','پیمانکاری','پخش مویرگی','سفارشات خارجی','بودجه و مدیریت']
        for name in modules:
            r=tk.Frame(frame,bg=WHITE);r.pack(fill='x',padx=23,pady=8)
            self._label(r,name,10,TEXT,True,bg=WHITE).pack(side='right')
            self._label(r,'در برنامه توسعه — هنوز فعال نیست',9,MUTED,bg=WHITE).pack(side='left')
            tk.Frame(frame,height=1,bg='#e6eaf0').pack(fill='x',padx=23)

    def _error(self,exc):
        messagebox.showerror('خطای عملیات',str(exc))

    def run(self):
        self.root.mainloop()
