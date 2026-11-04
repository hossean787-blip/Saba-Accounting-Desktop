"""Run with Python 3.8+ on Windows. No external pip packages needed."""
import argparse
import getpass
import sys
import os
import tempfile
from pathlib import Path

from saba_accounting.access import (AuthorizedStore, LoginError, UserManager,
                                    configured, set_password, verify_password, legacy_login_allowed)
from saba_accounting.finance import FinanceStore
from saba_accounting.demo_erp import seed_erp_demo
from saba_accounting.demo_finance import seed_finance_demo
from saba_accounting.ui import SabaUI


def default_database():
    root = os.environ.get('LOCALAPPDATA')
    if root:
        return Path(root) / 'SabaAccounting' / 'saba_ledger.sqlite3'
    return Path.home() / '.saba_accounting' / 'saba_ledger.sqlite3'


def main():
    parser=argparse.ArgumentParser(description='Saba Accounting independent prototype')
    parser.add_argument('--db',default=None,help='Path to sqlite database')
    parser.add_argument('--demo',action='store_true',help='Run sample data in a temporary database')
    parser.add_argument('--demo-finance',action='store_true',help='Demo ready for controlled year-end preview')
    parser.add_argument('--configure-login',action='store_true',help='Set or change local login password via terminal')
    parser.add_argument('--bootstrap-admin',action='store_true',help='Create the first named administrator')
    parser.add_argument('--verify-backup',metavar='FILE',help='Verify a backup and its SHA-256 receipt, then exit')
    parser.add_argument('--restore-backup',metavar='FILE',help='Recover a verified backup to a new database')
    parser.add_argument('--restore-to',metavar='FILE',help='Destination for --restore-backup (must not exist)')
    args=parser.parse_args()
    if args.verify_backup or args.restore_backup or args.restore_to:
        from saba_accounting.recovery import verify_backup, restore_to_new_database
        try:
            if args.verify_backup and not args.restore_backup and not args.restore_to:
                result = verify_backup(args.verify_backup)
                # ASCII remains reliable in redirected legacy Windows consoles.
                print('Backup verified; SHA-256:', result['sha256'])
                return
            if args.restore_backup and args.restore_to and not args.verify_backup:
                result = restore_to_new_database(args.restore_backup, args.restore_to)
                print('Backup restored to new database:', result['path'])
                return
            parser.error('برای بازیابی، هر دو گزینه --restore-backup و --restore-to لازم است.')
        except (OSError, ValueError) as exc:
            parser.exit(2, str(exc) + '\n')
    if args.demo or args.demo_finance:
        demo_dir=tempfile.TemporaryDirectory(prefix='saba_accounting_demo_')
        path=Path(demo_dir.name)/'demo.sqlite3'
    else:
        demo_dir=None
        path=Path(args.db) if args.db else default_database()
    try:
        store=FinanceStore(path)
        if args.bootstrap_admin:
            if not sys.stdin.isatty():
                raise SystemExit('ایجاد مدیر نیاز به ترمینال تعاملی دارد.')
            username = input('نام کاربری مدیر: ').strip()
            new = getpass.getpass('رمز مدیر (حداقل ۱۲ نویسه): ')
            repeat = getpass.getpass('تکرار رمز مدیر: ')
            if new != repeat:
                raise SystemExit('تکرار رمز مطابقت ندارد.')
            try:
                UserManager(path).bootstrap_admin(username, new)
            except LoginError as exc:
                raise SystemExit(str(exc))
            print('مدیر اولیه ایجاد شد.')
            return
        if args.configure_login:
            if not sys.stdin.isatty():
                raise SystemExit('تنظیم رمز نیاز به ترمینال تعاملی دارد.')
            if not legacy_login_allowed(path):
                raise SystemExit("در حالت چندکاربره تغییر رمز از ابزار مدیریت کاربران انجام می‌شود.")
            current = getpass.getpass('رمز فعلی: ') if configured(path) else None
            new = getpass.getpass('رمز جدید (حداقل ۱۲ نویسه): ')
            repeat = getpass.getpass('تکرار رمز جدید: ')
            if new != repeat:
                raise SystemExit('تکرار رمز مطابقت ندارد.')
            try:
                set_password(path,new,current)
            except LoginError as exc:
                raise SystemExit(str(exc))
            print('رمز ورود محلی تنظیم شد.')
            return
        session = None
        if configured(path) and not (args.demo or args.demo_finance):
            named_users = not legacy_login_allowed(path)
            import tkinter as tk
            from tkinter import simpledialog, messagebox
            root=tk.Tk();root.withdraw()
            try:
                authorized=False
                for _ in range(3):
                    username=simpledialog.askstring('حسابداری صبا','نام کاربری (برای ورود قدیمی خالی بگذارید):',parent=root)
                    if username is None:
                        return
                    if named_users and not username.strip():
                        messagebox.showerror('ورود ناموفق', 'در حالت چندکاربره نام کاربری الزامی است.', parent=root)
                        continue
                    entered=simpledialog.askstring('حسابداری صبا','رمز ورود:',show='*',parent=root)
                    if entered is None:
                        return
                    try:
                        if username.strip():
                            session=UserManager(path).authenticate(username,entered)
                            authorized=True
                            break
                        if not named_users and verify_password(path,entered):
                            authorized=True
                            break
                    except LoginError as exc:
                        messagebox.showerror('ورود ناموفق',str(exc),parent=root)
                        continue
                    messagebox.showerror('ورود ناموفق','رمز ورود نادرست است.',parent=root)
                if not authorized:
                    return
            finally:
                root.destroy()
        if args.demo:seed_erp_demo(store)
        financial=seed_finance_demo(store) if args.demo_finance else None
        if session is not None:
            store = AuthorizedStore(store, session)
        ui=SabaUI(store)
        if financial:
            ui.company_id=financial['company_id']
            ui.year_id=financial['current_year']
            ui.refresh_years()
            ui.show('کنترل مالی')
        ui.run()
    finally:
        if demo_dir:demo_dir.cleanup()


if __name__=='__main__':
    main()
