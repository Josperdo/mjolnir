"""
Database store for Mjolnir.
Handles all database operations using SQLite.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .models import BotSettings, PlaySession, ThresholdEvent, ThresholdRule, User


class Database:
    """SQLite database manager for Mjolnir."""

    def __init__(self, db_path: str = "mjolnir.db"):
        """Initialize database connection and create tables if needed."""
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                opted_in INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL
            )
        """)

        # Play sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS play_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                duration_seconds INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # Settings table (single row)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                tracking_enabled INTEGER NOT NULL DEFAULT 1,
                target_game TEXT NOT NULL DEFAULT 'League of Legends',
                weekly_threshold_hours REAL NOT NULL DEFAULT 20.0,
                timeout_duration_hours INTEGER NOT NULL DEFAULT 24,
                announcement_channel_id INTEGER
            )
        """)

        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user_time
            ON play_sessions(user_id, start_time)
        """)

        # Threshold rules table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threshold_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hours REAL NOT NULL,
                action TEXT NOT NULL DEFAULT 'warn',
                duration_hours INTEGER,
                message TEXT,
                window_type TEXT NOT NULL DEFAULT 'rolling_7d'
            )
        """)

        # Threshold events table (dedup tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threshold_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rule_id INTEGER NOT NULL,
                triggered_at TIMESTAMP NOT NULL,
                window_type TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (rule_id) REFERENCES threshold_rules (id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_threshold_events_user_rule
            ON threshold_events(user_id, rule_id, triggered_at)
        """)

        # Insert default settings if not exists
        cursor.execute("""
            INSERT OR IGNORE INTO settings (id) VALUES (1)
        """)

        # Seed default threshold rules if table is empty
        cursor.execute("SELECT COUNT(*) as cnt FROM threshold_rules")
        if cursor.fetchone()["cnt"] == 0:
            default_rules = [
                (10.0, 'warn', None, None, 'rolling_7d'),
                (15.0, 'timeout', 1, None, 'rolling_7d'),
                (20.0, 'timeout', 6, None, 'rolling_7d'),
                (30.0, 'timeout', 24, None, 'rolling_7d'),
            ]
            cursor.executemany(
                """INSERT INTO threshold_rules
                   (hours, action, duration_hours, message, window_type)
                   VALUES (?, ?, ?, ?, ?)""",
                default_rules
            )

        self.conn.commit()

    # ===== User operations =====

    def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by Discord ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if row:
            return User(
                user_id=row["user_id"],
                opted_in=bool(row["opted_in"]),
                created_at=row["created_at"]
            )
        return None

    def create_user(self, user_id: int, opted_in: bool = False) -> User:
        """Create a new user."""
        cursor = self.conn.cursor()
        created_at = datetime.now(timezone.utc)

        cursor.execute(
            "INSERT INTO users (user_id, opted_in, created_at) VALUES (?, ?, ?)",
            (user_id, int(opted_in), created_at)
        )
        self.conn.commit()

        return User(user_id=user_id, opted_in=opted_in, created_at=created_at)

    def set_user_opt_in(self, user_id: int, opted_in: bool):
        """Set user's opt-in status. Creates user if doesn't exist."""
        user = self.get_user(user_id)
        if user is None:
            self.create_user(user_id, opted_in)
        else:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE users SET opted_in = ? WHERE user_id = ?",
                (int(opted_in), user_id)
            )
            self.conn.commit()

    def get_opted_in_users(self) -> List[int]:
        """Get list of all opted-in user IDs."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE opted_in = 1")
        return [row["user_id"] for row in cursor.fetchall()]

    # ===== Play session operations =====

    def start_session(self, user_id: int, game_name: str) -> PlaySession:
        """Start a new play session."""
        cursor = self.conn.cursor()
        start_time = datetime.now(timezone.utc)

        cursor.execute(
            """INSERT INTO play_sessions
               (user_id, game_name, start_time)
               VALUES (?, ?, ?)""",
            (user_id, game_name, start_time)
        )
        self.conn.commit()

        return PlaySession(
            id=cursor.lastrowid,
            user_id=user_id,
            game_name=game_name,
            start_time=start_time
        )

    def end_session(self, session_id: int) -> Optional[PlaySession]:
        """End an active play session."""
        cursor = self.conn.cursor()
        end_time = datetime.now(timezone.utc)

        # Get the session to calculate duration
        cursor.execute("SELECT * FROM play_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()

        if row and row["end_time"] is None:
            start_time = row["start_time"]
            duration = int((end_time - start_time).total_seconds())

            cursor.execute(
                """UPDATE play_sessions
                   SET end_time = ?, duration_seconds = ?
                   WHERE id = ?""",
                (end_time, duration, session_id)
            )
            self.conn.commit()

            return PlaySession(
                id=row["id"],
                user_id=row["user_id"],
                game_name=row["game_name"],
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration
            )
        return None

    def get_active_session(self, user_id: int, game_name: str) -> Optional[PlaySession]:
        """Get user's active session for a specific game."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT * FROM play_sessions
               WHERE user_id = ? AND game_name = ? AND end_time IS NULL
               ORDER BY start_time DESC LIMIT 1""",
            (user_id, game_name)
        )
        row = cursor.fetchone()

        if row:
            return PlaySession(
                id=row["id"],
                user_id=row["user_id"],
                game_name=row["game_name"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                duration_seconds=row["duration_seconds"]
            )
        return None

    def get_weekly_playtime(self, user_id: int) -> float:
        """Get total playtime in hours for the past 7 days."""
        cursor = self.conn.cursor()
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        cursor.execute(
            """SELECT SUM(duration_seconds) as total
               FROM play_sessions
               WHERE user_id = ? AND start_time >= ? AND end_time IS NOT NULL""",
            (user_id, week_ago)
        )

        result = cursor.fetchone()
        total_seconds = result["total"] if result["total"] else 0
        return total_seconds / 3600  # Convert to hours

    # ===== Threshold rule operations =====

    def get_threshold_rules(self, window_type: Optional[str] = None) -> List[ThresholdRule]:
        """Get threshold rules, optionally filtered by window type, ordered by hours ASC."""
        cursor = self.conn.cursor()

        if window_type:
            cursor.execute(
                "SELECT * FROM threshold_rules WHERE window_type = ? ORDER BY hours ASC",
                (window_type,)
            )
        else:
            cursor.execute("SELECT * FROM threshold_rules ORDER BY hours ASC")

        return [
            ThresholdRule(
                id=row["id"],
                hours=row["hours"],
                action=row["action"],
                duration_hours=row["duration_hours"],
                message=row["message"],
                window_type=row["window_type"],
            )
            for row in cursor.fetchall()
        ]

    def get_daily_playtime(self, user_id: int) -> float:
        """Get total playtime in hours for the past 24 hours."""
        cursor = self.conn.cursor()
        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)

        cursor.execute(
            """SELECT SUM(duration_seconds) as total
               FROM play_sessions
               WHERE user_id = ? AND start_time >= ? AND end_time IS NOT NULL""",
            (user_id, day_ago)
        )

        result = cursor.fetchone()
        total_seconds = result["total"] if result["total"] else 0
        return total_seconds / 3600

    def get_calendar_week_playtime(self, user_id: int) -> float:
        """Get total playtime in hours since Monday 00:00 UTC of the current week."""
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc)
        # Monday = 0 in weekday()
        monday = now - timedelta(days=now.weekday(), hours=now.hour,
                                 minutes=now.minute, seconds=now.second,
                                 microseconds=now.microsecond)

        cursor.execute(
            """SELECT SUM(duration_seconds) as total
               FROM play_sessions
               WHERE user_id = ? AND start_time >= ? AND end_time IS NOT NULL""",
            (user_id, monday)
        )

        result = cursor.fetchone()
        total_seconds = result["total"] if result["total"] else 0
        return total_seconds / 3600

    def get_playtime_for_window(self, user_id: int, window_type: str,
                                session: Optional[PlaySession] = None) -> float:
        """Get playtime for a specific window type."""
        if window_type == "rolling_7d":
            return self.get_weekly_playtime(user_id)
        elif window_type == "daily":
            return self.get_daily_playtime(user_id)
        elif window_type == "weekly":
            return self.get_calendar_week_playtime(user_id)
        elif window_type == "session":
            return session.duration_hours if session else 0.0
        return 0.0

    def has_threshold_been_triggered(self, user_id: int, rule_id: int,
                                     window_type: str) -> bool:
        """Check if a threshold event exists for this user+rule within the current window."""
        # Session rules fire every qualifying session
        if window_type == "session":
            return False

        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc)

        if window_type == "rolling_7d":
            window_start = now - timedelta(days=7)
        elif window_type == "daily":
            window_start = now - timedelta(hours=24)
        elif window_type == "weekly":
            window_start = now - timedelta(days=now.weekday(), hours=now.hour,
                                           minutes=now.minute, seconds=now.second,
                                           microseconds=now.microsecond)
        else:
            return False

        cursor.execute(
            """SELECT COUNT(*) as cnt FROM threshold_events
               WHERE user_id = ? AND rule_id = ? AND triggered_at >= ?""",
            (user_id, rule_id, window_start)
        )

        return cursor.fetchone()["cnt"] > 0

    def record_threshold_event(self, user_id: int, rule_id: int,
                               window_type: str) -> None:
        """Record that a threshold rule was triggered for a user."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO threshold_events (user_id, rule_id, triggered_at, window_type)
               VALUES (?, ?, ?, ?)""",
            (user_id, rule_id, datetime.now(timezone.utc), window_type)
        )
        self.conn.commit()

    # ===== Settings operations =====

    def get_settings(self) -> BotSettings:
        """Get current bot settings."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        row = cursor.fetchone()

        return BotSettings(
            tracking_enabled=bool(row["tracking_enabled"]),
            target_game=row["target_game"],
            weekly_threshold_hours=row["weekly_threshold_hours"],
            timeout_duration_hours=row["timeout_duration_hours"],
            announcement_channel_id=row["announcement_channel_id"]
        )

    def update_settings(self, **kwargs):
        """Update bot settings. Pass settings as keyword arguments."""
        allowed_fields = {
            "tracking_enabled", "target_game", "weekly_threshold_hours",
            "timeout_duration_hours", "announcement_channel_id"
        }

        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not updates:
            return

        # Convert booleans to integers for SQLite
        if "tracking_enabled" in updates:
            updates["tracking_enabled"] = int(updates["tracking_enabled"])

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values())

        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE settings SET {set_clause} WHERE id = 1", values)
        self.conn.commit()

    def close(self):
        """Close database connection."""
        self.conn.close()
