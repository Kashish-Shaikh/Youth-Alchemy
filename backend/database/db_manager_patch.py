"""
db_manager_patch.py
===================
Drop this file into your  backend/database/  folder.

It monkey-patches the existing DBManager class at import time so that all the
methods called by app.py (but missing from the original DBManager) are added
without touching any of your existing code.

MISSING METHODS ADDED:
  • has_valid_consent(user_id, consent_type, version)  ← caused the crash
  • record_consent(user_id, consent_type, version, ip)
  • save_quality_log(user_id, valid, quality_score, issues, metrics)
  • log_image_action(user_id, scan_id, action, image_hash)
  • auto_expire_old_images(hours)

HOW TO USE
----------
In  backend/database/__init__.py  (or at the very top of db_manager.py),
add ONE line:

    import db_manager_patch          # ← add this line

That's it.  The patch runs once and DBManager gains all the missing methods.

Alternatively, paste the body of each method directly into your DBManager
class — the SQL and logic are self-contained.
"""

import sqlite3
import datetime
import json
import threading

# ── Lazy import — the real DBManager must already be importable ───────────────
try:
    from database.db_manager import DBManager
except ImportError:
    try:
        from db_manager import DBManager          # when cwd == backend/database
    except ImportError:
        DBManager = None

if DBManager is None:
    raise RuntimeError(
        "db_manager_patch: cannot import DBManager — check your Python path."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Helper: make sure the extra tables exist (called once per DBManager instance)
# ─────────────────────────────────────────────────────────────────────────────

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_APPLIED: set = set()


def _ensure_patch_tables(db_path: str):
    """Create the tables needed by the patched methods if they don't exist."""
    with _SCHEMA_LOCK:
        if db_path in _SCHEMA_APPLIED:
            return
        con = sqlite3.connect(db_path, check_same_thread=False)
        cur = con.cursor()

        # ── Consent table ─────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_consents (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                consent_type  TEXT    NOT NULL,
                version       TEXT    NOT NULL DEFAULT '1.0.0',
                consented_at  TEXT    NOT NULL,
                ip_address    TEXT,
                revoked       INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, consent_type, version)
            )
        """)

        # ── Image quality log ─────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS image_quality_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                valid         INTEGER NOT NULL DEFAULT 0,
                quality_score INTEGER NOT NULL DEFAULT 0,
                issues        TEXT,
                metrics       TEXT,
                created_at    TEXT    NOT NULL
            )
        """)

        # ── Image action log (privacy audit trail) ────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS image_action_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                scan_id       INTEGER,
                action        TEXT    NOT NULL,
                image_hash    TEXT,
                created_at    TEXT    NOT NULL
            )
        """)

        # ── Add expires_at column to scans if missing ─────────────────────────
        try:
            cur.execute("ALTER TABLE scans ADD COLUMN expires_at TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

        con.commit()
        con.close()
        _SCHEMA_APPLIED.add(db_path)


# ─────────────────────────────────────────────────────────────────────────────
# Detect which attribute the real DBManager uses for its DB path
# ─────────────────────────────────────────────────────────────────────────────

def _db_path(self) -> str:
    """Return the sqlite file path from the DBManager instance."""
    for attr in ('db_path', 'database', 'db_file', 'path', '_db_path'):
        if hasattr(self, attr):
            return getattr(self, attr)
    # Fallback: look for any str attribute ending in .db
    for val in self.__dict__.values():
        if isinstance(val, str) and val.endswith('.db'):
            return val
    raise AttributeError(
        "db_manager_patch: cannot find DB path on DBManager instance. "
        "Set self.db_path in your __init__."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Patched methods
# ─────────────────────────────────────────────────────────────────────────────

def has_valid_consent(self, user_id: int, consent_type: str, version: str = '1.0.0') -> bool:
    """
    Return True if the user has given (and not revoked) consent
    for `consent_type` at `version`.
    """
    path = _db_path(self)
    _ensure_patch_tables(path)
    con = sqlite3.connect(path, check_same_thread=False)
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT id FROM user_consents
            WHERE user_id = ? AND consent_type = ? AND version = ? AND revoked = 0
            LIMIT 1
        """, (user_id, consent_type, version))
        return cur.fetchone() is not None
    finally:
        con.close()


