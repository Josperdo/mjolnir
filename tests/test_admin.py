"""Tests for the /mystats command in the Admin cog."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.cogs.admin import Admin
from app.core.models import BotSettings, PlaySession, User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = BotSettings(
    tracking_enabled=True,
    target_game="League of Legends",
    weekly_threshold_hours=20.0,
    timeout_duration_hours=24,
)


@pytest.fixture
def db():
    """Mock database. Each method is a MagicMock we configure per-test."""
    return MagicMock()


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
# Tests: embed content and color zones
# ---------------------------------------------------------------------------


async def test_mystats_green_zone(cog, db, interaction):
    """5 of 20 hours (25%) — well under 50%, so green. 15 hrs remaining."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_weekly_playtime.return_value = 5.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]

    assert embed.color == discord.Color.green()
    assert "5.0" in embed.fields[0].value       # playtime line
    assert "15.0 hrs" in embed.fields[1].value  # remaining
    assert len(embed.fields) == 2               # no active-session field


async def test_mystats_gold_zone(cog, db, interaction):
    """12 of 20 hours (60%) — between 50% and 75%, so gold."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_weekly_playtime.return_value = 12.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.gold()


async def test_mystats_orange_zone(cog, db, interaction):
    """16 of 20 hours (80%) — between 75% and 100%, so orange."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_weekly_playtime.return_value = 16.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.orange()


async def test_mystats_over_threshold(cog, db, interaction):
    """22.5 of 20 hours — red, bar fully filled, threshold exceeded text."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_weekly_playtime.return_value = 22.5
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.color == discord.Color.red()
    assert "█" * 20 in embed.fields[0].value          # bar is 100% full
    assert "Threshold exceeded" in embed.fields[1].value


# ---------------------------------------------------------------------------
# Tests: active session logic (the tricky part)
# ---------------------------------------------------------------------------


async def test_mystats_active_session_adds_live_time(cog, db, interaction):
    """6 hrs completed + 2 hrs live = ~8 hrs total. Active session field appears."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_weekly_playtime.return_value = 6.0
    db.get_active_session.return_value = PlaySession(
        id=1,
        user_id=123456789,
        game_name="League of Legends",
        start_time=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]

    # 6 + 2 = 8, which is < 10 (50% of 20) → still green
    assert embed.color == discord.Color.green()
    assert "8.0" in embed.fields[0].value

    # Active session field is the third field
    assert len(embed.fields) == 3
    assert embed.fields[2].name == "🎮 Active Session"
    assert "2.0" in embed.fields[2].value


async def test_mystats_active_session_pushes_into_orange(cog, db, interaction):
    """13 hrs completed + 2 hrs live = 15 hrs. Lands exactly on the 75% boundary → orange."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_weekly_playtime.return_value = 13.0
    db.get_active_session.return_value = PlaySession(
        id=2,
        user_id=123456789,
        game_name="League of Legends",
        start_time=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    # 13 + 2 = 15, which is >= 15 (75% of 20) → orange
    assert embed.color == discord.Color.orange()
