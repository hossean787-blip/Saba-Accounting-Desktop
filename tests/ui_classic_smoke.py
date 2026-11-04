"""Read-only GUI smoke for classic accounting layout, verified on virtual X display."""
import tempfile
import sys
from pathlib import Path
from PIL import ImageGrab
from saba_accounting.finance import FinanceStore
from saba_accounting.demo_erp import seed_erp_demo
from saba_accounting.ui import SabaUI

out=Path(sys.argv[1]) if len(sys.argv)>1 else Path('previews')
out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as d:
    store=FinanceStore(Path(d)/'preview.sqlite3')
    seed_erp_demo(store)
    ui=SabaUI(store)
    ui.root.geometry('1460x900+0+0')
    for mod in ('حسابداری','دریافت و پرداخت','مشتریان و فروش','تولید و پیمانکاری'):
        ui._select_module(mod,navigate=True)
        ui.root.update()
        assert ui.active_module==mod, mod
        print('PASS module',mod)
    ui._select_module('حسابداری',navigate=False)
    for page,output in [('داشبورد','Saba_v05_Desktop.png'),
                        ('ثبت سند','Saba_v05_Journal.png'),
                        ('فهرست اسناد','Saba_v05_Journals.png'),
                        ('کدینگ حساب‌ها','Saba_v05_Accounts.png'),
                        ('تراز آزمایشی','Saba_v05_Trial.png')]:
        ui.show(page)
        ui.root.update_idletasks()
        ui.root.update()
        assert ui.current_page==page, page
        assert ui.content.winfo_children(), 'empty workspace '+page
        ImageGrab.grab(bbox=(0,0,1460,900)).save(out/output)
        print('PASS page',page, output)
    ui.root.event_generate('<Control-n>')
    ui.root.update()
    assert ui.current_page=='ثبت سند', 'Ctrl+N should open journal'
    print('PASS hotkey Ctrl+N')
    ui.root.destroy()
