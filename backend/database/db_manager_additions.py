# database/db_manager_additions.py
# Youth Alchemy — DB Manager ADDITIONS for the 4 new features.
#
# HOW TO USE:
#   These are NEW methods + schema additions to append into your existing DBManager class.
#   Step 1: Open  youthalchemy/backend/database/db_manager.py
#   Step 2: Find the _init_schema() method.
#   Step 3: Inside the executescript("...") triple-quoted string, ADD the SQL block below
#           (copy from the "### PASTE INTO _init_schema executescript" comment through
#            the matching end comment).
#   Step 4: Scroll to the bottom of DBManager class and PASTE the Python methods below.
#   Step 5: Save the file.
#
# Place this reference file at: youthalchemy/backend/database/db_manager_additions.py
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# ### PASTE INTO _init_schema executescript  (inside the triple-quoted SQL string)
# ─────────────────────────────────────────────────────────────────────────────
NEW_SCHEMA_SQL = """
    -- ── USER CONSENTS (Disclaimer + Privacy) ──────────────────────────────
    CREATE TABLE IF NOT EXISTS user_consents (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        consent_type TEXT    NOT NULL,   -- 'medical_disclaimer' | 'face_scan_privacy'
        version      TEXT    NOT NULL,
        ip_addr      TEXT    DEFAULT '',
        metadata     TEXT    DEFAULT '{}',
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_consents_user ON user_consents(user_id, consent_type, created_at DESC);

    -- ── IMAGE AUDIT LOG (Privacy — no raw images, only hash fingerprints) ──
    CREATE TABLE IF NOT EXISTS image_audit_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scan_id      INTEGER REFERENCES scans(id) ON DELETE SET NULL,
        action       TEXT    NOT NULL,   -- 'uploaded' | 'analyzed' | 'deleted' | 'auto_expired'
        image_hash   TEXT    DEFAULT '',  -- SHA-256 of image bytes (not the image)
        anon_ref     TEXT    DEFAULT '',  -- anonymized reference
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_audit_user ON image_audit_log(user_id, created_at DESC);

    -- ── IMAGE QUALITY VALIDATION LOG ─────────────────────────────────────
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

    -- ── FEEDBACK TABLE ────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS recommendation_feedback (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scan_id                 INTEGER REFERENCES scans(id) ON DELETE SET NULL,
        rating                  INTEGER,               -- 1-5 stars (nullable for quick feedback)
        was_useful              INTEGER,               -- 1=yes, 0=no (nullable)
        category                TEXT    DEFAULT 'overall',
        comment                 TEXT    DEFAULT '',
        followed_recommendation INTEGER,               -- 1=yes, 0=no (nullable)
        outcome_after_days      INTEGER,               -- days since recommendation before reporting
        form_type               TEXT    DEFAULT 'standard',  -- 'standard' | 'improvement' | 'quick'
        created_at              TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_feedback_user    ON recommendation_feedback(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_feedback_scan    ON recommendation_feedback(scan_id);
    CREATE INDEX IF NOT EXISTS idx_feedback_rating  ON recommendation_feedback(rating, created_at DESC);
"""


# ─────────────────────────────────────────────────────────────────────────────
# ### PASTE THESE METHODS inside your DBManager class (at the bottom)
# ─────────────────────────────────────────────────────────────────────────────

class DBManagerAdditions:
    """
    Mixin with all new methods.  In your actual db_manager.py, copy these methods
    directly into the DBManager class body (no inheritance needed).
    """

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
            # First null out images for audit clarity
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
        Call this periodically (e.g., via APScheduler or a cron job).
        Returns count of cleaned images.
        """
        import datetime
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
                       SELECT user_id, 'auto_expired', datetime('now')
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
        import json
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
        """
        Aggregated analytics (admin-only, anonymized).
        Returns stats about recommendation accuracy across all users.
        """
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
