"""
Database store for Mjolnir.
Handles all database operations using SQLite.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .models import AuditLog, BotSettings, CustomRoast, GameGroup, PlaySession, ThresholdEvent, ThresholdRule, TrackedGame, User


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

        # Tracked games registry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                added_at TIMESTAMP NOT NULL
            )
        """)

        # Insert default settings if not exists
        cursor.execute("""
            INSERT OR IGNORE INTO settings (id) VALUES (1)
        """)

        # Seed tracked_games from target_game if the table is still empty
        cursor.execute("SELECT COUNT(*) as cnt FROM tracked_games")
        if cursor.fetchone()["cnt"] == 0:
            cursor.execute("SELECT target_game FROM settings WHERE id = 1")
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    "INSERT OR IGNORE INTO tracked_games (game_name, enabled, added_at) VALUES (?, 1, ?)",
                    (row["target_game"], datetime.now(timezone.utc))
                )

        # Audit log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                target_user_id INTEGER,
                details TEXT,
                created_at TIMESTAMP NOT NULL
            )
        """)

        # Proactive warning dedup table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proactive_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rule_id INTEGER NOT NULL,
                warned_at TIMESTAMP NOT NULL,
                window_type TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (rule_id) REFERENCES threshold_rules (id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_proactive_warnings_user_rule
            ON proactive_warnings(user_id, rule_id, warned_at)
        """)

        # Custom roast messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_roasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                message TEXT NOT NULL
            )
        """)

        # Game groups for combined playtime limits
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_group_members (
                group_id INTEGER NOT NULL REFERENCES game_groups(id) ON DELETE CASCADE,
                game_name TEXT NOT NULL,
                PRIMARY KEY (group_id, game_name)
            )
        """)

        # Per-user per-game exclusions (users can opt out of specific games)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_game_exclusions (
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                game_name TEXT NOT NULL,
                PRIMARY KEY (user_id, game_name)
            )
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

        # Schema migrations for new columns on existing tables
        self._migrate(cursor)
        self.conn.commit()

    def _migrate(self, cursor):
        """Add columns that may not exist in older databases."""
        migrations = [
            ("users", "exempt", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "leaderboard_visible", "INTEGER NOT NULL DEFAULT 1"),
            ("settings", "warning_threshold_pct", "REAL NOT NULL DEFAULT 0.9"),
            ("settings", "cooldown_days", "INTEGER NOT NULL DEFAULT 3"),
            ("settings", "weekly_recap_day", "INTEGER NOT NULL DEFAULT 0"),
            ("settings", "weekly_recap_hour", "INTEGER NOT NULL DEFAULT 9"),
            ("settings", "last_weekly_recap_at", "TIMESTAMP"),
            # Multi-game support columns on threshold_rules
            ("threshold_rules", "game_name", "TEXT DEFAULT NULL"),
            ("threshold_rules", "group_id", "INTEGER DEFAULT NULL"),
        ]
        for table, column, col_type in migrations:
            try:
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Add game_name to threshold_events; backfill existing rows with target_game
        # (all pre-migration events were for the single global target game)
        try:
            cursor.execute("ALTER TABLE threshold_events ADD COLUMN game_name TEXT DEFAULT NULL")
            cursor.execute("""
                UPDATE threshold_events
                SET game_name = (SELECT target_game FROM settings WHERE id = 1)
                WHERE game_name IS NULL
            """)
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Same for proactive_warnings
        try:
            cursor.execute("ALTER TABLE proactive_warnings ADD COLUMN game_name TEXT DEFAULT NULL")
            cursor.execute("""
                UPDATE proactive_warnings
                SET game_name = (SELECT target_game FROM settings WHERE id = 1)
                WHERE game_name IS NULL
            """)
        except sqlite3.OperationalError:
            pass

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
                exempt=bool(row["exempt"]),
                leaderboard_visible=bool(row["leaderboard_visible"]),
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

    def set_user_exempt(self, user_id: int, exempt: bool):
        """Set user's exempt status. Creates user if doesn't exist."""
        user = self.get_user(user_id)
        if user is None:
            self.create_user(user_id, opted_in=False)
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE users SET exempt = ? WHERE user_id = ?",
            (int(exempt), user_id)
        )
        self.conn.commit()

    def set_leaderboard_visible(self, user_id: int, visible: bool):
        """Set whether the user appears on leaderboards. Creates user if needed."""
        user = self.get_user(user_id)
        if user is None:
            self.create_user(user_id, opted_in=False)
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE users SET leaderboard_visible = ? WHERE user_id = ?",
            (int(visible), user_id)
        )
        self.conn.commit()

    def delete_user_sessions(self, user_id: int) -> int:
        """Delete all play sessions for a user. Returns count of deleted rows."""
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM play_sessions WHERE user_id = ?", (user_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def clear_threshold_events(self, user_id: int) -> int:
        """Delete all threshold events for a user. Returns count of deleted rows."""
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM threshold_events WHERE user_id = ?", (user_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def clear_proactive_warnings(self, user_id: int) -> int:
        """Delete all proactive warnings for a user. Returns count of deleted rows."""
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM proactive_warnings WHERE user_id = ?", (user_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def get_user_export_data(self, user_id: int) -> dict:
        """Collect all stored data for a user (for GDPR export)."""
        user = self.get_user(user_id)
        cursor = self.conn.cursor()

        cursor.execute(
            "SELECT * FROM play_sessions WHERE user_id = ? ORDER BY start_time",
            (user_id,)
        )
        sessions = [
            {
                "id": row["id"],
                "game_name": row["game_name"],
                "start_time": str(row["start_time"]) if row["start_time"] else None,
                "end_time": str(row["end_time"]) if row["end_time"] else None,
                "duration_seconds": row["duration_seconds"],
            }
            for row in cursor.fetchall()
        ]

        cursor.execute(
            "SELECT * FROM threshold_events WHERE user_id = ? ORDER BY triggered_at",
            (user_id,)
        )
        events = [
            {
                "id": row["id"],
                "rule_id": row["rule_id"],
                "triggered_at": str(row["triggered_at"]) if row["triggered_at"] else None,
                "window_type": row["window_type"],
            }
            for row in cursor.fetchall()
        ]

        cursor.execute(
            "SELECT * FROM proactive_warnings WHERE user_id = ? ORDER BY warned_at",
            (user_id,)
        )
        warnings = [
            {
                "id": row["id"],
                "rule_id": row["rule_id"],
                "warned_at": str(row["warned_at"]) if row["warned_at"] else None,
                "window_type": row["window_type"],
            }
            for row in cursor.fetchall()
        ]

        return {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "opted_in": user.opted_in if user else None,
            "exempt": user.exempt if user else None,
            "leaderboard_visible": user.leaderboard_visible if user else None,
            "created_at": str(user.created_at) if user and user.created_at else None,
            "play_sessions": sessions,
            "threshold_events": events,
            "proactive_warnings": warnings,
        }

    def delete_all_user_data(self, user_id: int) -> dict:
        """Permanently delete all data for a user. Returns counts of deleted rows."""
        cursor = self.conn.cursor()

        cursor.execute("DELETE FROM proactive_warnings WHERE user_id = ?", (user_id,))
        warnings_deleted = cursor.rowcount

        cursor.execute("DELETE FROM threshold_events WHERE user_id = ?", (user_id,))
        events_deleted = cursor.rowcount

        cursor.execute("DELETE FROM play_sessions WHERE user_id = ?", (user_id,))
        sessions_deleted = cursor.rowcount

        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.conn.commit()

        return {
            "sessions_deleted": sessions_deleted,
            "events_deleted": events_deleted,
            "warnings_deleted": warnings_deleted,
        }

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
                game_name=row["game_name"],
                group_id=row["group_id"],
            )
            for row in cursor.fetchall()
        ]

    def get_threshold_rule(self, rule_id: int) -> Optional[ThresholdRule]:
        """Get a single threshold rule by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM threshold_rules WHERE id = ?", (rule_id,))
        row = cursor.fetchone()

        if row:
            return ThresholdRule(
                id=row["id"],
                hours=row["hours"],
                action=row["action"],
                duration_hours=row["duration_hours"],
                message=row["message"],
                window_type=row["window_type"],
                game_name=row["game_name"],
                group_id=row["group_id"],
            )
        return None

    def add_threshold_rule(self, hours: float, action: str,
                           duration_hours: Optional[int] = None,
                           message: Optional[str] = None,
                           window_type: str = "rolling_7d",
                           game_name: Optional[str] = None,
                           group_id: Optional[int] = None) -> ThresholdRule:
        """Add a new threshold rule and return it."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO threshold_rules
               (hours, action, duration_hours, message, window_type, game_name, group_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (hours, action, duration_hours, message, window_type, game_name, group_id)
        )
        self.conn.commit()

        return ThresholdRule(
            id=cursor.lastrowid,
            hours=hours,
            action=action,
            duration_hours=duration_hours,
            message=message,
            window_type=window_type,
            game_name=game_name,
            group_id=group_id,
        )

    def delete_threshold_rule(self, rule_id: int) -> bool:
        """Delete a threshold rule by ID. Returns True if a row was deleted."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM threshold_rules WHERE id = ?", (rule_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ===== Tracked game operations =====

    def get_tracked_games(self) -> List[TrackedGame]:
        """Return all tracked games ordered by name."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracked_games ORDER BY game_name")
        return [
            TrackedGame(
                id=row["id"],
                game_name=row["game_name"],
                enabled=bool(row["enabled"]),
                added_at=row["added_at"],
            )
            for row in cursor.fetchall()
        ]

    def add_tracked_game(self, game_name: str) -> TrackedGame:
        """Add a game to the tracking registry. Silently ignores duplicates."""
        cursor = self.conn.cursor()
        added_at = datetime.now(timezone.utc)
        cursor.execute(
            "INSERT OR IGNORE INTO tracked_games (game_name, enabled, added_at) VALUES (?, 1, ?)",
            (game_name, added_at)
        )
        self.conn.commit()
        # Re-fetch to return the actual row (handles the OR IGNORE case)
        cursor.execute("SELECT * FROM tracked_games WHERE LOWER(game_name) = LOWER(?)", (game_name,))
        row = cursor.fetchone()
        return TrackedGame(id=row["id"], game_name=row["game_name"],
                           enabled=bool(row["enabled"]), added_at=row["added_at"])

    def remove_tracked_game(self, game_name: str) -> bool:
        """Remove a game from the tracking registry. Returns True if found."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM tracked_games WHERE LOWER(game_name) = LOWER(?)", (game_name,))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_game_enabled(self, game_name: str, enabled: bool) -> None:
        """Enable or disable tracking for a specific game."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE tracked_games SET enabled = ? WHERE LOWER(game_name) = LOWER(?)",
            (int(enabled), game_name)
        )
        self.conn.commit()

    # ===== Game group operations =====

    def get_game_groups(self) -> List[GameGroup]:
        """Return all game groups with their member lists."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM game_groups ORDER BY group_name")
        groups = []
        for row in cursor.fetchall():
            cursor2 = self.conn.cursor()
            cursor2.execute(
                "SELECT game_name FROM game_group_members WHERE group_id = ? ORDER BY game_name",
                (row["id"],)
            )
            members = [r["game_name"] for r in cursor2.fetchall()]
            groups.append(GameGroup(
                id=row["id"],
                group_name=row["group_name"],
                members=members,
                created_at=row["created_at"],
            ))
        return groups

    def get_game_group(self, group_id: int) -> Optional[GameGroup]:
        """Return a single game group by ID, or None."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM game_groups WHERE id = ?", (group_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "SELECT game_name FROM game_group_members WHERE group_id = ? ORDER BY game_name",
            (group_id,)
        )
        members = [r["game_name"] for r in cursor.fetchall()]
        return GameGroup(id=row["id"], group_name=row["group_name"],
                         members=members, created_at=row["created_at"])

    def create_game_group(self, group_name: str) -> GameGroup:
        """Create a new game group."""
        cursor = self.conn.cursor()
        created_at = datetime.now(timezone.utc)
        cursor.execute(
            "INSERT INTO game_groups (group_name, created_at) VALUES (?, ?)",
            (group_name, created_at)
        )
        self.conn.commit()
        return GameGroup(id=cursor.lastrowid, group_name=group_name,
                         members=[], created_at=created_at)

    def delete_game_group(self, group_id: int) -> bool:
        """Delete a game group and its membership records."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM game_group_members WHERE group_id = ?", (group_id,))
        cursor.execute("DELETE FROM game_groups WHERE id = ?", (group_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def add_game_to_group(self, group_id: int, game_name: str) -> bool:
        """Add a game to a group. Returns False if already a member."""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO game_group_members (group_id, game_name) VALUES (?, ?)",
                (group_id, game_name)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_game_from_group(self, group_id: int, game_name: str) -> bool:
        """Remove a game from a group."""
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM game_group_members WHERE group_id = ? AND LOWER(game_name) = LOWER(?)",
            (group_id, game_name)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_groups_containing_game(self, game_name: str) -> List[int]:
        """Return IDs of groups that include the given game."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT DISTINCT group_id FROM game_group_members WHERE LOWER(game_name) = LOWER(?)",
            (game_name,)
        )
        return [row["group_id"] for row in cursor.fetchall()]

    # ===== Per-user game exclusion operations =====

    def is_user_excluded_from_game(self, user_id: int, game_name: str) -> bool:
        """Return True if the user has excluded this game from their tracking."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT COUNT(*) as cnt FROM user_game_exclusions
               WHERE user_id = ? AND LOWER(game_name) = LOWER(?)""",
            (user_id, game_name)
        )
        return cursor.fetchone()["cnt"] > 0

    def set_user_game_exclusion(self, user_id: int, game_name: str, excluded: bool) -> None:
        """Add or remove a per-game exclusion for a user."""
        cursor = self.conn.cursor()
        if excluded:
            cursor.execute(
                "INSERT OR IGNORE INTO user_game_exclusions (user_id, game_name) VALUES (?, ?)",
                (user_id, game_name)
            )
        else:
            cursor.execute(
                "DELETE FROM user_game_exclusions WHERE user_id = ? AND LOWER(game_name) = LOWER(?)",
                (user_id, game_name)
            )
        self.conn.commit()

    def get_user_game_exclusions(self, user_id: int) -> List[str]:
        """Return game names the user has explicitly excluded."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT game_name FROM user_game_exclusions WHERE user_id = ?",
            (user_id,)
        )
        return [row["game_name"] for row in cursor.fetchall()]

    # ===== Per-game / group playtime queries =====

    def get_playtime_for_game_window(self, user_id: int, game_name: str,
                                     window_type: str,
                                     session: Optional[PlaySession] = None) -> float:
        """Get playtime for a specific game in the given window (hours)."""
        if window_type == "session":
            if session and session.game_name.lower() == game_name.lower():
                return session.duration_hours
            return 0.0

        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc)

        if window_type == "rolling_7d":
            cutoff = now - timedelta(days=7)
        elif window_type == "daily":
            cutoff = now - timedelta(hours=24)
        elif window_type == "weekly":
            cutoff = now - timedelta(days=now.weekday(), hours=now.hour,
                                     minutes=now.minute, seconds=now.second,
                                     microseconds=now.microsecond)
        else:
            return 0.0

        cursor.execute(
            """SELECT SUM(duration_seconds) as total FROM play_sessions
               WHERE user_id = ? AND LOWER(game_name) = LOWER(?)
                 AND start_time >= ? AND end_time IS NOT NULL""",
            (user_id, game_name, cutoff)
        )
        row = cursor.fetchone()
        return (row["total"] or 0) / 3600

    def get_playtime_for_group_window(self, user_id: int, group_id: int,
                                      window_type: str,
                                      session: Optional[PlaySession] = None) -> float:
        """Get combined playtime for all games in a group for the given window."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT game_name FROM game_group_members WHERE group_id = ?",
            (group_id,)
        )
        game_names = [row["game_name"] for row in cursor.fetchall()]
        if not game_names:
            return 0.0
        return sum(
            self.get_playtime_for_game_window(user_id, gn, window_type, session)
            for gn in game_names
        )

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
                                     window_type: str,
                                     game_name: Optional[str] = None) -> bool:
        """Check if a threshold event exists for this user+rule within the current window.

        For global rules (game_name provided): dedup is per-game so separate games
        each get their own trigger record. Pass game_name=None for game-specific and
        group rules where the rule_id itself already encodes the scope.
        """
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

        if game_name is not None:
            cursor.execute(
                """SELECT COUNT(*) as cnt FROM threshold_events
                   WHERE user_id = ? AND rule_id = ? AND triggered_at >= ?
                     AND LOWER(game_name) = LOWER(?)""",
                (user_id, rule_id, window_start, game_name)
            )
        else:
            cursor.execute(
                """SELECT COUNT(*) as cnt FROM threshold_events
                   WHERE user_id = ? AND rule_id = ? AND triggered_at >= ?
                     AND game_name IS NULL""",
                (user_id, rule_id, window_start)
            )

        return cursor.fetchone()["cnt"] > 0

    def record_threshold_event(self, user_id: int, rule_id: int,
                               window_type: str,
                               game_name: Optional[str] = None) -> None:
        """Record that a threshold rule was triggered for a user.

        game_name should be set for global rules (enables per-game dedup),
        and left None for game-specific / group rules.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO threshold_events (user_id, rule_id, triggered_at, window_type, game_name)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, rule_id, datetime.now(timezone.utc), window_type, game_name)
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
            announcement_channel_id=row["announcement_channel_id"],
            warning_threshold_pct=row["warning_threshold_pct"],
            cooldown_days=row["cooldown_days"],
            weekly_recap_day=row["weekly_recap_day"],
            weekly_recap_hour=row["weekly_recap_hour"],
            last_weekly_recap_at=row["last_weekly_recap_at"],
        )

    def update_settings(self, **kwargs):
        """Update bot settings. Pass settings as keyword arguments."""
        allowed_fields = {
            "tracking_enabled", "target_game", "weekly_threshold_hours",
            "timeout_duration_hours", "announcement_channel_id",
            "warning_threshold_pct", "cooldown_days",
            "weekly_recap_day", "weekly_recap_hour", "last_weekly_recap_at",
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

    # ===== Audit log operations =====

    def add_audit_log(self, admin_id: int, action_type: str,
                      target_user_id: int, details: Optional[str] = None) -> AuditLog:
        """Record an admin action in the audit log."""
        cursor = self.conn.cursor()
        created_at = datetime.now(timezone.utc)
        cursor.execute(
            """INSERT INTO audit_log
               (admin_id, action_type, target_user_id, details, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (admin_id, action_type, target_user_id, details, created_at)
        )
        self.conn.commit()
        return AuditLog(
            id=cursor.lastrowid,
            admin_id=admin_id,
            action_type=action_type,
            target_user_id=target_user_id,
            details=details,
            created_at=created_at,
        )

    def get_audit_log(self, limit: int = 10) -> List[AuditLog]:
        """Get the most recent audit log entries."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        return [
            AuditLog(
                id=row["id"],
                admin_id=row["admin_id"],
                action_type=row["action_type"],
                target_user_id=row["target_user_id"],
                details=row["details"],
                created_at=row["created_at"],
            )
            for row in cursor.fetchall()
        ]

    # ===== Proactive warning operations =====

    def has_proactive_warning_been_sent(self, user_id: int, rule_id: int,
                                         window_type: str,
                                         game_name: Optional[str] = None) -> bool:
        """Check if a proactive warning was already sent for this user+rule in the window."""
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

        if game_name is not None:
            cursor.execute(
                """SELECT COUNT(*) as cnt FROM proactive_warnings
                   WHERE user_id = ? AND rule_id = ? AND warned_at >= ?
                     AND LOWER(game_name) = LOWER(?)""",
                (user_id, rule_id, window_start, game_name)
            )
        else:
            cursor.execute(
                """SELECT COUNT(*) as cnt FROM proactive_warnings
                   WHERE user_id = ? AND rule_id = ? AND warned_at >= ?
                     AND game_name IS NULL""",
                (user_id, rule_id, window_start)
            )
        return cursor.fetchone()["cnt"] > 0

    def record_proactive_warning(self, user_id: int, rule_id: int,
                                  window_type: str,
                                  game_name: Optional[str] = None) -> None:
        """Record that a proactive warning was sent."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO proactive_warnings (user_id, rule_id, warned_at, window_type, game_name)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, rule_id, datetime.now(timezone.utc), window_type, game_name)
        )
        self.conn.commit()

    def get_last_threshold_event_time(self, user_id: int) -> Optional[datetime]:
        """Get the timestamp of the user's most recent threshold event."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT MAX(triggered_at) as latest FROM threshold_events
               WHERE user_id = ?""",
            (user_id,)
        )
        row = cursor.fetchone()
        return row["latest"] if row and row["latest"] else None

    # ===== Leaderboard queries =====

    def get_leaderboard_most_hours(self, days: int = 7, limit: int = 5) -> list[tuple[int, float]]:
        """Get top users by total playtime hours in the rolling window."""
        cursor = self.conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor.execute("""
            SELECT ps.user_id, SUM(ps.duration_seconds) as total
            FROM play_sessions ps
            JOIN users u ON ps.user_id = u.user_id
            WHERE u.opted_in = 1
              AND u.leaderboard_visible = 1
              AND ps.end_time IS NOT NULL
              AND ps.start_time >= ?
            GROUP BY ps.user_id
            ORDER BY total DESC
            LIMIT ?
        """, (cutoff, limit))
        return [(row["user_id"], (row["total"] or 0) / 3600) for row in cursor.fetchall()]

    def get_leaderboard_longest_session(self, days: int = 7, limit: int = 5) -> list[tuple[int, float]]:
        """Get top users by their single longest session in the window."""
        cursor = self.conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor.execute("""
            SELECT ps.user_id, MAX(ps.duration_seconds) as longest
            FROM play_sessions ps
            JOIN users u ON ps.user_id = u.user_id
            WHERE u.opted_in = 1
              AND u.leaderboard_visible = 1
              AND ps.end_time IS NOT NULL
              AND ps.start_time >= ?
            GROUP BY ps.user_id
            ORDER BY longest DESC
            LIMIT ?
        """, (cutoff, limit))
        return [(row["user_id"], (row["longest"] or 0) / 3600) for row in cursor.fetchall()]

    def get_leaderboard_most_sessions(self, days: int = 7, limit: int = 5) -> list[tuple[int, int]]:
        """Get top users by session count in the window."""
        cursor = self.conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor.execute("""
            SELECT ps.user_id, COUNT(*) as cnt
            FROM play_sessions ps
            JOIN users u ON ps.user_id = u.user_id
            WHERE u.opted_in = 1
              AND u.leaderboard_visible = 1
              AND ps.end_time IS NOT NULL
              AND ps.start_time >= ?
            GROUP BY ps.user_id
            ORDER BY cnt DESC
            LIMIT ?
        """, (cutoff, limit))
        return [(row["user_id"], row["cnt"]) for row in cursor.fetchall()]

    # ===== User stats queries =====

    def get_daily_breakdown(self, user_id: int, days: int = 7) -> list[tuple[str, float]]:
        """Get hours per day for the last N days, filling gaps with 0.0."""
        cursor = self.conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor.execute("""
            SELECT DATE(start_time) as day, SUM(duration_seconds) as total
            FROM play_sessions
            WHERE user_id = ? AND start_time >= ? AND end_time IS NOT NULL
            GROUP BY DATE(start_time)
            ORDER BY day ASC
        """, (user_id, cutoff))
        rows = {row["day"]: (row["total"] or 0) / 3600 for row in cursor.fetchall()}

        result = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            result.append((d, rows.get(d, 0.0)))
        return result

    def get_session_stats(self, user_id: int, days: int = 7) -> dict:
        """Get session count, longest session, and average session length."""
        cursor = self.conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor.execute("""
            SELECT COUNT(*) as cnt,
                   MAX(duration_seconds) as longest,
                   AVG(duration_seconds) as average
            FROM play_sessions
            WHERE user_id = ? AND start_time >= ? AND end_time IS NOT NULL
        """, (user_id, cutoff))
        row = cursor.fetchone()
        return {
            "session_count": row["cnt"] or 0,
            "longest_session_hours": (row["longest"] or 0) / 3600,
            "avg_session_hours": (row["average"] or 0) / 3600,
        }

    def get_warning_timeout_counts(self, user_id: int) -> dict:
        """Get count of warnings and timeouts from threshold events."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT tr.action, COUNT(*) as cnt
            FROM threshold_events te
            JOIN threshold_rules tr ON te.rule_id = tr.id
            WHERE te.user_id = ?
            GROUP BY tr.action
        """, (user_id,))
        result = {"warn": 0, "timeout": 0}
        for row in cursor.fetchall():
            if row["action"] in result:
                result[row["action"]] = row["cnt"]
        return result

    # ===== Custom roast operations =====

    def get_custom_roasts(self, action: Optional[str] = None) -> List[CustomRoast]:
        """Get custom roast messages, optionally filtered by action type."""
        cursor = self.conn.cursor()
        if action:
            cursor.execute(
                "SELECT * FROM custom_roasts WHERE action = ? ORDER BY id", (action,)
            )
        else:
            cursor.execute("SELECT * FROM custom_roasts ORDER BY id")
        return [
            CustomRoast(id=row["id"], action=row["action"], message=row["message"])
            for row in cursor.fetchall()
        ]

    def add_custom_roast(self, action: str, message: str) -> CustomRoast:
        """Add a custom roast message."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO custom_roasts (action, message) VALUES (?, ?)",
            (action, message)
        )
        self.conn.commit()
        return CustomRoast(id=cursor.lastrowid, action=action, message=message)

    def delete_custom_roast(self, roast_id: int) -> bool:
        """Delete a custom roast by ID. Returns True if a row was deleted."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM custom_roasts WHERE id = ?", (roast_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ===== Weekly summary queries =====

    def get_weekly_summary(self, user_id: int) -> dict:
        """Get playtime summary for the previous calendar week (Mon-Sun)."""
        now = datetime.now(timezone.utc)
        # Previous week: go back to last Monday, then the Monday before that
        days_since_monday = now.weekday()
        this_monday = now - timedelta(
            days=days_since_monday, hours=now.hour,
            minutes=now.minute, seconds=now.second,
            microseconds=now.microsecond
        )
        last_monday = this_monday - timedelta(days=7)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT SUM(duration_seconds) as total,
                   COUNT(*) as cnt,
                   MAX(duration_seconds) as longest
            FROM play_sessions
            WHERE user_id = ?
              AND start_time >= ? AND start_time < ?
              AND end_time IS NOT NULL
        """, (user_id, last_monday, this_monday))
        row = cursor.fetchone()

        total_hours = (row["total"] or 0) / 3600
        session_count = row["cnt"] or 0
        longest_hours = (row["longest"] or 0) / 3600

        # Find busiest day
        cursor.execute("""
            SELECT strftime('%w', start_time) as dow, SUM(duration_seconds) as total
            FROM play_sessions
            WHERE user_id = ?
              AND start_time >= ? AND start_time < ?
              AND end_time IS NOT NULL
            GROUP BY dow
            ORDER BY total DESC
            LIMIT 1
        """, (user_id, last_monday, this_monday))
        busiest_row = cursor.fetchone()
        day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        busiest_day = day_names[int(busiest_row["dow"])] if busiest_row else None

        return {
            "total_hours": total_hours,
            "session_count": session_count,
            "longest_session_hours": longest_hours,
            "busiest_day": busiest_day,
        }

    # ===== Historical analytics queries =====

    def get_weekly_history(self, user_id: int, weeks: int = 8) -> list[tuple[str, float]]:
        """Get total playtime per calendar week for the last N weeks, oldest-first."""
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc)
        this_monday = now - timedelta(
            days=now.weekday(), hours=now.hour,
            minutes=now.minute, seconds=now.second, microseconds=now.microsecond
        )
        result = []
        for i in range(weeks - 1, -1, -1):
            week_start = this_monday - timedelta(weeks=i)
            week_end = week_start + timedelta(weeks=1)
            cursor.execute("""
                SELECT SUM(duration_seconds) as total
                FROM play_sessions
                WHERE user_id = ? AND start_time >= ? AND start_time < ?
                  AND end_time IS NOT NULL
            """, (user_id, week_start, week_end))
            row = cursor.fetchone()
            hours = (row["total"] or 0) / 3600
            label = week_start.strftime("%m/%d")
            result.append((label, hours))
        return result

    def get_monthly_history(self, user_id: int, months: int = 6) -> list[tuple[str, float]]:
        """Get total playtime per calendar month for the last N months, oldest-first."""
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc)
        result = []
        for i in range(months - 1, -1, -1):
            month_offset = now.month - 1 - i
            year = now.year + month_offset // 12
            month = month_offset % 12 + 1
            month_start = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
            cursor.execute("""
                SELECT SUM(duration_seconds) as total
                FROM play_sessions
                WHERE user_id = ? AND start_time >= ? AND start_time < ?
                  AND end_time IS NOT NULL
            """, (user_id, month_start, month_end))
            row = cursor.fetchone()
            hours = (row["total"] or 0) / 3600
            label = month_start.strftime("%b '%y")
            result.append((label, hours))
        return result

    def get_dow_pattern(self, user_id: int, days: int = 30) -> dict[int, float]:
        """Get total playtime per day of week (0=Mon..6=Sun) over the last N days."""
        cursor = self.conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        # SQLite strftime('%w'): 0=Sunday, 1=Monday, ..., 6=Saturday
        cursor.execute("""
            SELECT strftime('%w', start_time) as dow, SUM(duration_seconds) as total
            FROM play_sessions
            WHERE user_id = ? AND start_time >= ? AND end_time IS NOT NULL
            GROUP BY dow
        """, (user_id, cutoff))
        # Map SQLite dow (0=Sun..6=Sat) to Python weekday (0=Mon..6=Sun)
        sqlite_to_python = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
        result = {i: 0.0 for i in range(7)}
        for row in cursor.fetchall():
            python_dow = sqlite_to_python[int(row["dow"])]
            result[python_dow] = (row["total"] or 0) / 3600
        return result

    def close(self):
        """Close database connection."""
        self.conn.close()
