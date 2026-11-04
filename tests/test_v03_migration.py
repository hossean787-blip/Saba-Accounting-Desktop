import unittest
import tempfile
import sqlite3
from pathlib import Path
from contextlib import closing
from saba_accounting.erp import ERPStore
from saba_accounting.finance import FinanceStore
from saba_accounting.demo_erp import seed_erp_demo

class CompatibilityTests(unittest.TestCase):
    def test_upgrade_from_v03_preserves_documents_and_creates_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'data.sqlite3'
            old=ERPStore(path)
            c,y=seed_erp_demo(old)
            before=old.dashboard(c,y)
            posted=len(old.journals(c,y))
            with closing(sqlite3.connect(str(path))) as conn:
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],3)
            new=FinanceStore(path)
            self.assertEqual(new.dashboard(c,y),before)
            self.assertEqual(len(new.journals(c,y)),posted)
            self.assertEqual(new._read_one('PRAGMA integrity_check')['integrity_check'],'ok')
            self.assertTrue(path.with_suffix('.pre_v04.sqlite3').exists())
            self.assertEqual(new._read_one('PRAGMA user_version')['user_version'],4)
            # Reopening must preserve data and v0.4 user version.
            new2=FinanceStore(path)
            self.assertEqual(new2.dashboard(c,y),before)
