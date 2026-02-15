"""Tests for the Watcher cog's threshold checking logic."""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.cogs.watcher import Watcher
from app.core.models import BotSettings, PlaySession, ThresholdRule

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = BotSettings(
    tracking_enabled=True,
    target_game="League of Legends",
    weekly_threshold_hours=20.0,
    timeout_duration_hours=24,
    announcement_channel_id=None,
)

SETTINGS_WITH_CHANNEL = BotSettings(
    tracking_enabled=True,
    target_game="League of Legends",
    weekly_threshold_hours=20.0,
    timeout_duration_hours=24,
    announcement_channel_id=999,
)

DEFAULT_RULES = [
    ThresholdRule(id=1, hours=10.0, action="warn", window_type="rolling_7d"),
    ThresholdRule(id=2, hours=15.0, action="timeout", duration_hours=1, window_type="rolling_7d"),
    ThresholdRule(id=3, hours=20.0, action="timeout", duration_hours=6, window_type="rolling_7d"),
    ThresholdRule(id=4, hours=30.0, action="timeout", duration_hours=24, window_type="rolling_7d"),
]

COMPLETED_SESSION = PlaySession(
    id=1,
    user_id=123456789,
    game_name="League of Legends",
    duration_seconds=7200,  # 2 hours
)


@pytest.fixture
def db():
    """Mock database."""
    mock = MagicMock()
    mock.get_threshold_rules.return_value = DEFAULT_RULES
    mock.get_settings.return_value = DEFAULT_SETTINGS
    mock.has_threshold_been_triggered.return_value = False
    return mock


@pytest.fixture
def cog(db):
    """Watcher cog wired to mock db."""
    bot = MagicMock()
    bot.db = db
    bot.get_channel.return_value = None
    return Watcher(bot)


@pytest.fixture
def member():
    """Mock Discord member."""
    m = MagicMock(spec=discord.Member)
    m.id = 123456789
    m.name = "TestUser"
    m.mention = "<@123456789>"
    m.timeout = AsyncMock()
    m.send = AsyncMock()
    return m


# ---------------------------------------------------------------------------
# Tests: _check_threshold — no rules triggered
# ---------------------------------------------------------------------------


async def test_check_threshold_below_all(cog, db, member):
    """Playtime below all thresholds does nothing."""
    db.get_playtime_for_window.return_value = 5.0

    await cog._check_threshold(member, COMPLETED_SESSION)

    db.record_threshold_event.assert_not_called()
    member.timeout.assert_not_called()
    member.send.assert_not_called()


async def test_check_threshold_no_rules(cog, db, member):
    """No rules configured does nothing."""
    db.get_threshold_rules.return_value = []

    await cog._check_threshold(member, COMPLETED_SESSION)

    member.timeout.assert_not_called()
    member.send.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _check_threshold — warn triggered
# ---------------------------------------------------------------------------


@patch("app.cogs.watcher.get_roast", return_value="Touch grass challenge: FAILED")
async def test_check_threshold_warn(mock_roast, cog, db, member):
    """Exceeding warn threshold sends a warning (DM fallback, no channel)."""
    db.get_playtime_for_window.return_value = 12.0

    await cog._check_threshold(member, COMPLETED_SESSION)

    # Should record the event for rule 1 (10h warn)
    db.record_threshold_event.assert_called_once_with(123456789, 1, "rolling_7d")

    # Should NOT timeout
    member.timeout.assert_not_called()

    # Should DM (no announcement channel)
    member.send.assert_called_once()
    call_args = member.send.call_args
    assert "Touch grass" in call_args[0][0]


# ---------------------------------------------------------------------------
# Tests: _check_threshold — timeout triggered
# ---------------------------------------------------------------------------


@patch("app.cogs.watcher.get_roast", return_value="Mjolnir has spoken.")
async def test_check_threshold_timeout(mock_roast, cog, db, member):
    """Exceeding timeout threshold applies timeout and sends message."""
    db.get_playtime_for_window.return_value = 22.0

    await cog._check_threshold(member, COMPLETED_SESSION)

    # Should record events for rules 1 (warn), 2 (timeout 1h), 3 (timeout 6h)
    assert db.record_threshold_event.call_count == 3

    # Should timeout with the highest duration (rule 3 = 6h)
    member.timeout.assert_called_once()
    timeout_args = member.timeout.call_args
    assert timeout_args[0][0] == timedelta(hours=6)


