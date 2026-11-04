"""Authenticated encrypted backups with passphrase-based key recovery.

Format is deliberately versioned and fail-closed. The passphrase is never
stored; losing it makes recovery impossible. Active SQLite files remain
plaintext and require separate OS/volume protection.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .recovery import restore_to_new_database, verify_backup
from .storage import AccountingError

MAGIC = b"SABAENC1"
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024


def _key(passphrase, salt, *, n=2**15, r=8, p=1):
    if not isinstance(passphrase, str) or len(passphrase) < 12 or len(passphrase) > 1024:
        raise AccountingError("عبارت بازیابی باید حداقل ۱۲ و حداکثر ۱۰۲۴ نویسه باشد.")
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def encrypt_verified_backup(source, destination, passphrase):
    """Encrypt a verified plaintext backup without overwriting any output."""
    source, destination = Path(source), Path(destination)
    verify_backup(source)
    receipt = destination.with_suffix(destination.suffix + ".sha256")
    if destination.exists() or receipt.exists():
        raise AccountingError("فایل پشتیبان رمزگذاری‌شده یا رسید آن از قبل وجود دارد.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    salt, nonce = os.urandom(16), os.urandom(12)
    header = json.dumps({
        "version": 1, "cipher": "AES-256-GCM", "kdf": "scrypt",
        "n": 2**15, "r": 8, "p": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    prefix = MAGIC + struct.pack(">I", len(header)) + header
    encryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(prefix)
    created = False
    try:
        with destination.open("xb") as out, source.open("rb") as plain:
            created = True
            out.write(prefix)
            for chunk in iter(lambda: plain.read(CHUNK_SIZE), b""):
                out.write(encryptor.update(chunk))
            out.write(encryptor.finalize())
            out.write(encryptor.tag)
        digest = _sha256(destination)
        with receipt.open("x", encoding="ascii") as proof:
            proof.write(f"{digest}  {destination.name}\n")
        return {"path": str(destination), "sha256": digest, "receipt": str(receipt)}
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)
        raise


def restore_encrypted_backup(source, destination, passphrase):
    """Decrypt, authenticate, validate and restore to a new database path."""
    source, destination = Path(source), Path(destination)
    if destination.exists() or any(Path(str(destination) + ext).exists() for ext in ("-wal", "-shm", "-journal")):
        raise AccountingError("مقصد یا فایل‌های جانبی آن از قبل وجود دارد.")
    receipt = source.with_suffix(source.suffix + ".sha256")
    _verify_receipt(source, receipt)
    scratch_dir = destination.parent
    scratch_dir.mkdir(parents=True, exist_ok=True)
    fd, scratch_name = tempfile.mkstemp(prefix=".saba_decrypt_", suffix=".sqlite3", dir=str(scratch_dir))
    os.close(fd)
    scratch = Path(scratch_name)
    scratch_receipt = scratch.with_suffix(scratch.suffix + ".sha256")
    try:
        with source.open("rb") as encrypted:
            prefix_start = encrypted.read(len(MAGIC) + 4)
            if len(prefix_start) != len(MAGIC) + 4 or not prefix_start.startswith(MAGIC):
                raise AccountingError("قالب پشتیبان رمزگذاری‌شده معتبر نیست.")
            header_len = struct.unpack(">I", prefix_start[-4:])[0]
            if not 32 <= header_len <= 4096:
                raise AccountingError("سرآیند پشتیبان رمزگذاری‌شده معتبر نیست.")
            header_raw = encrypted.read(header_len)
            try:
                header = json.loads(header_raw.decode("ascii"))
                if header.get("version") != 1 or header.get("cipher") != "AES-256-GCM" or header.get("kdf") != "scrypt":
                    raise ValueError
                salt = base64.b64decode(header["salt"], validate=True)
                nonce = base64.b64decode(header["nonce"], validate=True)
                n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
                if (n, r, p, len(salt), len(nonce)) != (2**15, 8, 1, 16, 12):
                    raise ValueError
            except (KeyError, TypeError, ValueError, UnicodeError) as exc:
                raise AccountingError("مشخصات رمزگذاری پشتیبان معتبر نیست.") from exc
            ciphertext_start = len(MAGIC) + 4 + header_len
            if source.stat().st_size <= ciphertext_start + TAG_SIZE:
                raise AccountingError("پشتیبان رمزگذاری‌شده ناقص است.")
            encrypted.seek(-TAG_SIZE, os.SEEK_END)
            tag = encrypted.read(TAG_SIZE)
            remaining = source.stat().st_size - ciphertext_start - TAG_SIZE
            encrypted.seek(ciphertext_start)
            decryptor = Cipher(algorithms.AES(_key(passphrase, salt, n=n, r=r, p=p)), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(prefix_start + header_raw)
            try:
                with scratch.open("wb") as plain:
                    while remaining:
                        chunk = encrypted.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            raise AccountingError("پشتیبان رمزگذاری‌شده ناقص است.")
                        remaining -= len(chunk)
                        plain.write(decryptor.update(chunk))
                    plain.write(decryptor.finalize())
            except InvalidTag as exc:
                raise AccountingError("عبارت بازیابی نادرست است یا پشتیبان دست‌کاری شده است.") from exc
        scratch_receipt.write_text(f"{_sha256(scratch)}  {scratch.name}\n", encoding="ascii")
        return restore_to_new_database(scratch, destination)
    finally:
        scratch.unlink(missing_ok=True)
        scratch_receipt.unlink(missing_ok=True)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_receipt(source, receipt):
    if not source.is_file() or not receipt.is_file():
        raise AccountingError("پشتیبان رمزگذاری‌شده یا رسید آن یافت نشد.")
    try:
        expected, filename = receipt.read_text(encoding="ascii").strip().split("  ", 1)
    except (OSError, UnicodeError, ValueError) as exc:
        raise AccountingError("رسید پشتیبان رمزگذاری‌شده معتبر نیست.") from exc
    if filename != source.name or len(expected) != 64 or _sha256(source) != expected.lower():
        raise AccountingError("هش پشتیبان رمزگذاری‌شده با رسید مطابقت ندارد.")
