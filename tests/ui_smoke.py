import os
import tempfile
from pathlib import Path
from saba_accounting.storage import AccountingStore
from saba_accounting.demo import seed_demo
from saba_accounting.ui import SabaUI

with tempfile.TemporaryDirectory() as p:
    s=AccountingStore(Path(p)/'demo.sqlite3')
    seed_demo(s)
    ui=SabaUI(s)
    ui.root.update()
    for page in ('داشبورد','فهرست اسناد','کدینگ حساب‌ها','دفتر حساب','صورت‌های مالی','ثبت سند','تراز آزمایشی'):
        ui.show(page)
        ui.root.update()
        print('OK UI page:',page)
    draft=[x for x in s.journals(ui.company_id,ui.year_id) if x['status']=='draft'][0]
    ui.page_journal_form(draft['id'])
    ui.root.update()
    assert len(ui.lines)==2
    print('OK edit draft UI:',draft['id'])
    ui.root.destroy()
