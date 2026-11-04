import os
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from contextlib import closing
from saba_accounting.access import (AuthorizedStore, LoginError, PermissionDenied,
                                    UserManager, configured, legacy_login_allowed, set_password,
                                    verify_password)
from saba_accounting.finance import FinanceStore

class LocalLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'data.sqlite3'
        self.store=FinanceStore(self.db)

    def test_not_configured_by_default(self):
        self.assertFalse(configured(self.db))
        self.assertFalse(verify_password(self.db,'anything'))

    def test_login_and_wrong_password(self):
        set_password(self.db,'secret pass 123456')
        self.assertTrue(configured(self.db))
        self.assertTrue(verify_password(self.db,'secret pass 123456'))
        self.assertFalse(verify_password(self.db,'wrong pass 123456'))
        with closing(sqlite3.connect(self.db)) as conn:
            row=conn.execute('SELECT salt,secret FROM local_login').fetchone()
            self.assertNotIn(b'secret pass 123456',row)

    def test_change_requires_current_password(self):
        set_password(self.db,'old secret pass 123')
        with self.assertRaises(LoginError):set_password(self.db,'new secret pass 123','wrong')
        self.assertTrue(verify_password(self.db,'old secret pass 123'))
        set_password(self.db,'new secret pass 123','old secret pass 123')
        self.assertFalse(verify_password(self.db,'old secret pass 123'))
        self.assertTrue(verify_password(self.db,'new secret pass 123'))

    def test_legacy_password_is_rejected_after_named_user_bootstrap(self):
        set_password(self.db, 'shared-password-123')
        self.assertTrue(legacy_login_allowed(self.db))
        self.assertTrue(verify_password(self.db, 'shared-password-123'))
        users = UserManager(self.db)
        users.bootstrap_admin('admin', 'Admin-passphrase-123')
        self.assertFalse(legacy_login_allowed(self.db))
        self.assertFalse(verify_password(self.db, 'shared-password-123'))
        with self.assertRaises(LoginError):
            set_password(self.db, 'other-shared-password', 'shared-password-123')
        self.assertEqual('admin', users.authenticate('admin', 'Admin-passphrase-123').username)

    def test_short_password_rejected_and_accounting_untouched(self):
        with self.assertRaises(LoginError):set_password(self.db,'too short')
        company=self.store.create_company('شرکت')
        self.assertEqual(self.store.companies()[0]['id'],company)

class RoleAndSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'roles.sqlite3'
        self.store=FinanceStore(self.db)
        self.users=UserManager(self.db)
        self.users.bootstrap_admin('admin','Admin-passphrase-123')
        self.admin=self.users.authenticate('ADMIN','Admin-passphrase-123')

    def test_role_facade_rejects_private_database_access(self):
        wrapped = AuthorizedStore(self.store, self.admin)
        with self.assertRaises(AttributeError):
            wrapped._connection()
        with self.assertRaises(AttributeError):
            wrapped._read_all('SELECT * FROM app_users')
        company = wrapped.create_company('مجاز')
        self.assertEqual(company, wrapped.companies()[0]['id'])

    def test_erp_selector_respects_role_and_company(self):
        wrapped = AuthorizedStore(self.store, self.admin)
        company = self.store.create_company('شرکت ۱')
        other = self.store.create_company('شرکت ۲')
        self.assertEqual([], wrapped.reference_choices(company, 'employees'))
        self.assertEqual([], wrapped.reference_choices(other, 'employees'))
        with self.assertRaises(ValueError):
            wrapped.reference_choices(company, 'app_users')

    def test_roles_enforced_in_business_layer(self):
        company=self.store.create_company('شرکت مجاز')
        year=self.store.create_fiscal_year(company,'1405','1405/01/01','1405/12/29')
        self.users.create_user(self.admin,'viewer','Viewer-passphrase-123','مشاهده‌گر','viewer')
        viewer=AuthorizedStore(self.store,self.users.authenticate('viewer','Viewer-passphrase-123'))
        self.assertEqual(company,viewer.companies()[0]['id'])
        self.assertIsInstance(viewer.dashboard(company,year),dict)
        with self.assertRaises(PermissionDenied):viewer.create_company('نباید ثبت شود')
        self.assertEqual(1,len(self.store.companies()))

    def test_accountant_cannot_manage_users(self):
        self.users.create_user(self.admin,'accountant','Accountant-pass-123','حسابدار','accountant')
        actor=self.users.authenticate('accountant','Accountant-pass-123')
        with self.assertRaises(PermissionDenied):
            self.users.create_user(actor,'x','Another-passphrase-123','کاربر','viewer')

    def test_lockout_and_security_log(self):
        for _ in range(5):
            with self.assertRaises(LoginError):self.users.authenticate('admin','wrong-password')
        with self.assertRaisesRegex(LoginError,'قفل'):
            self.users.authenticate('admin','Admin-passphrase-123')
        events=self.users.security_events(self.admin)
        self.assertGreaterEqual(sum(e['event_type']=='LOGIN' and not e['success'] for e in events),5)

    def test_expired_session_blocks_reads(self):
        self.admin._last_seen-=timedelta(minutes=31)
        with self.assertRaisesRegex(LoginError,'منقضی'):
            AuthorizedStore(self.store,self.admin).companies()

    def test_only_admin_reads_security_events(self):
        self.users.create_user(self.admin,'viewer','Viewer-passphrase-123','مشاهده‌گر','viewer')
        viewer=self.users.authenticate('viewer','Viewer-passphrase-123')
        with self.assertRaises(PermissionDenied):self.users.security_events(viewer)

    def test_own_password_change_requires_current_password(self):
        with self.assertRaisesRegex(LoginError, 'رمز فعلی'):
            self.users.change_password(self.admin, self.admin.user_id, 'New-admin-password-123')
        with self.assertRaisesRegex(LoginError, 'رمز فعلی'):
            self.users.change_password(self.admin, self.admin.user_id,
                                       'New-admin-password-123', current_password='wrong password')
        self.assertEqual('admin', self.users.authenticate('admin', 'Admin-passphrase-123').username)
        self.users.change_password(self.admin, self.admin.user_id,
                                   'New-admin-password-123', current_password='Admin-passphrase-123')
        with self.assertRaises(LoginError):
            AuthorizedStore(self.store, self.admin).companies()
        with self.assertRaises(LoginError):
            self.users.authenticate('admin', 'Admin-passphrase-123')
        self.assertEqual('admin', self.users.authenticate('admin', 'New-admin-password-123').username)

    def test_changed_role_revokes_existing_session(self):
        uid = self.users.create_user(self.admin, 'staff', 'Staff-passphrase-123', 'کارمند', 'accountant')
        session = self.users.authenticate('staff', 'Staff-passphrase-123')
        self.users.update_user(self.admin, uid, role='viewer')
        with self.assertRaisesRegex(LoginError, 'باطل'):
            AuthorizedStore(self.store, session).create_company('illegal')
        fresh = self.users.authenticate('staff', 'Staff-passphrase-123')
        with self.assertRaises(PermissionDenied):
            AuthorizedStore(self.store, fresh).create_company('illegal')

    def test_disabled_user_revokes_existing_session(self):
        uid = self.users.create_user(self.admin, 'staff', 'Staff-passphrase-123', 'کارمند', 'viewer')
        session = self.users.authenticate('staff', 'Staff-passphrase-123')
        self.users.update_user(self.admin, uid, is_active=False)
        with self.assertRaises(LoginError):
            AuthorizedStore(self.store, session).companies()
        with self.assertRaises(LoginError):
            self.users.authenticate('staff', 'Staff-passphrase-123')

    def test_admin_reset_revokes_existing_session(self):
        uid = self.users.create_user(self.admin, 'staff', 'Staff-passphrase-123', 'کارمند', 'viewer')
        old = self.users.authenticate('staff', 'Staff-passphrase-123')
        self.users.change_password(self.admin, uid, 'Reset-passphrase-123')
        with self.assertRaises(LoginError):
            AuthorizedStore(self.store, old).companies()
        self.assertEqual('staff', self.users.authenticate('staff', 'Reset-passphrase-123').username)

    def test_version_check_survives_new_manager_instance(self):
        uid = self.users.create_user(self.admin, 'staff', 'Staff-passphrase-123', 'کارمند', 'viewer')
        session = self.users.authenticate('staff', 'Staff-passphrase-123')
        another = UserManager(self.db)
        another.update_user(self.admin, uid, role='accountant')
        with self.assertRaises(LoginError):
            AuthorizedStore(self.store, session).companies()

    def test_user_lifecycle_and_last_admin_guard(self):
        ident=self.users.create_user(self.admin,'staff','Staff-passphrase-123','کارمند','viewer')
        self.assertEqual('viewer',[u for u in self.users.list_users(self.admin) if u['id']==ident][0]['role'])
        self.users.update_user(self.admin,ident,role='accountant')
        self.assertEqual('accountant',self.users.authenticate('staff','Staff-passphrase-123').role)
        self.users.change_password(self.admin,ident,'Changed-passphrase-123')
        with self.assertRaises(LoginError):self.users.authenticate('staff','Staff-passphrase-123')
        self.assertEqual('staff',self.users.authenticate('staff','Changed-passphrase-123').username)
        with self.assertRaisesRegex(LoginError,'آخرین مدیر'):
            self.users.update_user(self.admin,self.admin.user_id,is_active=False)

if __name__=='__main__':unittest.main()
