"""Regression tests derived from the independent 0.6.5 audit handoff."""
import concurrent.futures
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from saba_accounting.access import (AuthorizedStore, PermissionDenied,
                                    PUBLIC_METHOD_PERMISSIONS, UserManager)
from saba_accounting.finance import FinanceStore
from saba_accounting.storage import AccountingError, AccountingStore


def _concurrent_draft(args):
    """Top-level worker remains importable by Windows multiprocessing spawn."""
    path, company, year, debit, credit, number = args
    store = AccountingStore(path)
    return store.new_draft(company, year, "1405/02/01", f"worker-{number}", [
        {"account_id": debit, "debit": number + 1, "credit": 0},
        {"account_id": credit, "debit": 0, "credit": number + 1},
    ])


class InsertLineSchemaTests(unittest.TestCase):
    def test_schema_is_inspected_once_for_many_lines_old_and_new(self):
        for has_detail in (False, True):
            with self.subTest(has_detail=has_detail), closing(sqlite3.connect(":memory:")) as conn:
                conn.row_factory = sqlite3.Row
                detail = ", detail_id INTEGER" if has_detail else ""
                conn.execute("CREATE TABLE journal_lines (entry_id INTEGER, account_id INTEGER, "
                             "row_no INTEGER, debit_rial INTEGER, credit_rial INTEGER, "
                             "narration TEXT, party_id INTEGER, cost_center_id INTEGER" + detail + ")")
                statements = []
                conn.set_trace_callback(statements.append)
                lines = [
                    {"account_id": i + 1, "debit": i + 1, "credit": 0,
                     "detail_id": 10 if has_detail else None}
                    for i in range(50)
                ]
                AccountingStore._insert_lines(conn, 1, lines)
                pragma_count = sum("PRAGMA table_info(journal_lines)" in sql for sql in statements)
                self.assertEqual(1, pragma_count)
                self.assertEqual(50, conn.execute("SELECT COUNT(*) FROM journal_lines").fetchone()[0])
                if has_detail:
                    self.assertEqual(10, conn.execute("SELECT detail_id FROM journal_lines LIMIT 1").fetchone()[0])


class ConcurrentJournalTests(unittest.TestCase):
    def test_multiple_processes_get_unique_serials_without_partial_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "concurrent.sqlite3")
            store = AccountingStore(path)
            company = store.create_company("هم‌زمانی")
            year = store.create_fiscal_year(company, "1405", "1405/01/01", "1405/12/29")
            debit = self._account(store, company, "1", "دارایی")
            credit = self._account(store, company, "3", "سرمایه")
            jobs = [(path, company, year, debit, credit, n) for n in range(12)]
            with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
                ids = list(pool.map(_concurrent_draft, jobs, timeout=60))
            self.assertEqual(12, len(set(ids)))
            with closing(store._connection()) as conn:
                serials = [row[0] for row in conn.execute(
                    "SELECT serial_no FROM journal_entries ORDER BY serial_no")]
                self.assertEqual(list(range(1, 13)), serials)
                self.assertEqual([], conn.execute(
                    "SELECT j.id FROM journal_entries j LEFT JOIN journal_lines l ON l.entry_id=j.id "
                    "GROUP BY j.id HAVING COUNT(l.id)<>2").fetchall())
                self.assertEqual("ok", conn.execute("PRAGMA integrity_check").fetchone()[0])

    @staticmethod
    def _account(store, company, prefix, title):
        parent = None
        for level, code in enumerate((prefix, prefix + "1", prefix + "101", prefix + "10101"), 1):
            parent = store.create_account(company, code, title, level, parent_id=parent,
                                          is_postable=level == 4)
        return parent


class ScopeAndPermissionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = FinanceStore(self.root / "scope.sqlite3")
        self.c1 = self.store.create_company("شرکت الف")
        self.c2 = self.store.create_company("شرکت ب")
        self.y1 = self.store.create_fiscal_year(self.c1, "1405", "1405/01/01", "1405/12/29")
        self.y2 = self.store.create_fiscal_year(self.c2, "1405", "1405/01/01", "1405/12/29")
        self.a1 = ConcurrentJournalTests._account(self.store, self.c1, "1", "صندوق الف")

    def test_company_year_mismatch_is_rejected_by_all_financial_reports(self):
        calls = [
            lambda: self.store.trial_balance(self.c1, self.y2),
            lambda: self.store.trial_balance_detailed(self.c1, self.y2),
            lambda: self.store.trial_balance_levels(self.c1, self.y2),
            lambda: self.store.trial_balance_six(self.c1, self.y2),
            lambda: self.store.dashboard(self.c1, self.y2),
            lambda: self.store.ledger(self.c1, self.y2, self.a1),
            lambda: self.store.statements(self.c1, self.y2),
            lambda: self.store.general_journal(self.c1, self.y2),
            lambda: self.store.reconcile_accounting_reports(self.c1, self.y2),
            lambda: self.store.full_integrity_report(self.c1, self.y2),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(AccountingError):
                call()

    def test_viewer_is_denied_every_sensitive_public_operation(self):
        users = UserManager(self.store.path)
        users.bootstrap_admin("admin", "Admin-passphrase-123")
        admin = users.authenticate("admin", "Admin-passphrase-123")
        users.create_user(admin, "viewer", "Viewer-passphrase-123", "بازرس", "viewer")
        viewer = AuthorizedStore(self.store, users.authenticate("viewer", "Viewer-passphrase-123"))
        sensitive = {name for name, permission in PUBLIC_METHOD_PERMISSIONS.items()
                     if permission != "read"}
        for name in sorted(sensitive):
            with self.subTest(method=name), self.assertRaises(PermissionDenied):
                getattr(viewer, name)()

    def test_plain_backup_never_overwrites_an_existing_file(self):
        destination = self.root / "existing.sqlite3"
        destination.write_bytes(b"KEEP-THIS-FILE")
        with self.assertRaises(AccountingError):
            self.store.backup(destination)
        self.assertEqual(b"KEEP-THIS-FILE", destination.read_bytes())

    def test_financial_statement_exports_are_explicitly_non_legal(self):
        html = self.root / "statements.html"
        csv_path = self.root / "statements.csv"
        self.store.export_statement_html(self.c1, self.y1, html)
        self.store.export_statements_csv(self.c1, self.y1, csv_path)
        html_text = html.read_text(encoding="utf-8")
        csv_text = csv_path.read_text(encoding="utf-8-sig")
        self.assertIn("صورت‌های مالی داخلی", html_text)
        self.assertIn("برای استفاده رسمی", html_text)
        self.assertIn("گزارش اولیه صورت‌های مالی", csv_text)


if __name__ == "__main__":
    unittest.main()
