import tempfile
import unittest
from pathlib import Path

from saba_accounting.encrypted_backup import MAGIC, restore_encrypted_backup
from saba_accounting.finance import FinanceStore
from saba_accounting.storage import AccountingError


class EncryptedBackupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "active.sqlite3"
        self.store = FinanceStore(self.db)
        self.company = self.store.create_company("شرکت رمزگذاری")
        self.encrypted = self.root / "daily.sabaenc"
        self.password = "Recovery-passphrase-123"

    def _backup(self):
        return self.store.encrypted_backup(self.encrypted, self.password, self.company)

    def test_roundtrip_is_authenticated_and_preserves_data(self):
        result = self._backup()
        self.assertEqual(MAGIC, self.encrypted.read_bytes()[:len(MAGIC)])
        self.assertNotIn(b"SQLite format 3", self.encrypted.read_bytes()[:100])
        self.assertTrue(Path(result["receipt"]).is_file())
        restored = self.root / "restored.sqlite3"
        restore_encrypted_backup(self.encrypted, restored, self.password)
        self.assertEqual("شرکت رمزگذاری", FinanceStore(restored).companies()[0]["name"])

    def test_wrong_passphrase_or_tamper_never_delivers_database(self):
        self._backup()
        target = self.root / "wrong.sqlite3"
        with self.assertRaisesRegex(AccountingError, "نادرست|دست‌کاری"):
            restore_encrypted_backup(self.encrypted, target, "Wrong-passphrase-123")
        self.assertFalse(target.exists())

    def test_receipt_detects_ciphertext_tamper(self):
        self._backup()
        with self.encrypted.open("r+b") as stream:
            stream.seek(-20, 2)
            value = stream.read(1)
            stream.seek(-1, 1)
            stream.write(bytes([value[0] ^ 1]))
        with self.assertRaisesRegex(AccountingError, "هش"):
            restore_encrypted_backup(self.encrypted, self.root / "tampered.sqlite3", self.password)

    def test_no_overwrite_and_password_policy(self):
        with self.assertRaises(AccountingError):
            self.store.encrypted_backup(self.encrypted, "short", self.company)
        self._backup()
        with self.assertRaises(AccountingError):
            self.store.encrypted_backup(self.encrypted, self.password, self.company)
        target = self.root / "existing.sqlite3"
        target.write_bytes(b"KEEP")
        with self.assertRaises(AccountingError):
            restore_encrypted_backup(self.encrypted, target, self.password)
        self.assertEqual(b"KEEP", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
