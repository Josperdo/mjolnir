"""
Database models for Mjolnir.
Defines the schema for tracking users, play sessions, and settings.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class User:
    """Represents a Discord user being tracked."""
    user_id: int  # Discord user ID
    opted_in: bool = False
    exempt: bool = False
    leaderboard_visible: bool = True
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


@dataclass
class PlaySession:
    """Represents a single play session."""
    id: Optional[int] = None
    user_id: int = 0
    game_name: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: int = 0

    def __post_init__(self):
        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)

    @property
    def duration_hours(self) -> float:
        """Returns duration in hours."""
        return self.duration_seconds / 3600

    @property
    def is_active(self) -> bool:
        """Returns True if session is still ongoing."""
        return self.end_time is None


@dataclass
class BotSettings:
    """Global bot settings."""
    tracking_enabled: bool = True
    target_game: str = "League of Legends"
    weekly_threshold_hours: float = 20.0
    timeout_duration_hours: int = 24
    announcement_channel_id: Optional[int] = None
    warning_threshold_pct: float = 0.9
    cooldown_days: int = 3
    weekly_recap_day: int = 0  # 0=Monday, 6=Sunday
    weekly_recap_hour: int = 9  # UTC hour (0-23)
    last_weekly_recap_at: Optional[datetime] = None


@dataclass
class TrackedGame:
    """A game the bot monitors for playtime."""
    id: Optional[int] = None
    game_name: str = ""
    enabled: bool = True
    added_at: Optional[datetime] = None

    def __post_init__(self):
        if self.added_at is None:
            self.added_at = datetime.now(timezone.utc)


@dataclass
class GameGroup:
    """A named group of games whose playtime is tracked combined."""
    id: Optional[int] = None
    group_name: str = ""
    members: list = field(default_factory=list)  # List[str] of game_names
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


@dataclass
class ThresholdRule:
    """A single threshold rule defining an action at a playtime boundary."""
    id: Optional[int] = None
    hours: float = 0.0
    action: str = "warn"  # 'warn' or 'timeout'
    duration_hours: Optional[int] = None  # timeout duration; None for warn
    message: Optional[str] = None
    window_type: str = "rolling_7d"  # 'daily', 'weekly', 'session', 'rolling_7d'
    game_name: Optional[str] = None  # None = applies to every tracked game individually
    group_id: Optional[int] = None   # Set for group-scoped rules


@dataclass
class ThresholdEvent:
    """Records that a threshold rule was triggered for a user."""
    id: Optional[int] = None
    user_id: int = 0
    rule_id: int = 0
    triggered_at: Optional[datetime] = None
    window_type: str = "rolling_7d"

    def __post_init__(self):
        if self.triggered_at is None:
            self.triggered_at = datetime.now(timezone.utc)


@dataclass
class AuditLog:
    """Records an admin action for accountability."""
    id: Optional[int] = None
    admin_id: int = 0
    action_type: str = ""  # 'pardon', 'exempt', 'unexempt', 'reset_playtime'
    target_user_id: int = 0
    details: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


@dataclass
class CustomRoast:
    """A custom roast message configured by admins."""
    id: Optional[int] = None
    action: str = "warn"  # 'warn' or 'timeout'
    message: str = ""
