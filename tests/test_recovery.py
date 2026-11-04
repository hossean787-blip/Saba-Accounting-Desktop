"""Regression tests for verified recovery; never modify an existing target."""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from saba_accounting.finance import FinanceStore
from saba_accounting.recovery import restore_to_new_database, verify_backup
from saba_accounting.storage import AccountingError

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/'active.sqlite3'
        self.store=FinanceStore(self.db)
        self.store.create_company('شرکت آزمایشی')
        self.backup=self.root/'snapshot.sqlite3'
        self.store.verified_backup(self.backup)

    def test_verify_and_restore_preserves_accounting_data(self):
        self.assertTrue(verify_backup(self.backup)['sha256'])
        target=self.root/'recovered.sqlite3'
        restore_to_new_database(self.backup,target)
        with closing(sqlite3.connect(target)) as conn:
            self.assertEqual(conn.execute('SELECT name FROM companies').fetchone()[0],'شرکت آزمایشی')
        self.assertEqual(len(FinanceStore(target).companies()),1)

    def test_never_overwrite_destination(self):
        target=self.root/'recovered.sqlite3';target.write_bytes(b'IMPORTANT')
        with self.assertRaises(AccountingError):restore_to_new_database(self.backup,target)
        self.assertEqual(target.read_bytes(),b'IMPORTANT')

    def test_reject_tampered_backup(self):
        with self.backup.open('ab') as f:f.write(b'tampered')
        with self.assertRaises(AccountingError):verify_backup(self.backup)
        target=self.root/'recovered.sqlite3'
        with self.assertRaises(AccountingError):restore_to_new_database(self.backup,target)
        self.assertFalse(target.exists())

    def test_reject_missing_or_altered_receipt(self):
        receipt=self.backup.with_suffix('.sqlite3.sha256')
        receipt.write_text('0'*64+'  snapshot.sqlite3\n',encoding='utf-8')
        with self.assertRaises(AccountingError):verify_backup(self.backup)

    def test_cli_verify_and_restore(self):
        root=Path(__file__).resolve().parents[1]
        cmd=[sys.executable,str(root/'main.py')]
        check=subprocess.run(cmd+['--verify-backup',str(self.backup)],capture_output=True,text=True,cwd=str(root))
        self.assertEqual(check.returncode,0,check.stderr)
        dest=self.root/'from_cli.sqlite3'
        recovered=subprocess.run(cmd+['--restore-backup',str(self.backup),'--restore-to',str(dest)],capture_output=True,text=True,cwd=str(root))
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        self.assertTrue(dest.exists())

    def test_reject_non_database_even_with_matching_receipt(self):
        from saba_accounting.recovery import sha256_file
        self.backup.write_bytes(b'not a sqlite database')
        self.backup.with_suffix('.sqlite3.sha256').write_text(
            sha256_file(self.backup)+'  snapshot.sqlite3\n', encoding='utf-8')
        with self.assertRaises(AccountingError):verify_backup(self.backup)

    def test_reject_unrelated_sqlite_even_with_matching_receipt(self):
        from saba_accounting.recovery import sha256_file
        self.backup.unlink()
        with closing(sqlite3.connect(self.backup)) as conn:
            conn.execute('CREATE TABLE unrelated (x INTEGER)')
        self.backup.with_suffix('.sqlite3.sha256').write_text(
            sha256_file(self.backup)+'  snapshot.sqlite3\n', encoding='utf-8')
        with self.assertRaises(AccountingError):verify_backup(self.backup)

    def test_reject_sidecar_collision(self):
        dest=self.root/'target.sqlite3'
        Path(str(dest)+'-wal').write_text('busy')
        with self.assertRaises(AccountingError):restore_to_new_database(self.backup,dest)
        self.assertFalse(dest.exists())

if __name__=='__main__':unittest.main()
