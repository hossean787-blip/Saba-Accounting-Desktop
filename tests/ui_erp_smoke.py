import tempfile
from pathlib import Path
from saba_accounting.erp import ERPStore
from saba_accounting.demo import seed_demo
from saba_accounting.ui import SabaUI

with tempfile.TemporaryDirectory() as p:
    store=ERPStore(Path(p)/'demo.db')
    seed_demo(store)
    ui=SabaUI(store)
    ui.show('عملیات یکپارچه')
    ui.root.update()
    # Find the action selector and visit each operation in the desktop app.
    from tkinter import ttk
    comboboxes=[]
    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child,ttk.Combobox):comboboxes.append(child)
            walk(child)
    walk(ui.content)
    actions=next(c for c in comboboxes if 'نگاشت حساب سیستمی' in c.cget('values'))
    for i,action in enumerate(actions.cget('values')):
        actions.current(i)
        actions.event_generate('<<ComboboxSelected>>')
        ui.root.update()
        print('PASS UI',action)
    actions.current(0);actions.event_generate('<<ComboboxSelected>>');ui.root.update()
    ui.root.after(300,ui.root.destroy)
    ui.root.mainloop()