def record_consent(self, user_id: int, consent_type: str,
                   version: str = '1.0.0', ip_address: str = '') -> int:
    """
    Record that the user accepted `consent_type` at `version`.
    Returns the row id.  Uses INSERT OR REPLACE so re-accepting is safe.
    """
    path = _db_path(self)
    _ensure_patch_tables(path)
    now = datetime.datetime.utcnow().isoformat()
    con = sqlite3.connect(path, check_same_thread=False)
    try:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO user_consents (user_id, consent_type, version, consented_at, ip_address, revoked)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id, consent_type, version)
            DO UPDATE SET consented_at = excluded.consented_at,
                          ip_address   = excluded.ip_address,
                          revoked      = 0
        """, (user_id, consent_type, version, now, ip_address or ''))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def revoke_consent(self, user_id: int, consent_type: str, version: str = '1.0.0'):
    """Mark a consent as revoked."""
    path = _db_path(self)
    _ensure_patch_tables(path)
    con = sqlite3.connect(path, check_same_thread=False)
    try:
        con.execute("""
            UPDATE user_consents SET revoked = 1
            WHERE user_id = ? AND consent_type = ? AND version = ?
        """, (user_id, consent_type, version))
        con.commit()
    finally:
        con.close()


def save_quality_log(self, user_id: int, valid: bool,
                     quality_score: int, issues: list, metrics: dict) -> int:
    """Persist an image quality check result."""
    path = _db_path(self)
    _ensure_patch_tables(path)
    now = datetime.datetime.utcnow().isoformat()
    con = sqlite3.connect(path, check_same_thread=False)
    try:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO image_quality_logs
                (user_id, valid, quality_score, issues, metrics, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, int(valid), quality_score,
              json.dumps(issues), json.dumps(metrics), now))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def log_image_action(self, user_id: int, scan_id: int,
                     action: str, image_hash: str = '') -> int:
    """Append a privacy audit event (upload / delete / expire)."""
    path = _db_path(self)
    _ensure_patch_tables(path)
    now = datetime.datetime.utcnow().isoformat()
    con = sqlite3.connect(path, check_same_thread=False)
    try:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO image_action_logs (user_id, scan_id, action, image_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, scan_id, action, image_hash, now))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def auto_expire_old_images(self, hours: int = 24) -> int:
    """
    Null-out the stored annotated image for scans older than `hours`.
    Returns the number of scans cleared.
    """
    path = _db_path(self)
    _ensure_patch_tables(path)
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(hours=hours)).isoformat()
    con = sqlite3.connect(path, check_same_thread=False)
    try:
        cur = con.cursor()
        # Try updating with image_b64 column (common name)
        for col in ('image_b64', 'annotated_image', 'image_data', 'image'):
            try:
                cur.execute(f"""
                    UPDATE scans SET {col} = NULL
                    WHERE created_at < ?
                      AND {col} IS NOT NULL
                      AND {col} != ''
                """, (cutoff,))
                count = cur.rowcount
                con.commit()
                if count >= 0:          # column exists
                    return count
            except sqlite3.OperationalError:
                continue                # column doesn't exist, try next
        return 0
    finally:
        con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Attach all patched methods to the real DBManager class
# ─────────────────────────────────────────────────────────────────────────────

def _patch():
    methods = {
        'has_valid_consent':    has_valid_consent,
        'record_consent':       record_consent,
        'revoke_consent':       revoke_consent,
        'save_quality_log':     save_quality_log,
        'log_image_action':     log_image_action,
        'auto_expire_old_images': auto_expire_old_images,
    }
    patched = []
    for name, fn in methods.items():
        if not hasattr(DBManager, name):
            setattr(DBManager, name, fn)
            patched.append(name)
    if patched:
        print(f"[db_manager_patch] Added to DBManager: {', '.join(patched)}")
    else:
        print("[db_manager_patch] All methods already present — nothing patched.")

_patch()
