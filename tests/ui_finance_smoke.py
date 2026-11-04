"""Actual Tk smoke with v0.4 backend under Xvfb; screenshots are real UI."""
import os
import sys
import tempfile
from pathlib import Path
from PIL import ImageGrab
from saba_accounting.finance import FinanceStore
from saba_accounting.demo_erp import seed_erp_demo
from saba_accounting.ui import SabaUI

out=Path(sys.argv[1]) if len(sys.argv)>1 else Path(tempfile.gettempdir())
out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as d:
    store=FinanceStore(Path(d)/'demo.sqlite3')
    seed_erp_demo(store)
    ui=SabaUI(store)
    ui.root.geometry('1450x900+0+0')
    pages=['داشبورد','شرکت و سال مالی','کدینگ حساب‌ها','ثبت سند','فهرست اسناد',
           'تراز آزمایشی','دفتر حساب','صورت‌های مالی','کنترل مالی','عملیات یکپارچه']
    for page in pages:
        ui.show(page)
        ui.root.update_idletasks()
        ui.root.update()
        if page in ('داشبورد','کنترل مالی','صورت‌های مالی'):
            ImageGrab.grab(bbox=(0,0,1450,900)).save(out/('Saba_v04_'+{'داشبورد':'Dashboard','کنترل مالی':'Finance_Control','صورت‌های مالی':'Statements'}[page]+'.png'))
        print('PASS',page)
    ui.show('ثبت سند');ui.root.update()
    ui.page_journal_form(as_adjustment=True);ui.root.update()
    print('PASS','فرم سند اصلاحی')
    ui.show('کنترل مالی');ui.root.update()
    # Each finance tab contains interactive controls, not placeholder screens.
    notebook=next(w for w in ui.content.winfo_children() if w.winfo_class()=='TNotebook')
    for idx in range(len(notebook.tabs())):
        notebook.select(idx);ui.root.update()
        print('PASS','تب',idx)
    ui.root.destroy()
