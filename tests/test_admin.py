"""Tests for the Admin cog commands."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.cogs.admin import Admin
from app.core.models import BotSettings, PlaySession, ThresholdRule, User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = BotSettings(
    tracking_enabled=True,
    target_game="League of Legends",
    weekly_threshold_hours=20.0,
    timeout_duration_hours=24,
)

DEFAULT_RULES = [
    ThresholdRule(id=1, hours=10.0, action="warn", window_type="rolling_7d"),
    ThresholdRule(id=2, hours=15.0, action="timeout", duration_hours=1, window_type="rolling_7d"),
    ThresholdRule(id=3, hours=20.0, action="timeout", duration_hours=6, window_type="rolling_7d"),
    ThresholdRule(id=4, hours=30.0, action="timeout", duration_hours=24, window_type="rolling_7d"),
]


@pytest.fixture
def db():
    """Mock database. Each method is a MagicMock we configure per-test."""
    mock = MagicMock()
    mock.get_threshold_rules.return_value = DEFAULT_RULES
    return mock


@pytest.fixture
def cog(db):
    """Admin cog wired to the mock db."""
    bot = MagicMock()
    bot.db = db
    return Admin(bot)


@pytest.fixture
def interaction():
    """Mock Discord interaction. send_message is AsyncMock so it can be awaited."""
    ctx = MagicMock(spec=discord.Interaction)
    ctx.user = MagicMock()
    ctx.user.id = 123456789
    ctx.response = MagicMock()
    ctx.response.send_message = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# Tests: early exit — user not tracked
# ---------------------------------------------------------------------------


async def test_mystats_no_db_record(cog, db, interaction):
    """User has never interacted with the bot — no row in users table."""
    db.get_user.return_value = None

    await cog.mystats.callback(cog, interaction)

    msg, kwargs = interaction.response.send_message.call_args
    assert "not currently opted in" in msg[0]
    assert kwargs["ephemeral"] is True


async def test_mystats_opted_out(cog, db, interaction):
    """User exists but opted_in is False."""
    db.get_user.return_value = User(user_id=123456789, opted_in=False)

    await cog.mystats.callback(cog, interaction)

    msg, kwargs = interaction.response.send_message.call_args
    assert "not currently opted in" in msg[0]


# ---------------------------------------------------------------------------
# Tests: embed color zones (based on closest threshold proximity)
# ---------------------------------------------------------------------------


async def test_mystats_green_zone(cog, db, interaction):
    """3h played — 30% of first threshold (10h), so green."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 3.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.green()
    assert "3.0" in embed.fields[0].value


async def test_mystats_gold_zone(cog, db, interaction):
    """6h of 10h first threshold (60%) — between 50% and 75%, so gold."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 6.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.gold()


async def test_mystats_orange_zone(cog, db, interaction):
    """8h of 10h first threshold (80%) — between 75% and 100%, so orange."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 8.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.orange()


async def test_mystats_red_zone_all_exceeded(cog, db, interaction):
    """35h played — all thresholds exceeded, bar full, red."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 35.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.red()
    assert "All thresholds exceeded" in embed.fields[0].value


# ---------------------------------------------------------------------------
# Tests: active session logic
# ---------------------------------------------------------------------------


async def test_mystats_active_session_adds_live_time(cog, db, interaction):
    """1h completed + 2h live = 3h total. Active session field appears."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 1.0
    db.get_active_session.return_value = PlaySession(
        id=1,
        user_id=123456789,
        game_name="League of Legends",
        start_time=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    # 1 + 2 = 3h, 30% of 10h first threshold -> green
    assert embed.color == discord.Color.green()
    assert "3.0" in embed.fields[0].value

    # Active session field should exist
    active_field = next((f for f in embed.fields if f.name == "Active Session"), None)
    assert active_field is not None
    assert "2.0" in active_field.value


# ---------------------------------------------------------------------------
# Tests: upcoming thresholds display
# ---------------------------------------------------------------------------


async def test_mystats_shows_upcoming_thresholds(cog, db, interaction):
    """With 5h played, all 4 rules should be in upcoming thresholds."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 5.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    upcoming_field = next((f for f in embed.fields if f.name == "Upcoming Thresholds"), None)
    assert upcoming_field is not None
    assert "10.0h" in upcoming_field.value
    assert "15.0h" in upcoming_field.value


async def test_mystats_no_upcoming_when_all_exceeded(cog, db, interaction):
    """With 35h played, no upcoming thresholds field."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 35.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    upcoming_field = next((f for f in embed.fields if f.name == "Upcoming Thresholds"), None)
    assert upcoming_field is None
