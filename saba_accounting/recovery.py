"""Offline, verified recovery to a *new* database path.

Never overwrites an existing database. Backups remain plaintext SQLite;
protect both the database and the .sha256 receipt with filesystem ACLs.
"""
import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .storage import AccountingError

REQUIRED_TABLES = ('companies', 'fiscal_years', 'accounts', 'journal_entries', 'journal_lines')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def verify_backup(source):
    """Check filename-bound receipt, DB integrity, foreign keys and basic schema."""
    source = Path(source)
    receipt = source.with_suffix(source.suffix + '.sha256')
    if not source.is_file() or not receipt.is_file():
        raise AccountingError('فایل پشتیبان یا رسید SHA-256 یافت نشد.')
    try:
        parts = receipt.read_text(encoding='utf-8').strip().split('  ', 1)
    except (OSError, UnicodeError) as exc:
        raise AccountingError('رسید پشتیبان خواندنی نیست.') from exc
    if len(parts) != 2 or parts[1] != source.name or len(parts[0]) != 64:
        raise AccountingError('ساختار رسید پشتیبان معتبر نیست.')
    expected = parts[0]
    try:
        int(expected, 16)
    except ValueError as exc:
        raise AccountingError('هش رسید معتبر نیست.') from exc
    digest = sha256_file(source)
    if digest.lower() != expected.lower():
        raise AccountingError('هش فایل پشتیبان با رسید مطابقت ندارد.')
    # URI mode=ro ensures SQLite does not create an empty DB for a missing path.
    uri = source.resolve().as_uri() + '?mode=ro'
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise AccountingError('پایگاه داده پشتیبان ناسالم است.')
            if conn.execute('PRAGMA foreign_key_check').fetchall():
                raise AccountingError('پشتیبان دارای خطای کلید خارجی است.')
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(REQUIRED_TABLES).issubset(tables):
                raise AccountingError('ساختار پشتیبان متعلق به نسخه قابل پشتیبانی صبا نیست.')
    except sqlite3.DatabaseError as exc:
        raise AccountingError('فایل پشتیبان یک پایگاه داده SQLite معتبر نیست.') from exc
    return {'sha256': digest, 'source': str(source)}


def restore_to_new_database(source, destination):
    """Verified restore to a new file, never overwriting live data.

    SQLite online backup copies a consistent snapshot, and the exclusive open
    prevents an existing target from being replaced.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise AccountingError('مسیر منبع و مقصد یکسان است.')
    if destination.exists() or any(Path(str(destination)+ext).exists() for ext in ('-wal', '-shm', '-journal')):
        raise AccountingError('مقصد یا فایل‌های جانبی آن از قبل وجود دارد.')
    verify_backup(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix='.saba_restore_', suffix='.sqlite3', dir=str(destination.parent))
    os.close(fd)
    scratch = Path(scratch)
    created = False
    try:
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True)) as origin:
            with closing(sqlite3.connect(str(scratch))) as target:
                origin.backup(target)
        with closing(sqlite3.connect(str(scratch))) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise AccountingError('بازبینی پایگاه داده بازیابی‌شده ناموفق بود.')
        # Deliberate no-clobber semantics; concurrent destination creation is rejected.
        with destination.open('xb') as out, scratch.open('rb') as original:
            created = True
            for chunk in iter(lambda: original.read(1024 * 1024), b''):
                out.write(chunk)
        # Validate the delivered copy rather than trusting only the scratch DB.
        with closing(sqlite3.connect(destination.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise AccountingError('فایل بازیابی‌شده یکپارچه نیست.')
        return {'path': str(destination), 'sha256': sha256_file(destination)}
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        scratch.unlink(missing_ok=True)
