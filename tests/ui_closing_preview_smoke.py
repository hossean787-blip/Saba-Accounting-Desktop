"""Real Tk/Xvfb read-only closing-preview smoke on synthetic data."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from test_close_verification import YearEndVerificationTests
from saba_accounting.ui import SabaUI

case=YearEndVerificationTests(methodName='test_verify_close_and_opening_dimensions')
case.setUp()
try:
    case.seed()
    ui=SabaUI(case.store)
    ui.company_id=case.company
    ui.year_id=case.y1
    ui.show('کنترل مالی')
    ui.root.update()
    widgets=[]
    def visit(widget):
        widgets.append(widget)
        for child in widget.winfo_children():visit(child)
    visit(ui.content)
    comboboxes=[w for w in widgets if isinstance(w,ttk.Combobox)]
    assert len(comboboxes)>=2, 'Expected year and retained-account selectors'
    yearbox,retainedbox=comboboxes[:2]
    target_year=next(i for i,v in enumerate(yearbox['values']) if '1406' in v)
    yearbox.current(target_year)
    account_values=list(retainedbox['values'])
    target_account=next(i for i,v in enumerate(account_values) if v.split(' | ')[0] == case.store._read_one('SELECT code FROM accounts WHERE id=?',(case.retained,))['code'])
    retainedbox.current(target_account)
    buttons=[w for w in widgets if isinstance(w,tk.Button)]
    previewbutton=buttons[2]  # first action in closing-year pane
    previewbutton.invoke()
    ui.root.update()
    windows=[w for w in ui.root.winfo_children() if isinstance(w,tk.Toplevel)]
    assert len(windows)==1, 'Expected one preview dialog; got '+str(len(windows))
    notebooks=[w for w in windows[0].winfo_children() if isinstance(w,ttk.Notebook)]
    assert len(notebooks)==1 and len(notebooks[0].tabs())==3
    for tabid in notebooks[0].tabs():
        notebooks[0].select(tabid)
        ui.root.update()
        trees=[]
        visitwidgets=[]
        def walk(w):
            visitwidgets.append(w)
            for x in w.winfo_children():walk(x)
        walk(notebooks[0].nametowidget(tabid))
        trees=[w for w in visitwidgets if isinstance(w,ttk.Treeview)]
        assert len(trees)==1 and len(trees[0].get_children())>0
    assert not case.store.closure_info(case.company,case.y1)
    print('PASS GUI: all three journals rendered read-only; year remains open')
    windows[0].destroy()
    ui.root.destroy()
finally:
    case.doCleanups()
