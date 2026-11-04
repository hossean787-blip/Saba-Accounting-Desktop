"""Local users, hardened login, sessions and business-layer authorization.

This protects access through the application. OS permissions or BitLocker are
still required to protect an offline copy of the SQLite database.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ITERATIONS = 600_000
_MAX_FAILURES = 5
ROLE_PERMISSIONS = {
    "admin": frozenset({"read", "write", "post", "export", "backup", "manage_users"}),
    "accountant": frozenset({"read", "write", "post", "export", "backup"}),
    "viewer": frozenset({"read", "export"}),
}
_METHOD_PERMISSIONS = {"post": "post", "close_fiscal_year": "post", "reverse": "post",
                       "backup": "backup", "backup_verified": "backup", "verified_backup": "backup",
                       "tax_export": "export"}
_WRITE_PREFIXES = ("create_", "new_", "replace_", "update_", "register_", "record_", "set_", "run_")
_READ_PREFIXES = ("get_", "list_", "preview_", "verify_", "reconcile_", "integration_", "trial_",
                  "ledger", "income_", "balance_", "companies", "accounts", "fiscal_")
_READ_METHODS = {
    "journals", "journal", "dashboard", "statements", "config", "parties", "cashboxes",
    "cash_flow", "warehouses", "items", "stock_report", "invoices", "budgets", "overview",
    "integrity_report", "floating_details", "require_floating_detail", "closing_preview",
    "closing_preview_details", "closure_info", "general_journal", "floating_ledger",
    "journal_source_summary", "full_integrity_report", "verify_backup_receipt",
}


class LoginError(ValueError):
    pass


class PermissionDenied(LoginError):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS local_login (
      singleton INTEGER PRIMARY KEY CHECK(singleton=1), salt BLOB NOT NULL,
      secret BLOB NOT NULL, iterations INTEGER NOT NULL CHECK(iterations>=100000));
    CREATE TABLE IF NOT EXISTS app_users (
      id INTEGER PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
      display_name TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin','accountant','viewer')),
      salt BLOB NOT NULL, secret BLOB NOT NULL,
      iterations INTEGER NOT NULL CHECK(iterations>=100000),
      is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
      failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT,
      password_changed_at TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS security_events (
      id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, username TEXT,
      event_type TEXT NOT NULL, success INTEGER NOT NULL CHECK(success IN (0,1)),
      detail TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS ix_security_events_time ON security_events(occurred_at);
    """)
    # Schema migration for databases created by v0.6.3 and earlier.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(app_users)")}
    if "auth_version" not in existing:
        conn.execute("ALTER TABLE app_users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn


def _hash_password(password, salt=None, iterations=_ITERATIONS):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise LoginError("رمز ورود باید حداقل ۱۲ و حداکثر ۱۰۲۴ نویسه باشد.")
    salt = salt or secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return salt, digest, iterations


def _matches(row, password):
    if not isinstance(password, str):
        return False
    salt, digest, rounds = row
    if not isinstance(rounds, int) or not 100_000 <= rounds <= 2_000_000:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(candidate, digest)


def _event(conn, username, event_type, success, detail=""):
    # Deliberately exclude credentials, tokens, SQL and financial values.
    conn.execute("INSERT INTO security_events(occurred_at,username,event_type,success,detail) VALUES(?,?,?,?,?)",
                 (_iso(_utcnow()), username, event_type, int(success), str(detail)[:500]))


def configured(db_path):
    with closing(_connect(db_path)) as conn:
        return (conn.execute("SELECT 1 FROM app_users WHERE is_active=1 LIMIT 1").fetchone() is not None
                or conn.execute("SELECT 1 FROM local_login WHERE singleton=1").fetchone() is not None)


def legacy_login_allowed(db_path):
    """Disable the shared-password login as soon as named accounts exist.

    An upgraded installation may still contain the old local_login record.
    It must never bypass role-based authorization once a named user is created.
    """
    with closing(_connect(db_path)) as conn:
        return conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone() is None


def set_password(db_path, new_password, old_password=None):
    """Retain the v0.6.2 single-password API for compatible upgrades."""
    salt, key, rounds = _hash_password(new_password)
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
            raise LoginError("در حالت چندکاربره تغییر رمز فقط از طریق مدیریت کاربران مجاز است.")
        row = conn.execute("SELECT salt,secret,iterations FROM local_login WHERE singleton=1").fetchone()
        if row and not _matches(row, old_password):
            raise LoginError("رمز فعلی صحیح نیست.")
        conn.execute("INSERT INTO local_login(singleton,salt,secret,iterations) VALUES(1,?,?,?) "
                     "ON CONFLICT(singleton) DO UPDATE SET salt=excluded.salt,secret=excluded.secret,iterations=excluded.iterations",
                     (salt, key, rounds))
        conn.commit()


def verify_password(db_path, password):
    with closing(_connect(db_path)) as conn:
        if conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
            return False
        row = conn.execute("SELECT salt,secret,iterations FROM local_login WHERE singleton=1").fetchone()
    return bool(row and _matches(row, password))


@dataclass
class Session:
    user_id: int
    username: str
    display_name: str
    role: str
    issued_at: datetime
    expires_at: datetime
    idle_timeout: timedelta = timedelta(minutes=30)
    _last_seen: datetime | None = None
    _revoked: bool = False
    _db_path: Path | None = None
    _auth_version: int = 0

    def __post_init__(self):
        self._last_seen = self.issued_at

    def require(self, permission):
        now = _utcnow()
        if self._revoked or now >= self.expires_at or now - self._last_seen >= self.idle_timeout:
            self._revoked = True
            raise LoginError("نشست منقضی شده است؛ دوباره وارد شوید.")
        # Recheck authoritative account state on every protected operation.
        # This revokes already-issued sessions after role, status or password changes.
        if self._db_path is not None:
            with closing(_connect(self._db_path)) as conn:
                row = conn.execute(
                    "SELECT role,is_active,auth_version FROM app_users WHERE id=?", (self.user_id,)
                ).fetchone()
            if (row is None or not row["is_active"] or row["role"] != self.role
                    or row["auth_version"] != self._auth_version):
                self._revoked = True
                raise LoginError("نشست به دلیل تغییر حساب کاربری باطل شد؛ دوباره وارد شوید.")
        if permission not in ROLE_PERMISSIONS[self.role]:
            raise PermissionDenied("نقش کاربر مجوز انجام این عملیات را ندارد.")
        self._last_seen = now

    def logout(self):
        self._revoked = True


class UserManager:
    def __init__(self, db_path):
        self.path = Path(db_path)

    def bootstrap_admin(self, username, password, display_name="مدیر سیستم"):
        with closing(_connect(self.path)) as conn:
            if conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
                raise LoginError("راه‌اندازی مدیر فقط برای پایگاه بدون کاربر مجاز است.")
            return self._insert_user(conn, username, password, display_name, "admin")

    def _insert_user(self, conn, username, password, display_name, role):
        username, display_name = str(username).strip(), str(display_name).strip()
        if role not in ROLE_PERMISSIONS or not username or len(username) > 100 or not display_name or len(display_name) > 200:
            raise LoginError("نام کاربری، نام نمایشی یا نقش معتبر نیست.")
        salt, digest, rounds = _hash_password(password)
        now = _iso(_utcnow())
        cur = conn.execute("INSERT INTO app_users(username,display_name,role,salt,secret,iterations,password_changed_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (username, display_name, role, salt, digest, rounds, now, now))
        _event(conn, username, "USER_BOOTSTRAPPED" if role == "admin" else "USER_CREATED", True)
        conn.commit()
        return cur.lastrowid

    def create_user(self, actor, username, password, display_name, role):
        actor.require("manage_users")
        with closing(_connect(self.path)) as conn:
            try:
                ident = self._insert_user(conn, username, password, display_name, role)
                _event(conn, actor.username, "USER_CREATED", True, f"username={username}; role={role}")
                conn.commit()
                return ident
            except sqlite3.IntegrityError as exc:
                raise LoginError("نام کاربری تکراری است.") from exc

    def list_users(self, actor):
        actor.require("manage_users")
        with closing(_connect(self.path)) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,username,display_name,role,is_active,created_at FROM app_users ORDER BY username")]

    def update_user(self, actor, user_id, *, role=None, is_active=None):
        actor.require("manage_users")
        if role is None and is_active is None:
            raise LoginError("هیچ تغییری درخواست نشده است.")
        if role is not None and role not in ROLE_PERMISSIONS:
            raise LoginError("نقش معتبر نیست.")
        with closing(_connect(self.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute("SELECT id,username,role,is_active FROM app_users WHERE id=?", (int(user_id),)).fetchone()
            if not target:
                raise LoginError("کاربر یافت نشد.")
            new_role = role if role is not None else target["role"]
            new_active = int(bool(is_active)) if is_active is not None else target["is_active"]
            if target["role"] == "admin" and target["is_active"] and (new_role != "admin" or not new_active):
                admins = conn.execute("SELECT COUNT(*) FROM app_users WHERE role='admin' AND is_active=1").fetchone()[0]
                if admins <= 1:
                    raise LoginError("آخرین مدیر فعال را نمی‌توان غیرفعال یا تنزل نقش داد.")
            conn.execute("UPDATE app_users SET role=?,is_active=?,auth_version=auth_version+1 WHERE id=?",
                         (new_role, new_active, target["id"]))
            _event(conn, actor.username, "USER_UPDATED", True,
                   f"username={target['username']}; role={new_role}; active={new_active}")
            conn.commit()

    def change_password(self, actor, user_id, new_password, current_password=None):
        target_id = int(user_id)
        self_change = actor.user_id == target_id
        actor.require("read" if self_change else "manage_users")
        # Admins may reset other users' passwords; self-service changes must
        # verify the existing password, even when the actor is an admin.
        salt, digest, rounds = _hash_password(new_password)
        with closing(_connect(self.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute("SELECT id,username,salt,secret,iterations FROM app_users WHERE id=?",
                                  (target_id,)).fetchone()
            if not target:
                raise LoginError("کاربر یافت نشد.")
            if self_change and not _matches((target["salt"], target["secret"], target["iterations"]), current_password):
                _event(conn, actor.username, "PASSWORD_CHANGE", False, "invalid-current-password")
                conn.commit()
                raise LoginError("رمز فعلی صحیح نیست.")
            conn.execute("UPDATE app_users SET salt=?,secret=?,iterations=?,password_changed_at=?,"
                         "failed_attempts=0,locked_until=NULL,auth_version=auth_version+1 WHERE id=?",
                         (salt, digest, rounds, _iso(_utcnow()), target_id))
            _event(conn, actor.username, "PASSWORD_CHANGED", True, f"user_id={target_id}")
            conn.commit()

    def authenticate(self, username, password):
        username = str(username).strip()
        with closing(_connect(self.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM app_users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            now = _utcnow()
            if not row or not row["is_active"]:
                _event(conn, username, "LOGIN", False, "unknown-or-disabled")
                conn.commit()
                raise LoginError("نام کاربری یا رمز ورود نادرست است.")
            locked = datetime.fromisoformat(row["locked_until"]) if row["locked_until"] else None
            if locked and locked > now:
                _event(conn, row["username"], "LOGIN", False, "locked")
                conn.commit()
                raise LoginError("حساب موقتاً قفل است؛ بعداً دوباره تلاش کنید.")
            if not _matches((row["salt"], row["secret"], row["iterations"]), password):
                failures = row["failed_attempts"] + 1
                until = _iso(now + timedelta(minutes=15)) if failures >= _MAX_FAILURES else None
                conn.execute("UPDATE app_users SET failed_attempts=?,locked_until=? WHERE id=?", (failures, until, row["id"]))
                _event(conn, row["username"], "LOGIN", False, "invalid-credential")
                conn.commit()
                raise LoginError("نام کاربری یا رمز ورود نادرست است.")
            conn.execute("UPDATE app_users SET failed_attempts=0,locked_until=NULL WHERE id=?", (row["id"],))
            _event(conn, row["username"], "LOGIN", True)
            conn.commit()
            return Session(row["id"], row["username"], row["display_name"], row["role"], now,
                           now + timedelta(hours=8), _db_path=self.path,
                           _auth_version=row["auth_version"])

    def security_events(self, actor, limit=200):
        actor.require("manage_users")
        limit = max(1, min(int(limit), 1000))
        with closing(_connect(self.path)) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,occurred_at,username,event_type,success,detail FROM security_events ORDER BY id DESC LIMIT ?", (limit,))]


class AuthorizedStore:
    """Permission-enforcing facade for accounting, ERP and finance services."""
    def __init__(self, store, session):
        self._store, self.session = store, session

    @property
    def path(self):
        return self._store.path

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError("Private storage operations are not exposed by the authorization facade")
        target = getattr(self._store, name)
        if not callable(target):
            return target
        permission = _METHOD_PERMISSIONS.get(name)
        if permission is None:
            if name.startswith("export_"):
                permission = "export"
            elif name.startswith(_WRITE_PREFIXES):
                permission = "write"
            elif name.startswith(_READ_PREFIXES) or name in _READ_METHODS:
                permission = "read"
            else:
                permission = "write"  # fail closed for future public methods

        def guarded(*args, **kwargs):
            self.session.require(permission)
            return target(*args, **kwargs)
        return guarded
