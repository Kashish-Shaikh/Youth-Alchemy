# database/db_manager.py — Youth Alchemy — Full DB layer (Users + Tracking + Appointments + Doctor)

import os
import sqlite3
import json
import datetime
from typing import Optional, List, Dict

DB_PATH = os.environ.get(
    'DERMIQ_DB_PATH',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'youthalchemy.db')
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")
    return conn


class DBManager:

    def __init__(self):
        self._init_schema()

    # ════════════════════════════════════════════════
    #  SCHEMA
    # ════════════════════════════════════════════════

    def _init_schema(self):
        with _get_conn() as conn:
            conn.executescript("""
                -- ── USERS ────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL,
                    email         TEXT    NOT NULL UNIQUE,
                    password_hash TEXT    NOT NULL,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                -- ── SCANS ────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS scans (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    overall_score REAL,
                    overall_grade TEXT,
                    face_detected INTEGER DEFAULT 0,
                    concerns_json TEXT,
                    profile_json  TEXT,
                    plan_text     TEXT,
                    image_b64     TEXT
                );

                -- ── HABITS ───────────────────────────────────────
                CREATE TABLE IF NOT EXISTS habits (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name        TEXT    NOT NULL,
                    emoji       TEXT    DEFAULT '✨',
                    category    TEXT    DEFAULT 'routine',
                    target_days INTEGER DEFAULT 7,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    active      INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS habit_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    habit_id    INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    logged_date TEXT    NOT NULL,
                    note        TEXT,
                    UNIQUE(habit_id, logged_date)
                );

                -- ── GOALS ────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS goals (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title        TEXT    NOT NULL,
                    description  TEXT,
                    target_score REAL,
                    target_date  TEXT,
                    concern_key  TEXT,
                    status       TEXT DEFAULT 'active',
                    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- ── JOURNAL ──────────────────────────────────────
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    entry_date    TEXT    NOT NULL DEFAULT (date('now')),
                    mood          TEXT,
                    skin_feel     TEXT,
                    notes         TEXT,
                    products_used TEXT,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- ── PRODUCTS ─────────────────────────────────────
                CREATE TABLE IF NOT EXISTS product_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name       TEXT    NOT NULL,
                    category   TEXT,
                    rating     INTEGER,
                    started_at TEXT    NOT NULL DEFAULT (date('now')),
                    ended_at   TEXT,
                    notes      TEXT,
                    active     INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- ── LOGIN ATTEMPTS ────────────────────────────────
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    email        TEXT    NOT NULL,
                    success      INTEGER DEFAULT 0,
                    ip_addr      TEXT    DEFAULT '',
                    attempted_at TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                -- ════════════════════════════════════════════════
                --  DOCTOR TABLES
                -- ════════════════════════════════════════════════

                -- Doctor accounts (role = 'doctor')
                CREATE TABLE IF NOT EXISTS doctors (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL,
                    email         TEXT    NOT NULL UNIQUE,
                    password_hash TEXT    NOT NULL,
                    specialty     TEXT    DEFAULT 'Dermatology',
                    bio           TEXT,
                    is_active     INTEGER DEFAULT 1,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                -- Weekly recurring availability
                -- day_of_week: 0=Mon … 6=Sun
                CREATE TABLE IF NOT EXISTS doctor_availability (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    doctor_id     INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
                    day_of_week   INTEGER NOT NULL,     -- 0=Mon, 6=Sun
                    start_time    TEXT    NOT NULL,     -- 'HH:MM' 24-hr UTC
                    end_time      TEXT    NOT NULL,
                    slot_duration INTEGER NOT NULL DEFAULT 30,  -- minutes
                    is_active     INTEGER DEFAULT 1,
                    UNIQUE(doctor_id, day_of_week)
                );

                -- Emergency overrides for a specific date
                CREATE TABLE IF NOT EXISTS doctor_schedule_override (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    doctor_id     INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
                    override_date TEXT    NOT NULL,     -- 'YYYY-MM-DD'
                    start_time    TEXT,                 -- NULL = entire day blocked
                    end_time      TEXT,
                    is_day_off    INTEGER DEFAULT 0,    -- 1 = cancel entire day
                    reason        TEXT,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(doctor_id, override_date)
                );

                -- Appointments (unified — linked to users OR walk-in guests)
                CREATE TABLE IF NOT EXISTS appointments (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    doctor_id     INTEGER REFERENCES doctors(id),
                    user_id       INTEGER REFERENCES users(id),   -- NULL if guest
                    name          TEXT    NOT NULL,
                    email         TEXT    NOT NULL,
                    phone         TEXT    NOT NULL,
                    date          TEXT    NOT NULL,    -- 'YYYY-MM-DD'
                    time          TEXT    NOT NULL,    -- 'HH:MM'
                    status        TEXT    DEFAULT 'pending',
                    concern       TEXT,
                    doctor_notes  TEXT,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(doctor_id, date, time)
                );

                -- ── INDEXES ──────────────────────────────────────
                CREATE INDEX IF NOT EXISTS idx_scans_user       ON scans(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_habit_logs_user  ON habit_logs(user_id, logged_date DESC);
                CREATE INDEX IF NOT EXISTS idx_journal_user     ON journal_entries(user_id, entry_date DESC);
                CREATE INDEX IF NOT EXISTS idx_login_email      ON login_attempts(email, attempted_at DESC);
                CREATE INDEX IF NOT EXISTS idx_appt_doctor_date ON appointments(doctor_id, date, time);
                CREATE INDEX IF NOT EXISTS idx_avail_doctor     ON doctor_availability(doctor_id, day_of_week);
                CREATE INDEX IF NOT EXISTS idx_override_doctor  ON doctor_schedule_override(doctor_id, override_date);

                -- ── USER CONSENTS (Disclaimer + Privacy) ─────────────────
                CREATE TABLE IF NOT EXISTS user_consents (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    consent_type TEXT    NOT NULL,
                    version      TEXT    NOT NULL,
                    ip_addr      TEXT    DEFAULT '',
                    metadata     TEXT    DEFAULT '{}',
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_consents_user ON user_consents(user_id, consent_type, created_at DESC);

                -- ── IMAGE AUDIT LOG ───────────────────────────────────────
                CREATE TABLE IF NOT EXISTS image_audit_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    scan_id      INTEGER REFERENCES scans(id) ON DELETE SET NULL,
                    action       TEXT    NOT NULL,
                    image_hash   TEXT    DEFAULT '',
                    anon_ref     TEXT    DEFAULT '',
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_audit_user ON image_audit_log(user_id, created_at DESC);

                -- ── IMAGE QUALITY VALIDATION LOG ──────────────────────────
                CREATE TABLE IF NOT EXISTS image_quality_log (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    valid          INTEGER DEFAULT 0,
                    quality_score  INTEGER DEFAULT 0,
                    issues_json    TEXT    DEFAULT '[]',
                    metrics_json   TEXT    DEFAULT '{}',
                    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_quality_user ON image_quality_log(user_id, created_at DESC);

                -- ── FEEDBACK TABLE ────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS recommendation_feedback (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    scan_id                 INTEGER REFERENCES scans(id) ON DELETE SET NULL,
                    rating                  INTEGER,
                    was_useful              INTEGER,
                    category                TEXT    DEFAULT 'overall',
                    comment                 TEXT    DEFAULT '',
                    followed_recommendation INTEGER,
                    outcome_after_days      INTEGER,
                    form_type               TEXT    DEFAULT 'standard',
                    created_at              TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_user   ON recommendation_feedback(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_feedback_scan   ON recommendation_feedback(scan_id);
                CREATE INDEX IF NOT EXISTS idx_feedback_rating ON recommendation_feedback(rating, created_at DESC);
            """)
        print(f"[DB] SQLite ready: {DB_PATH}")

    # ════════════════════════════════════════════════
    #  USERS
    # ════════════════════════════════════════════════

    def create_user(self, name: str, email: str, password_hash: str) -> int:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, password_hash)
            )
            uid = cur.lastrowid
        self._seed_default_habits(uid)
        return uid

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    # ════════════════════════════════════════════════
    #  SCANS
    # ════════════════════════════════════════════════

    def save_scan(self, user_id: int, scan_data: dict, image_b64: str = '') -> int:
        with _get_conn() as conn:
            user_exists = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            if not user_exists:
                raise ValueError(f"User {user_id} not found")
            concerns_json = json.dumps(scan_data.get('concerns', {}))
            cur = conn.execute(
                """INSERT INTO scans
                   (user_id, overall_score, overall_grade, face_detected, concerns_json, image_b64)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, scan_data.get('overall_score', 0), scan_data.get('overall_grade', 'A'),
                 1 if scan_data.get('face_detected') else 0, concerns_json,
                 image_b64[:50_000] if image_b64 else '')
            )
            return cur.lastrowid

    def update_scan_plan(self, scan_id: int, user_id: int, plan: str, profile: dict = None):
        with _get_conn() as conn:
            conn.execute(
                "UPDATE scans SET plan_text=?, profile_json=? WHERE id=? AND user_id=?",
                (plan, json.dumps(profile) if profile else None, scan_id, user_id)
            )

    def get_scan_history(self, user_id: int, limit: int = 60) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT id, created_at, overall_score, overall_grade,
                          face_detected, concerns_json,
                          CASE WHEN plan_text IS NOT NULL THEN 1 ELSE 0 END AS has_plan
                   FROM scans WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try: d['concerns'] = json.loads(d.pop('concerns_json') or '{}')
            except: d['concerns'] = {}
            result.append(d)
        return result

    def get_scan_by_id(self, scan_id: int, user_id: int) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM scans WHERE id=? AND user_id=?", (scan_id, user_id)).fetchone()
        if not row: return None
        d = dict(row)
        for field in ('concerns_json', 'profile_json'):
            key = field.replace('_json', '')
            try: d[key] = json.loads(d.pop(field) or '{}')
            except: d[key] = {}
        return d

    # ════════════════════════════════════════════════
    #  HABITS
    # ════════════════════════════════════════════════

    def _seed_default_habits(self, user_id: int):
        defaults = [
            ('Morning Cleanse',   '🫧', 'routine'),
            ('Sunscreen SPF 30+', '☀️', 'protection'),
            ('Moisturizer',       '💧', 'routine'),
            ('Evening Routine',   '🌙', 'routine'),
            ('Drink 2L Water',    '💦', 'lifestyle'),
            ('7-8 hrs Sleep',     '😴', 'lifestyle'),
            ('No Face Touching',  '🙌', 'lifestyle'),
            ('Change Pillowcase', '🛏️', 'hygiene'),
        ]
        with _get_conn() as conn:
            for name, emoji, cat in defaults:
                conn.execute(
                    "INSERT INTO habits (user_id, name, emoji, category) VALUES (?,?,?,?)",
                    (user_id, name, emoji, cat)
                )

    def get_habits(self, user_id: int) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM habits WHERE user_id=? AND active=1 ORDER BY category, id",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def create_habit(self, user_id: int, name: str, emoji: str, category: str) -> int:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO habits (user_id, name, emoji, category) VALUES (?,?,?,?)",
                (user_id, name, emoji, category)
            )
            return cur.lastrowid

    def delete_habit(self, habit_id: int, user_id: int):
        with _get_conn() as conn:
            conn.execute("UPDATE habits SET active=0 WHERE id=? AND user_id=?", (habit_id, user_id))

    def log_habit(self, habit_id: int, user_id: int, date_str: str, note: str = '') -> bool:
        try:
            with _get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO habit_logs (habit_id, user_id, logged_date, note) VALUES (?,?,?,?)",
                    (habit_id, user_id, date_str, note)
                )
            return True
        except Exception:
            return False

    def unlog_habit(self, habit_id: int, user_id: int, date_str: str):
        with _get_conn() as conn:
            conn.execute(
                "DELETE FROM habit_logs WHERE habit_id=? AND user_id=? AND logged_date=?",
                (habit_id, user_id, date_str)
            )

    def get_habit_logs(self, user_id: int, days: int = 30) -> List[Dict]:
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT hl.habit_id, hl.logged_date, hl.note,
                          h.name, h.emoji, h.category
                   FROM habit_logs hl JOIN habits h ON hl.habit_id=h.id
                   WHERE hl.user_id=? AND hl.logged_date>=? ORDER BY hl.logged_date DESC""",
                (user_id, since)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_habit_streaks(self, user_id: int) -> Dict:
        habits = self.get_habits(user_id)
        logs   = self.get_habit_logs(user_id, days=90)
        log_set = {(l['habit_id'], l['logged_date']) for l in logs}
        today = datetime.date.today()
        result = {}
        for h in habits:
            streak = 0
            d = today
            while (h['id'], d.isoformat()) in log_set:
                streak += 1
                d -= datetime.timedelta(days=1)
            result[h['id']] = streak
        return result

    def get_habit_completion_rate(self, user_id: int, days: int = 30) -> Dict:
        habits = self.get_habits(user_id)
        logs   = self.get_habit_logs(user_id, days=days)
        log_set = {(l['habit_id'], l['logged_date']) for l in logs}
        today = datetime.date.today()
        dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days)]
        result = {}
        for h in habits:
            logged = sum(1 for d in dates if (h['id'], d) in log_set)
            result[h['id']] = {
                'name': h['name'], 'emoji': h['emoji'],
                'logged': logged, 'total': days,
                'rate_pct': round(logged / days * 100, 1),
            }
        return result

    # ════════════════════════════════════════════════
    #  GOALS
    # ════════════════════════════════════════════════

    def create_goal(self, user_id: int, title: str, description: str,
                    target_score: float, target_date: str, concern_key: str) -> int:
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO goals (user_id, title, description, target_score, target_date, concern_key)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, title, description, target_score, target_date, concern_key)
            )
            return cur.lastrowid

    def get_goals(self, user_id: int) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE user_id=? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_goal_status(self, goal_id: int, user_id: int, status: str):
        with _get_conn() as conn:
            conn.execute(
                "UPDATE goals SET status=? WHERE id=? AND user_id=?", (status, goal_id, user_id)
            )

    # ════════════════════════════════════════════════
    #  JOURNAL
    # ════════════════════════════════════════════════

    def save_journal(self, user_id: int, entry_date: str, mood: str,
                     skin_feel: str, notes: str, products_used: str) -> int:
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT OR REPLACE INTO journal_entries
                   (user_id, entry_date, mood, skin_feel, notes, products_used)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, entry_date, mood, skin_feel, notes, products_used)
            )
            return cur.lastrowid

    def get_journal(self, user_id: int, limit: int = 30) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM journal_entries WHERE user_id=? ORDER BY entry_date DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    # ════════════════════════════════════════════════
    #  PRODUCT LOG
    # ════════════════════════════════════════════════

    def add_product(self, user_id: int, name: str, category: str, rating: int, notes: str) -> int:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO product_log (user_id, name, category, rating, notes) VALUES (?,?,?,?,?)",
                (user_id, name, category, rating, notes)
            )
            return cur.lastrowid

    def get_products(self, user_id: int) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM product_log WHERE user_id=? ORDER BY active DESC, created_at DESC",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_product(self, product_id: int, user_id: int, rating: int, notes: str, active: int):
        with _get_conn() as conn:
            conn.execute(
                "UPDATE product_log SET rating=?, notes=?, active=? WHERE id=? AND user_id=?",
                (rating, notes, active, product_id, user_id)
            )

    # ════════════════════════════════════════════════
    #  ANALYTICS
    # ════════════════════════════════════════════════

    def get_score_trend(self, user_id: int, days: int = 90) -> List[Dict]:
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT date(created_at) as scan_date, overall_score, overall_grade, id
                   FROM scans WHERE user_id=? AND face_detected=1
                   AND created_at>=? ORDER BY created_at ASC""",
                (user_id, since)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_concern_trend(self, user_id: int, concern_key: str, days: int = 90) -> List[Dict]:
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT date(created_at) as scan_date, concerns_json, overall_score
                   FROM scans WHERE user_id=? AND face_detected=1
                   AND created_at>=? ORDER BY created_at ASC""",
                (user_id, since)
            ).fetchall()
        result = []
        for row in rows:
            try:
                concerns = json.loads(row['concerns_json'] or '{}')
                c = concerns.get(concern_key, {})
                if c:
                    result.append({
                        'date': row['scan_date'], 'severity': c.get('severity', 0),
                        'grade': c.get('grade', 'A'), 'overall_score': row['overall_score']
                    })
            except Exception:
                pass
        return result

    # ════════════════════════════════════════════════
    #  SECURITY — Login attempts
    # ════════════════════════════════════════════════

    def record_login_attempt(self, email: str, success: bool, ip: str = ''):
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO login_attempts (email, success, ip_addr) VALUES (?,?,?)",
                (email.lower(), 1 if success else 0, ip[:45] if ip else '')
            )

    def get_failed_attempts(self, email: str, minutes: int = 15) -> int:
        since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)).isoformat()
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM login_attempts WHERE email=? AND success=0 AND attempted_at>=?",
                (email.lower(), since)
            ).fetchone()
        return row['c'] if row else 0

    def clear_login_attempts(self, email: str):
        with _get_conn() as conn:
            conn.execute("DELETE FROM login_attempts WHERE email=?", (email.lower(),))

    # ════════════════════════════════════════════════
    #  DOCTORS
    # ════════════════════════════════════════════════

    def create_doctor(self, name: str, email: str, password_hash: str,
                      specialty: str = 'Dermatology', bio: str = '') -> int:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO doctors (name, email, password_hash, specialty, bio) VALUES (?,?,?,?,?)",
                (name, email, password_hash, specialty, bio)
            )
            return cur.lastrowid

    def get_doctor_by_email(self, email: str) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM doctors WHERE email=? AND is_active=1", (email.lower(),)).fetchone()
            return dict(row) if row else None

    def get_doctor_by_id(self, doctor_id: int) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT id, name, email, specialty, bio, created_at FROM doctors WHERE id=? AND is_active=1",
                (doctor_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_doctors(self) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT id, name, specialty, bio FROM doctors WHERE is_active=1 ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    # ════════════════════════════════════════════════
    #  DOCTOR AVAILABILITY (weekly schedule)
    # ════════════════════════════════════════════════

    def set_availability(self, doctor_id: int, day_of_week: int, start_time: str,
                         end_time: str, slot_duration: int = 30) -> int:
        """Upsert a day's availability for a doctor."""
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO doctor_availability
                   (doctor_id, day_of_week, start_time, end_time, slot_duration, is_active)
                   VALUES (?,?,?,?,?,1)
                   ON CONFLICT(doctor_id, day_of_week) DO UPDATE SET
                     start_time=excluded.start_time,
                     end_time=excluded.end_time,
                     slot_duration=excluded.slot_duration,
                     is_active=1""",
                (doctor_id, day_of_week, start_time, end_time, slot_duration)
            )
            return cur.lastrowid

    def delete_availability(self, doctor_id: int, day_of_week: int):
        """Mark a day as unavailable (soft delete)."""
        with _get_conn() as conn:
            conn.execute(
                "UPDATE doctor_availability SET is_active=0 WHERE doctor_id=? AND day_of_week=?",
                (doctor_id, day_of_week)
            )

    def get_availability(self, doctor_id: int) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM doctor_availability
                   WHERE doctor_id=? AND is_active=1 ORDER BY day_of_week""",
                (doctor_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ════════════════════════════════════════════════
    #  DOCTOR SCHEDULE OVERRIDES (emergency)
    # ════════════════════════════════════════════════

    def set_override(self, doctor_id: int, override_date: str,
                     start_time: Optional[str], end_time: Optional[str],
                     is_day_off: bool = False, reason: str = '') -> int:
        """Upsert an emergency override for a specific date."""
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO doctor_schedule_override
                   (doctor_id, override_date, start_time, end_time, is_day_off, reason)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(doctor_id, override_date) DO UPDATE SET
                     start_time=excluded.start_time,
                     end_time=excluded.end_time,
                     is_day_off=excluded.is_day_off,
                     reason=excluded.reason""",
                (doctor_id, override_date, start_time, end_time, 1 if is_day_off else 0, reason)
            )
            return cur.lastrowid

    def get_override(self, doctor_id: int, date_str: str) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM doctor_schedule_override WHERE doctor_id=? AND override_date=?",
                (doctor_id, date_str)
            ).fetchone()
        return dict(row) if row else None

    def get_all_overrides(self, doctor_id: int) -> List[Dict]:
        today = datetime.date.today().isoformat()
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM doctor_schedule_override
                   WHERE doctor_id=? AND override_date >= ?
                   ORDER BY override_date""",
                (doctor_id, today)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_override(self, override_id: int, doctor_id: int):
        with _get_conn() as conn:
            conn.execute(
                "DELETE FROM doctor_schedule_override WHERE id=? AND doctor_id=?",
                (override_id, doctor_id)
            )

    # ════════════════════════════════════════════════
    #  SLOT GENERATION (core algorithm)
    # ════════════════════════════════════════════════

    def get_available_slots(self, doctor_id: int, date_str: str) -> Dict:
        """
        Returns available, booked, and blocked slots for a doctor on a given date.

        Priority: override > weekly availability.
        Only returns future slots if date == today.
        """
        target = datetime.date.fromisoformat(date_str)
        today  = datetime.date.today()
        now_utc = datetime.datetime.utcnow()

        # Past date — no slots
        if target < today:
            return {'available': [], 'booked': [], 'all': [], 'day_off': False, 'reason': 'Past date'}

        # Check override first
        override = self.get_override(doctor_id, date_str)
        if override:
            if override['is_day_off']:
                return {
                    'available': [], 'booked': [], 'all': [],
                    'day_off': True,
                    'reason': override.get('reason') or 'Doctor unavailable'
                }
            # Overridden hours
            start_t = override['start_time']
            end_t   = override['end_time']
            # Get slot_duration from normal schedule for this day
            dow = target.weekday()
            avail_row = self._get_availability_row(doctor_id, dow)
            slot_dur  = avail_row['slot_duration'] if avail_row else 30
        else:
            # Normal weekly schedule — weekday() gives 0=Mon…6=Sun
            dow = target.weekday()
            avail_row = self._get_availability_row(doctor_id, dow)
            if not avail_row:
                return {'available': [], 'booked': [], 'all': [], 'day_off': True, 'reason': 'Not a working day'}
            start_t  = avail_row['start_time']
            end_t    = avail_row['end_time']
            slot_dur = avail_row['slot_duration']

        # Generate all slots in range
        all_slots = self._generate_slots(start_t, end_t, slot_dur)

        # Filter past slots if today
        if target == today:
            cutoff = now_utc.strftime('%H:%M')
            all_slots = [s for s in all_slots if s > cutoff]

        # Get booked slots for this doctor+date
        booked = self._get_booked_times(doctor_id, date_str)
        available = [s for s in all_slots if s not in booked]

        return {
            'available': available,
            'booked':    booked,
            'all':       all_slots,
            'day_off':   False,
            'slot_duration': slot_dur,
            'reason':    None
        }

    def _get_availability_row(self, doctor_id: int, day_of_week: int) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM doctor_availability WHERE doctor_id=? AND day_of_week=? AND is_active=1",
                (doctor_id, day_of_week)
            ).fetchone()
        return dict(row) if row else None

    def _generate_slots(self, start_time: str, end_time: str, duration_minutes: int) -> List[str]:
        """Generate 'HH:MM' slot list from start to end with given duration."""
        slots = []
        sh, sm = map(int, start_time.split(':'))
        eh, em = map(int, end_time.split(':'))
        current = sh * 60 + sm
        end_min = eh * 60 + em
        while current + duration_minutes <= end_min:
            h, m = divmod(current, 60)
            slots.append(f"{h:02d}:{m:02d}")
            current += duration_minutes
        return slots

    def _get_booked_times(self, doctor_id: int, date_str: str) -> List[str]:
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT time FROM appointments
                   WHERE doctor_id=? AND date=? AND status NOT IN ('cancelled')""",
                (doctor_id, date_str)
            ).fetchall()
        return [r['time'] for r in rows]

    # ════════════════════════════════════════════════
    #  APPOINTMENTS
    # ════════════════════════════════════════════════

    def create_appointment(self, name: str, email: str,
                           phone: str, date: str, time: str,
                           doctor_id: Optional[int] = None,
                           user_id: Optional[int] = None,
                           concern: str = '') -> int:
        """Book a slot — raises ValueError('SLOT_TAKEN') on conflict."""
        with _get_conn() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO appointments
                       (doctor_id, user_id, name, email, phone, date, time, concern)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (doctor_id, user_id, name, email, phone, date, time, concern)
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError("SLOT_TAKEN")

    def get_appointment(self, appt_id: int) -> Optional[Dict]:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        return dict(row) if row else None

    def get_appointments_for_doctor(self, doctor_id: int,
                                    date_from: str = None, date_to: str = None) -> List[Dict]:
        clauses = ["a.doctor_id=?"]
        params = [doctor_id]
        if date_from:
            clauses.append("a.date>=?"); params.append(date_from)
        if date_to:
            clauses.append("a.date<=?"); params.append(date_to)
        where_sql = " AND ".join(clauses)
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT a.*, u.name as user_display_name "
                "FROM appointments a "
                "LEFT JOIN users u ON a.user_id = u.id "
                "WHERE " + where_sql + " ORDER BY a.date DESC, a.time ASC",
                params
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_appointments(self) -> List[Dict]:
        """Admin view — all appointments across all doctors."""
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT a.*, d.name as doctor_name
                   FROM appointments a
                   LEFT JOIN doctors d ON a.doctor_id = d.id
                   ORDER BY a.date DESC, a.time ASC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def update_appointment_status(self, appt_id: int, status: str,
                                  doctor_id: int = None):
        """Update status. If doctor_id given, scoped to that doctor only."""
        with _get_conn() as conn:
            if doctor_id:
                conn.execute(
                    "UPDATE appointments SET status=? WHERE id=? AND doctor_id=?",
                    (status, appt_id, doctor_id)
                )
            else:
                conn.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))

    def add_doctor_notes(self, appt_id: int, doctor_id: int, notes: str):
        with _get_conn() as conn:
            conn.execute(
                "UPDATE appointments SET doctor_notes=? WHERE id=? AND doctor_id=?",
                (notes, appt_id, doctor_id)
            )

    # ════════════════════════════════════════════════
    #  PATIENT HISTORY (for doctor view)
    # ════════════════════════════════════════════════

    def get_patient_full_history(self, user_id: int) -> Dict:
        """
        Returns everything a doctor needs to see about a patient:
        scans (with images), journal, products, habits.
        """
        with _get_conn() as conn:
            user_row = conn.execute(
                "SELECT id, name, email, created_at FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not user_row:
                return {}
            user = dict(user_row)

            scans_rows = conn.execute(
                """SELECT id, created_at, overall_score, overall_grade,
                          face_detected, concerns_json, plan_text, image_b64
                   FROM scans WHERE user_id=? ORDER BY created_at DESC LIMIT 20""",
                (user_id,)
            ).fetchall()
            scans = []
            for r in scans_rows:
                d = dict(r)
                try: d['concerns'] = json.loads(d.pop('concerns_json') or '{}')
                except: d['concerns'] = {}
                # Truncate image for list view — full image sent on individual scan fetch
                d['has_image'] = bool(d.get('image_b64'))
                d.pop('image_b64', None)
                scans.append(d)

            journal_rows = conn.execute(
                "SELECT * FROM journal_entries WHERE user_id=? ORDER BY entry_date DESC LIMIT 30",
                (user_id,)
            ).fetchall()

            product_rows = conn.execute(
                "SELECT * FROM product_log WHERE user_id=? ORDER BY active DESC, created_at DESC",
                (user_id,)
            ).fetchall()

        return {
            'user':     user,
            'scans':    scans,
            'journal':  [dict(r) for r in journal_rows],
            'products': [dict(r) for r in product_rows],
        }

    def get_patient_scan_image(self, scan_id: int, user_id: int) -> Optional[str]:
        """Fetch base64 image for a specific scan (doctor use)."""
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT image_b64 FROM scans WHERE id=? AND user_id=?",
                (scan_id, user_id)
            ).fetchone()
        return row['image_b64'] if row else None

    def get_appointments_for_user(self, user_id: int) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT a.*, d.name as doctor_name, d.specialty
                   FROM appointments a
                   LEFT JOIN doctors d ON a.doctor_id = d.id
                   WHERE a.user_id=? ORDER BY a.date DESC, a.time ASC""",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ════════════════════════════════════════════════
    #  LEGACY COMPAT — old hardcoded slot list removed
    #  (kept for reference; real slots come from get_available_slots)
    # ════════════════════════════════════════════════

    def get_booked_slots(self, date: str) -> list:
        """Legacy — used by old guest booking. Returns first doctor's booked slots."""
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT time FROM appointments WHERE date=? AND status!='cancelled'", (date,)
            ).fetchall()
        return [r['time'] for r in rows]

    # ════════════════════════════════════════════════
    #  CONSENT MANAGEMENT  (Features 1 & 2)
    # ════════════════════════════════════════════════

    def record_consent(self, user_id: int, consent_type: str, version: str,
                       ip_addr: str = '', metadata: str = '{}') -> int:
        """Saves a consent record. Returns the new consent ID."""
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO user_consents
                   (user_id, consent_type, version, ip_addr, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, consent_type, version, ip_addr, metadata)
            )
            return cur.lastrowid

    def get_latest_consent(self, user_id: int, consent_type: str) -> dict:
        """Returns the most recent consent record for a user+type, or {}."""
        with _get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM user_consents
                   WHERE user_id = ? AND consent_type = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id, consent_type)
            ).fetchone()
            return dict(row) if row else {}

    def has_valid_consent(self, user_id: int, consent_type: str,
                          required_version: str) -> bool:
        """Returns True if the user has accepted the required version."""
        consent = self.get_latest_consent(user_id, consent_type)
        return bool(consent) and consent.get('version') == required_version

    def revoke_consent(self, user_id: int, consent_type: str, version: str) -> int:
        """Marks the most recent matching consent as revoked. Returns rows affected."""
        with _get_conn() as conn:
            cur = conn.execute(
                """UPDATE user_consents SET metadata = json_set(coalesce(metadata,'{}'), '$.revoked', 1)
                   WHERE user_id = ? AND consent_type = ? AND version = ?""",
                (user_id, consent_type, version)
            )
            return cur.rowcount

    # ════════════════════════════════════════════════
    #  IMAGE PRIVACY MANAGEMENT  (Feature 2)
    # ════════════════════════════════════════════════

    def delete_user_images(self, user_id: int) -> int:
        """
        Nulls out all stored image data for a user (immediate deletion).
        Returns count of affected scans.
        """
        with _get_conn() as conn:
            cur = conn.execute(
                "UPDATE scans SET image_b64 = NULL WHERE user_id = ? AND image_b64 IS NOT NULL",
                (user_id,)
            )
            affected = cur.rowcount
            if affected > 0:
                conn.execute(
                    """INSERT INTO image_audit_log (user_id, action, created_at)
                       VALUES (?, 'deleted', datetime('now'))""",
                    (user_id,)
                )
            return affected

    def delete_user_account(self, user_id: int) -> bool:
        """
        Full account deletion — removes user row; cascade deletes all related data.
        Returns True on success.
        """
        with _get_conn() as conn:
            conn.execute("UPDATE scans SET image_b64 = NULL WHERE user_id = ?", (user_id,))
            conn.execute(
                """INSERT INTO image_audit_log (user_id, action, created_at)
                   VALUES (?, 'account_deleted', datetime('now'))""",
                (user_id,)
            )
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return True

    def auto_expire_old_images(self, hours: int = 24) -> int:
        """
        Scheduled cleanup: nulls images older than `hours`.
        Returns count of cleaned images.
        """
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()
        with _get_conn() as conn:
            cur = conn.execute(
                """UPDATE scans SET image_b64 = NULL
                   WHERE image_b64 IS NOT NULL AND created_at < ?""",
                (cutoff,)
            )
            affected = cur.rowcount
            if affected > 0:
                conn.execute(
                    """INSERT INTO image_audit_log (user_id, action, created_at)
                       SELECT DISTINCT user_id, 'auto_expired', datetime('now')
                       FROM scans WHERE user_id IS NOT NULL LIMIT 1"""
                )
            return affected

    def log_image_action(self, user_id: int, scan_id: int,
                         action: str, image_hash: str = '', anon_ref: str = '') -> int:
        """Logs an image lifecycle event for audit purposes."""
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO image_audit_log
                   (user_id, scan_id, action, image_hash, anon_ref)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, scan_id, action, image_hash, anon_ref)
            )
            return cur.lastrowid

    # ════════════════════════════════════════════════
    #  IMAGE QUALITY LOGGING  (Feature 3)
    # ════════════════════════════════════════════════

    def save_quality_log(self, user_id: int, valid: bool,
                         quality_score: int, issues: list, metrics: dict) -> int:
        """Saves an image quality validation result."""
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO image_quality_log
                   (user_id, valid, quality_score, issues_json, metrics_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, int(valid), quality_score,
                 json.dumps(issues), json.dumps(metrics))
            )
            return cur.lastrowid

    def get_quality_stats(self, user_id: int) -> dict:
        """Returns image quality history for a user."""
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT valid, quality_score, issues_json, created_at
                   FROM image_quality_log
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT 20""",
                (user_id,)
            ).fetchall()
            items = [dict(r) for r in rows]
            total = len(items)
            passed = sum(1 for r in items if r['valid'])
            return {
                "total_attempts": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": round(passed / total * 100, 1) if total else 0,
                "history": items
            }

    # ════════════════════════════════════════════════
    #  FEEDBACK SYSTEM  (Feature 4)
    # ════════════════════════════════════════════════

    def save_feedback(self, user_id: int, scan_id, rating, was_useful,
                      category: str = 'overall', comment: str = '',
                      followed_recommendation=None, outcome_after_days=None,
                      form_type: str = 'standard') -> int:
        """Saves a feedback record. Returns new feedback ID."""
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO recommendation_feedback
                   (user_id, scan_id, rating, was_useful, category, comment,
                    followed_recommendation, outcome_after_days, form_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, scan_id, rating,
                 int(was_useful) if was_useful is not None else None,
                 category, comment,
                 int(followed_recommendation) if followed_recommendation is not None else None,
                 outcome_after_days, form_type)
            )
            return cur.lastrowid

    def get_user_feedback(self, user_id: int, limit: int = 20) -> list:
        """Returns a user's own feedback history."""
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT f.*, s.overall_score, s.created_at as scan_date
                   FROM recommendation_feedback f
                   LEFT JOIN scans s ON f.scan_id = s.id
                   WHERE f.user_id = ?
                   ORDER BY f.created_at DESC LIMIT ?""",
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_feedback_stats(self, user_id: int) -> dict:
        """Returns aggregated feedback statistics for a user."""
        with _get_conn() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(*)                              AS total,
                     ROUND(AVG(CAST(rating AS FLOAT)), 2) AS avg_rating,
                     SUM(CASE WHEN was_useful=1 THEN 1 ELSE 0 END) AS useful_count,
                     SUM(CASE WHEN was_useful=0 THEN 1 ELSE 0 END) AS not_useful_count,
                     SUM(CASE WHEN followed_recommendation=1 THEN 1 ELSE 0 END) AS followed_count
                   FROM recommendation_feedback
                   WHERE user_id = ?""",
                (user_id,)
            ).fetchone()
            d = dict(row) if row else {}
            total = d.get('total', 0) or 0
            useful = d.get('useful_count', 0) or 0
            d['usefulness_rate'] = round(useful / total * 100, 1) if total > 0 else 0
            return d

    def get_global_feedback_analytics(self) -> dict:
        """Aggregated analytics (admin-only, anonymized)."""
        with _get_conn() as conn:
            overview = dict(conn.execute(
                """SELECT
                     COUNT(*)                              AS total_feedbacks,
                     ROUND(AVG(CAST(rating AS FLOAT)), 2) AS avg_rating,
                     SUM(CASE WHEN was_useful=1 THEN 1 ELSE 0 END)  AS total_useful,
                     SUM(CASE WHEN was_useful=0 THEN 1 ELSE 0 END)  AS total_not_useful,
                     COUNT(DISTINCT user_id)               AS unique_users
                   FROM recommendation_feedback"""
            ).fetchone() or {})

            by_category = conn.execute(
                """SELECT category,
                     COUNT(*) AS count,
                     ROUND(AVG(CAST(rating AS FLOAT)), 2) AS avg_rating,
                     SUM(CASE WHEN was_useful=1 THEN 1 ELSE 0 END) AS useful
                   FROM recommendation_feedback
                   GROUP BY category
                   ORDER BY count DESC"""
            ).fetchall()

            trend_30d = conn.execute(
                """SELECT date(created_at) AS day,
                     COUNT(*) AS count,
                     ROUND(AVG(CAST(rating AS FLOAT)), 2) AS avg_rating
                   FROM recommendation_feedback
                   WHERE created_at >= date('now', '-30 days')
                   GROUP BY day ORDER BY day ASC"""
            ).fetchall()

            return {
                "overview": overview,
                "by_category": [dict(r) for r in by_category],
                "trend_30d": [dict(r) for r in trend_30d]
            }

    def get_recommendation_history(self, user_id: int, limit: int = 10) -> list:
        """
        Returns recent scans WITH their feedback, used for personalized future suggestions.
        """
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT
                     s.id, s.created_at, s.overall_score, s.overall_grade,
                     s.concerns_json, s.plan_text,
                     f.rating, f.was_useful, f.comment, f.category
                   FROM scans s
                   LEFT JOIN recommendation_feedback f ON f.scan_id = s.id
                   WHERE s.user_id = ?
                   ORDER BY s.created_at DESC LIMIT ?""",
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]