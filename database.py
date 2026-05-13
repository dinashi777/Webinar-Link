"""
database.py — SQLite-based persistence for the webinar bot
"""

import sqlite3
from datetime import datetime


DB_PATH = "webinar_bot.db"


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    joined_at   TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS invite_links (
                    user_id     INTEGER PRIMARY KEY,
                    link        TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS invites (
                    referrer_id INTEGER,
                    invited_id  INTEGER,
                    invited_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (referrer_id, invited_id),
                    FOREIGN KEY (referrer_id) REFERENCES users(user_id)
                );
            """)

    # ── Users ──────────────────────────────────
    def add_user(self, user_id: int, username: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username),
            )

    def get_user(self, user_id: int):
        return self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

    # ── Invite links ───────────────────────────
    def save_invite_link(self, user_id: int, link: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO invite_links (user_id, link) VALUES (?, ?)",
                (user_id, link),
            )

    def get_invite_link(self, user_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT link FROM invite_links WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["link"] if row else None

    def get_referrer_by_link(self, link: str) -> int | None:
        row = self.conn.execute(
            "SELECT user_id FROM invite_links WHERE link = ?", (link,)
        ).fetchone()
        return row["user_id"] if row else None

    # ── Invite tracking ────────────────────────
    def record_invite(self, referrer_id: int, invited_id: int):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO invites (referrer_id, invited_id) VALUES (?, ?)",
                (referrer_id, invited_id),
            )

    def get_invite_count(self, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM invites WHERE referrer_id = ?", (user_id,)
        ).fetchone()
        return row["cnt"] if row else 0

    def has_already_counted(self, referrer_id: int, invited_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM invites WHERE referrer_id = ? AND invited_id = ?",
            (referrer_id, invited_id),
        ).fetchone()
        return row is not None

    # ── Admin stats ────────────────────────────
    def get_stats(self) -> dict:
        total_users = self.conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        total_invites = self.conn.execute("SELECT COUNT(*) AS c FROM invites").fetchone()["c"]

        # Count users whose invite count >= REQUIRED_INVITES
        from config import REQUIRED_INVITES
        qualified = self.conn.execute(
            """
            SELECT COUNT(*) AS c FROM (
                SELECT referrer_id FROM invites
                GROUP BY referrer_id
                HAVING COUNT(*) >= ?
            )
            """,
            (REQUIRED_INVITES,),
        ).fetchone()["c"]

        return {
            "total_users": total_users,
            "qualified_users": qualified,
            "total_invites": total_invites,
        }
