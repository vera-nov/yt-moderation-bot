import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any


def utc_now_iso() -> str:
    """
    :return:  UTC timestamp (ISO)
    :rtype: str
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_day_key() -> str:
    """
    :return: UTC date YYYY-MM-DD
    :rtype: str
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class StateStore:
    """
    Store bot state in SQLite
    """
    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # access rows via row names
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        """
        Initialize database

        bot_state: State of the bot (active, disabled, etc.)
        processed_comments: Seen comments
        quota_usage: Quota usage per day
        telegram_updates_offset: Last action with the bot in Telegram
        audit_log: Event log

        Create indexes to speed up the search
        """
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    enabled_at TEXT,
                    dry_run INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processed_comments (
                    comment_id TEXT PRIMARY KEY,
                    comment_type TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    parent_comment_id TEXT,
                    video_id TEXT,
                    published_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    processed_result TEXT NOT NULL,
                    rule_name TEXT,
                    text TEXT,
                    author_display_name TEXT,
                    author_channel_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_processed_comments_published_at
                    ON processed_comments(published_at);

                CREATE INDEX IF NOT EXISTS idx_processed_comments_first_seen_at
                    ON processed_comments(first_seen_at);

                CREATE INDEX IF NOT EXISTS idx_processed_comments_video_id
                    ON processed_comments(video_id);

                CREATE TABLE IF NOT EXISTS quota_usage (
                    quota_day_key TEXT PRIMARY KEY,
                    units_spent INTEGER NOT NULL,
                    warning_sent INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telegram_updates_offset (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_update_id INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            row = conn.execute("SELECT id FROM bot_state WHERE id = 1").fetchone()
            if row is None:
                now = utc_now_iso()
                conn.execute(
                    """
                    INSERT INTO bot_state (id, enabled, state, enabled_at, dry_run, updated_at)
                    VALUES (1, 0, 'OFF', NULL, 0, ?)
                    """,
                    (now,),
                )

            row = conn.execute("SELECT id FROM telegram_updates_offset WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO telegram_updates_offset (id, last_update_id)
                    VALUES (1, 0)
                    """
                )

    def get_bot_state(self) -> dict[str, Any]:
        """
        Return bot state
        """
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM bot_state WHERE id = 1").fetchone()
            return {
                "enabled": bool(row["enabled"]),
                "state": row["state"],
                "enabled_at": row["enabled_at"],
                "dry_run": bool(row["dry_run"]),
                "updated_at": row["updated_at"],
            }

    def set_bot_state(
        self,
        *,
        enabled: bool,
        state: str,
        dry_run: bool,
        enabled_at: str | None,
    ) -> None:
        """
        Update bot state
        """
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE bot_state
                SET enabled = ?, state = ?, enabled_at = ?, dry_run = ?, updated_at = ?
                WHERE id = 1
                """,
                (int(enabled), state, enabled_at, int(dry_run), utc_now_iso()),
            )

    def enable_bot(self, dry_run: bool) -> str:
        """
        Activate the bot
        """
        enabled_at = utc_now_iso()
        state = "DRY_RUN" if dry_run else "ACTIVE"
        self.set_bot_state(enabled=True, state=state, dry_run=dry_run, enabled_at=enabled_at)
        return enabled_at

    def disable_bot(self) -> None:
        """
        Disable the bot
        """
        self.set_bot_state(enabled=False, state="OFF", dry_run=self.get_bot_state()["dry_run"], enabled_at=None)

    def set_dry_run(self, dry_run: bool) -> None:
        """
        Set dry run if active
        """
        current = self.get_bot_state()
        if current["enabled"]:
            state = "DRY_RUN" if dry_run else "ACTIVE"
            enabled_at = current["enabled_at"]
        else:
            state = "OFF"
            enabled_at = None
        self.set_bot_state(enabled=current["enabled"], state=state, dry_run=dry_run, enabled_at=enabled_at)

    def set_quota_paused(self) -> None:
        """
        Disable bot if reached quota
        """
        current = self.get_bot_state()
        self.set_bot_state(
            enabled=False,
            state="QUOTA_PAUSED",
            dry_run=current["dry_run"],
            enabled_at=None,
        )

    def reset_session_data(self) -> None:
        """
        Delete all processed comments and event log upon enabling
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM processed_comments")
            conn.execute("DELETE FROM audit_log")

    def get_processed_comment(self, comment_id: str) -> dict[str, Any] | None:
        """
        Return comment if already was processed
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM processed_comments WHERE comment_id = ?",
                (comment_id,),
            ).fetchone()
            return dict(row) if row else None

    def add_processed_comment(
        self,
        *,
        comment_id: str,
        comment_type: str,
        thread_id: str,
        parent_comment_id: str | None,
        video_id: str | None,
        published_at: str,
        processed_result: str,
        rule_name: str | None,
        text: str | None = None,
        author_display_name: str | None = None,
        author_channel_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_comments (
                    comment_id, comment_type, thread_id, parent_comment_id, video_id,
                    published_at, first_seen_at, processed_result, rule_name,
                    text, author_display_name, author_channel_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    comment_id, comment_type, thread_id, parent_comment_id, video_id,
                    published_at, utc_now_iso(), processed_result, rule_name,
                    text, author_display_name, author_channel_id,
                ),
            )

    def get_today_counts(self) -> dict[str, int]:
        """
        Get statistics for the day
        """
        day_key = utc_day_key()
        with self._conn() as conn:
            processed = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM processed_comments
                WHERE substr(first_seen_at, 1, 10) = ?
                """,
                (day_key,),
            ).fetchone()["cnt"]

            rejected = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM processed_comments
                WHERE substr(first_seen_at, 1, 10) = ?
                  AND processed_result IN ('rejected', 'dry_run_reject')
                """,
                (day_key,),
            ).fetchone()["cnt"]

            return {"processed_today": processed, "rejected_today": rejected}

    def get_quota_usage_today(self) -> dict[str, Any]:
        """
        Get info about quota usage today
        """
        day_key = utc_day_key()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM quota_usage WHERE quota_day_key = ?",
                (day_key,),
            ).fetchone()
            if row is None:
                return {"quota_day_key": day_key, "units_spent": 0, "warning_sent": False}
            return {
                "quota_day_key": row["quota_day_key"],
                "units_spent": row["units_spent"],
                "warning_sent": bool(row["warning_sent"]),
            }

    def add_quota_units(self, units: int) -> None:
        day_key = utc_day_key()
        now = utc_now_iso()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT quota_day_key FROM quota_usage WHERE quota_day_key = ?",
                (day_key,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO quota_usage (quota_day_key, units_spent, warning_sent, updated_at)
                    VALUES (?, ?, 0, ?)
                    """,
                    (day_key, units, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE quota_usage
                    SET units_spent = units_spent + ?, updated_at = ?
                    WHERE quota_day_key = ?
                    """,
                    (units, now, day_key),
                )

    def set_quota_warning_sent(self, sent: bool) -> None:
        day_key = utc_day_key()
        now = utc_now_iso()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT quota_day_key FROM quota_usage WHERE quota_day_key = ?",
                (day_key,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO quota_usage (quota_day_key, units_spent, warning_sent, updated_at)
                    VALUES (?, 0, ?, ?)
                    """,
                    (day_key, int(sent), now),
                )
            else:
                conn.execute(
                    """
                    UPDATE quota_usage
                    SET warning_sent = ?, updated_at = ?
                    WHERE quota_day_key = ?
                    """,
                    (int(sent), now, day_key),
                )

    def get_last_update_id(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_update_id FROM telegram_updates_offset WHERE id = 1"
            ).fetchone()
            return int(row["last_update_id"])

    def set_last_update_id(self, update_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE telegram_updates_offset
                SET last_update_id = ?
                WHERE id = 1
                """,
                (update_id,),
            )

    def append_audit_log(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (event_type, payload_json, created_at)
                VALUES (?, ?, ?)
                """,
                (event_type, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
            )

    def cleanup_old_records(self, processed_ttl_days: int, audit_ttl_days: int) -> None:
        """
        Delete records older than PROCESSED_TTL_DAYS days
        """
        processed_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=processed_ttl_days)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        audit_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=audit_ttl_days)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        quota_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        with self._conn() as conn:
            conn.execute(
                "DELETE FROM processed_comments WHERE first_seen_at < ?",
                (processed_cutoff,),
            )
            conn.execute(
                "DELETE FROM audit_log WHERE created_at < ?",
                (audit_cutoff,),
            )
            conn.execute(
                "DELETE FROM quota_usage WHERE quota_day_key < ?",
                (quota_cutoff,),
            )

    def get_pending_rejections_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM processed_comments
                WHERE processed_result = 'pending_reject'
                """
            ).fetchone()
            return int(row["cnt"])

    def get_pending_rejections(self, limit: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM processed_comments
                WHERE processed_result = 'pending_reject'
                ORDER BY first_seen_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_comments_rejected(self, comment_ids: list[str]) -> None:
        if not comment_ids:
            return

        placeholders = ",".join("?" for _ in comment_ids)
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE processed_comments
                SET processed_result = 'rejected'
                WHERE comment_id IN ({placeholders})
                """,
                comment_ids,
            )