# ---------------------------------------------------------------------------
# Tests: _check_threshold — dedup
# ---------------------------------------------------------------------------


@patch("app.cogs.watcher.get_roast", return_value="Test roast")
async def test_check_threshold_skips_already_triggered(mock_roast, cog, db, member):
    """Already-triggered rules are skipped."""
    db.get_playtime_for_window.return_value = 22.0

    # Rules 1 and 2 already triggered
    def triggered_side_effect(user_id, rule_id, window_type):
        return rule_id in (1, 2)

    db.has_threshold_been_triggered.side_effect = triggered_side_effect

    await cog._check_threshold(member, COMPLETED_SESSION)

    # Only rule 3 should be recorded
    db.record_threshold_event.assert_called_once_with(123456789, 3, "rolling_7d")

    # Should timeout with rule 3 (6h)
    member.timeout.assert_called_once()


async def test_check_threshold_all_already_triggered(cog, db, member):
    """All matching rules already triggered does nothing."""
    db.get_playtime_for_window.return_value = 22.0
    db.has_threshold_been_triggered.return_value = True

    await cog._check_threshold(member, COMPLETED_SESSION)

    db.record_threshold_event.assert_not_called()
    member.timeout.assert_not_called()
    member.send.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: public channel announcement
# ---------------------------------------------------------------------------


@patch("app.cogs.watcher.get_roast", return_value="Public roast!")
async def test_check_threshold_posts_to_channel(mock_roast, cog, db, member):
    """When announcement channel is configured, posts there instead of DM."""
    db.get_settings.return_value = SETTINGS_WITH_CHANNEL
    db.get_playtime_for_window.return_value = 12.0

    # Set up a mock channel
    channel = MagicMock()
    channel.send = AsyncMock()
    cog.bot.get_channel.return_value = channel

    await cog._check_threshold(member, COMPLETED_SESSION)

    # Should post to channel, not DM
    channel.send.assert_called_once()
    call_kwargs = channel.send.call_args
    assert "<@123456789>" in call_kwargs[0][0]
    assert "Public roast!" in call_kwargs[0][0]
    member.send.assert_not_called()


@patch("app.cogs.watcher.get_roast", return_value="DM fallback")
async def test_check_threshold_falls_back_to_dm(mock_roast, cog, db, member):
    """When channel send fails, falls back to DM."""
    db.get_settings.return_value = SETTINGS_WITH_CHANNEL
    db.get_playtime_for_window.return_value = 12.0

    # Channel exists but send fails
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No perms"))
    cog.bot.get_channel.return_value = channel

    await cog._check_threshold(member, COMPLETED_SESSION)

    # Should fall back to DM
    member.send.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: multi-window
# ---------------------------------------------------------------------------


@patch("app.cogs.watcher.get_roast", return_value="Daily roast")
async def test_check_threshold_multi_window(mock_roast, cog, db, member):
    """Daily rule triggers but rolling_7d does not."""
    daily_rule = ThresholdRule(id=10, hours=4.0, action="warn", window_type="daily")
    rolling_rule = ThresholdRule(id=1, hours=10.0, action="warn", window_type="rolling_7d")
    db.get_threshold_rules.return_value = [rolling_rule, daily_rule]

    def playtime_side_effect(user_id, window_type, session=None):
        if window_type == "daily":
            return 5.0  # exceeds 4h daily
        elif window_type == "rolling_7d":
            return 8.0  # does not exceed 10h rolling
        return 0.0

    db.get_playtime_for_window.side_effect = playtime_side_effect

    await cog._check_threshold(member, COMPLETED_SESSION)

    # Only daily rule should trigger
    db.record_threshold_event.assert_called_once_with(123456789, 10, "daily")

    # Warn, not timeout
    member.timeout.assert_not_called()
    member.send.assert_called_once()
