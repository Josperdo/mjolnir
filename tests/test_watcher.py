"""Tests for the Watcher cog's threshold checking logic."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.cogs.watcher import Watcher
from app.core.models import BotSettings, PlaySession, ThresholdRule, User

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
    mock.get_last_threshold_event_time.return_value = None
    mock.has_proactive_warning_been_sent.return_value = False
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


# ---------------------------------------------------------------------------
# Tests: exempt users
# ---------------------------------------------------------------------------


async def test_exempt_user_skipped(cog, db):
    """Exempt user's presence updates are ignored."""
    db.get_user.return_value = User(user_id=123, opted_in=True, exempt=True)

    before = MagicMock(spec=discord.Member)
    before.id = 123
    before.activities = []

    after = MagicMock(spec=discord.Member)
    after.id = 123
    game = MagicMock(spec=discord.Game)
    game.type = discord.ActivityType.playing
    game.name = "League of Legends"
    after.activities = [game]

    await cog.on_presence_update(before, after)

    db.start_session.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: cooldown system
# ---------------------------------------------------------------------------


async def test_cooldown_clears_old_events(cog, db, member):
    """Events older than cooldown_days get cleared before evaluation."""
    # Last event was 5 days ago, cooldown is 3 days -> should clear
    db.get_last_threshold_event_time.return_value = (
        datetime.now(timezone.utc) - timedelta(days=5)
    )
    db.get_playtime_for_window.return_value = 5.0  # Below all thresholds

    await cog._check_threshold(member, COMPLETED_SESSION)

    db.clear_threshold_events.assert_called_once_with(123456789)


async def test_cooldown_preserves_recent_events(cog, db, member):
    """Events within cooldown_days are NOT cleared."""
    # Last event was 1 day ago, cooldown is 3 days -> should NOT clear
    db.get_last_threshold_event_time.return_value = (
        datetime.now(timezone.utc) - timedelta(days=1)
    )
    db.get_playtime_for_window.return_value = 5.0

    await cog._check_threshold(member, COMPLETED_SESSION)

    db.clear_threshold_events.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: proactive warnings
# ---------------------------------------------------------------------------


async def test_proactive_warning_sent_at_threshold(cog, db, member):
    """At 90% of next threshold (9h of 10h), a proactive DM is sent."""
    db.get_playtime_for_window.return_value = 9.5  # 95% of 10h

    await cog._check_threshold(member, COMPLETED_SESSION)

    # No threshold was crossed, so no threshold events recorded
    db.record_threshold_event.assert_not_called()

    # Proactive warning should be sent
    member.send.assert_called_once()
    msg = member.send.call_args[0][0]
    assert "9.5h" in msg
    assert "10.0h" in msg
    db.record_proactive_warning.assert_called_once()


async def test_proactive_warning_not_sent_below_pct(cog, db, member):
    """At 80% of threshold (8h of 10h), no proactive warning (pct=0.9)."""
    db.get_playtime_for_window.return_value = 8.0  # 80% of 10h

    await cog._check_threshold(member, COMPLETED_SESSION)

    db.record_threshold_event.assert_not_called()
    member.send.assert_not_called()
    db.record_proactive_warning.assert_not_called()


async def test_proactive_warning_dedup(cog, db, member):
    """Proactive warning is not sent twice for the same rule in a window."""
    db.get_playtime_for_window.return_value = 9.5
    db.has_proactive_warning_been_sent.return_value = True  # Already warned

    await cog._check_threshold(member, COMPLETED_SESSION)

    member.send.assert_not_called()
    db.record_proactive_warning.assert_not_called()


async def test_proactive_warning_disabled_when_pct_zero(cog, db, member):
    """No proactive warnings when warning_threshold_pct is 0."""
    db.get_settings.return_value = BotSettings(
        tracking_enabled=True,
        target_game="League of Legends",
        warning_threshold_pct=0.0,
    )
    db.get_playtime_for_window.return_value = 9.5

    await cog._check_threshold(member, COMPLETED_SESSION)

    member.send.assert_not_called()
    db.record_proactive_warning.assert_not_called()
