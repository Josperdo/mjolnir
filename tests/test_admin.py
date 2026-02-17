"""Tests for the Admin cog commands."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.cogs.admin import Admin
from app.core.models import AuditLog, BotSettings, PlaySession, ThresholdRule, User

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
    # Defaults for mystats enhanced fields
    mock.get_daily_breakdown.return_value = [
        ("2026-02-10", 0.0), ("2026-02-11", 0.0), ("2026-02-12", 0.0),
        ("2026-02-13", 0.0), ("2026-02-14", 0.0), ("2026-02-15", 0.0),
        ("2026-02-16", 0.0),
    ]
    mock.get_session_stats.return_value = {
        "session_count": 0, "longest_session_hours": 0.0, "avg_session_hours": 0.0,
    }
    mock.get_warning_timeout_counts.return_value = {"warn": 0, "timeout": 0}
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


# ---------------------------------------------------------------------------
# Tests: /hammer on / off / status
# ---------------------------------------------------------------------------


async def test_hammer_on_enables_tracking(cog, db, interaction):
    """Turning on tracking when currently disabled."""
    db.get_settings.return_value = BotSettings(tracking_enabled=False)

    await cog.hammer_on.callback(cog, interaction)

    db.update_settings.assert_called_once_with(tracking_enabled=True)
    msg = interaction.response.send_message.call_args[0][0]
    assert "activated" in msg.lower()


async def test_hammer_on_already_enabled(cog, db, interaction):
    """If tracking is already on, report that without updating."""
    db.get_settings.return_value = DEFAULT_SETTINGS  # tracking_enabled=True

    await cog.hammer_on.callback(cog, interaction)

    db.update_settings.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert "already enabled" in msg.lower()


async def test_hammer_off_disables_tracking(cog, db, interaction):
    """Turning off tracking when currently enabled."""
    db.get_settings.return_value = DEFAULT_SETTINGS  # tracking_enabled=True

    await cog.hammer_off.callback(cog, interaction)

    db.update_settings.assert_called_once_with(tracking_enabled=False)
    msg = interaction.response.send_message.call_args[0][0]
    assert "deactivated" in msg.lower()


async def test_hammer_off_already_disabled(cog, db, interaction):
    """If tracking is already off, report that without updating."""
    db.get_settings.return_value = BotSettings(tracking_enabled=False)

    await cog.hammer_off.callback(cog, interaction)

    db.update_settings.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert "already disabled" in msg.lower()


async def test_hammer_status_shows_embed(cog, db, interaction):
    """Status command returns an embed with key fields."""
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_opted_in_users.return_value = [1, 2, 3]
    cog.bot.get_channel.return_value = None

    await cog.hammer_status.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.title == "Mjolnir Status"
    field_names = [f.name for f in embed.fields]
    assert "Tracking Status" in field_names
    assert "Opted-In Users" in field_names
    assert "Target Game" in field_names


# ---------------------------------------------------------------------------
# Tests: /hammer setchannel
# ---------------------------------------------------------------------------


async def test_setchannel_saves_channel_id(cog, db, interaction):
    """setchannel stores the channel id in settings."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 999888777
    channel.mention = "#announcements"

    await cog.hammer_setchannel.callback(cog, interaction, channel)

    db.update_settings.assert_called_once_with(announcement_channel_id=999888777)
    msg = interaction.response.send_message.call_args[0][0]
    assert "#announcements" in msg


# ---------------------------------------------------------------------------
# Tests: /hammer setgame
# ---------------------------------------------------------------------------


async def test_setgame_updates_target(cog, db, interaction):
    """setgame stores new game name in settings."""
    await cog.hammer_setgame.callback(cog, interaction, "Valorant")

    db.update_settings.assert_called_once_with(target_game="Valorant")
    msg = interaction.response.send_message.call_args[0][0]
    assert "Valorant" in msg


async def test_setgame_rejects_empty(cog, db, interaction):
    """setgame rejects an empty string."""
    await cog.hammer_setgame.callback(cog, interaction, "   ")

    db.update_settings.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert "cannot be empty" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /hammer rules list
# ---------------------------------------------------------------------------


async def test_rules_list_shows_all_rules(cog, db, interaction):
    """rules list returns an embed with rule IDs."""
    await cog.rules_list.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.title == "Threshold Rules"
    # All 4 default rules should appear
    text = "\n".join(f.value for f in embed.fields)
    assert "#1" in text
    assert "#4" in text


async def test_rules_list_empty(cog, db, interaction):
    """rules list when no rules exist shows helpful message."""
    db.get_threshold_rules.return_value = []

    await cog.rules_list.callback(cog, interaction)

    msg = interaction.response.send_message.call_args[0][0]
    assert "no threshold rules" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /hammer rules add
# ---------------------------------------------------------------------------


async def test_rules_add_warn(cog, db, interaction):
    """Adding a warn rule calls add_threshold_rule correctly."""
    db.add_threshold_rule.return_value = ThresholdRule(
        id=5, hours=8.0, action="warn", window_type="daily"
    )

    await cog.rules_add.callback(
        cog, interaction, hours=8.0, action="warn", window="daily"
    )

    db.add_threshold_rule.assert_called_once_with(
        hours=8.0, action="warn", duration_hours=None, window_type="daily"
    )
    msg = interaction.response.send_message.call_args[0][0]
    assert "#5" in msg
    assert "warning" in msg.lower()


async def test_rules_add_timeout(cog, db, interaction):
    """Adding a timeout rule stores hours and duration."""
    db.add_threshold_rule.return_value = ThresholdRule(
        id=6, hours=12.0, action="timeout", duration_hours=2, window_type="rolling_7d"
    )

    await cog.rules_add.callback(
        cog, interaction, hours=12.0, action="timeout",
        window="rolling_7d", duration=2
    )

    db.add_threshold_rule.assert_called_once_with(
        hours=12.0, action="timeout", duration_hours=2, window_type="rolling_7d"
    )
    msg = interaction.response.send_message.call_args[0][0]
    assert "#6" in msg
    assert "timeout" in msg.lower()


async def test_rules_add_timeout_missing_duration(cog, db, interaction):
    """Timeout rule without duration is rejected."""
    await cog.rules_add.callback(
        cog, interaction, hours=10.0, action="timeout", window="rolling_7d"
    )

    db.add_threshold_rule.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert "duration" in msg.lower()


async def test_rules_add_invalid_hours(cog, db, interaction):
    """Zero or negative hours is rejected."""
    await cog.rules_add.callback(
        cog, interaction, hours=0, action="warn", window="daily"
    )

    db.add_threshold_rule.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert "greater than 0" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /hammer rules remove
# ---------------------------------------------------------------------------


async def test_rules_remove_success(cog, db, interaction):
    """Removing an existing rule returns confirmation."""
    db.delete_threshold_rule.return_value = True

    await cog.rules_remove.callback(cog, interaction, rule_id=2)

    db.delete_threshold_rule.assert_called_once_with(2)
    msg = interaction.response.send_message.call_args[0][0]
    assert "#2" in msg
    assert "removed" in msg.lower()


async def test_rules_remove_not_found(cog, db, interaction):
    """Removing a non-existent rule returns not-found message."""
    db.delete_threshold_rule.return_value = False

    await cog.rules_remove.callback(cog, interaction, rule_id=999)

    msg = interaction.response.send_message.call_args[0][0]
    assert "no rule found" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /hammer pardon
# ---------------------------------------------------------------------------


async def test_pardon_removes_timeout(cog, db, interaction):
    """Pardoning a user calls timeout(None) and logs the action."""
    target = MagicMock(spec=discord.Member)
    target.id = 987654321
    target.name = "TargetUser"
    target.mention = "<@987654321>"
    target.timeout = AsyncMock()

    await cog.hammer_pardon.callback(cog, interaction, target)

    target.timeout.assert_called_once()
    assert target.timeout.call_args[0][0] is None
    db.add_audit_log.assert_called_once()
    log_call = db.add_audit_log.call_args
    assert log_call[1]["action_type"] == "pardon"
    assert log_call[1]["target_user_id"] == 987654321
    msg = interaction.response.send_message.call_args[0][0]
    assert "pardoned" in msg.lower()


async def test_pardon_forbidden(cog, db, interaction):
    """Pardon fails gracefully when bot lacks permissions."""
    target = MagicMock(spec=discord.Member)
    target.id = 987654321
    target.mention = "<@987654321>"
    target.timeout = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No perms"))

    await cog.hammer_pardon.callback(cog, interaction, target)

    db.add_audit_log.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert "missing permissions" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /hammer exempt
# ---------------------------------------------------------------------------


async def test_exempt_toggles_on(cog, db, interaction):
    """Exempting a non-exempt user sets exempt to True."""
    target = MagicMock(spec=discord.Member)
    target.id = 987654321
    target.name = "TargetUser"
    target.mention = "<@987654321>"
    db.get_user.return_value = User(user_id=987654321, opted_in=True, exempt=False)

    await cog.hammer_exempt.callback(cog, interaction, target)

    db.set_user_exempt.assert_called_once_with(987654321, True)
    db.add_audit_log.assert_called_once()
    assert db.add_audit_log.call_args[1]["action_type"] == "exempt"
    msg = interaction.response.send_message.call_args[0][0]
    assert "exempt" in msg.lower()


async def test_exempt_toggles_off(cog, db, interaction):
    """Exempting an already-exempt user removes exemption."""
    target = MagicMock(spec=discord.Member)
    target.id = 987654321
    target.name = "TargetUser"
    target.mention = "<@987654321>"
    db.get_user.return_value = User(user_id=987654321, opted_in=True, exempt=True)

    await cog.hammer_exempt.callback(cog, interaction, target)

    db.set_user_exempt.assert_called_once_with(987654321, False)
    assert db.add_audit_log.call_args[1]["action_type"] == "unexempt"
    msg = interaction.response.send_message.call_args[0][0]
    assert "no longer exempt" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /hammer resetplaytime
# ---------------------------------------------------------------------------


async def test_resetplaytime_clears_data(cog, db, interaction):
    """Resetting playtime deletes sessions and events."""
    target = MagicMock(spec=discord.Member)
    target.id = 987654321
    target.name = "TargetUser"
    target.mention = "<@987654321>"
    db.delete_user_sessions.return_value = 5
    db.clear_threshold_events.return_value = 2

    await cog.hammer_resetplaytime.callback(cog, interaction, target)

    db.delete_user_sessions.assert_called_once_with(987654321)
    db.clear_threshold_events.assert_called_once_with(987654321)
    db.add_audit_log.assert_called_once()
    assert db.add_audit_log.call_args[1]["action_type"] == "reset_playtime"
    msg = interaction.response.send_message.call_args[0][0]
    assert "5" in msg
    assert "2" in msg


# ---------------------------------------------------------------------------
# Tests: /hammer audit
# ---------------------------------------------------------------------------


async def test_audit_shows_entries(cog, db, interaction):
    """Audit command shows log entries in an embed."""
    from datetime import datetime, timezone
    db.get_audit_log.return_value = [
        AuditLog(
            id=1, admin_id=111, action_type="pardon",
            target_user_id=222, details="Timeout removed",
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
    ]

    await cog.hammer_audit.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert embed.title == "Admin Audit Log"
    assert len(embed.fields) == 1
    assert "pardon" in embed.fields[0].name.lower()


async def test_audit_empty(cog, db, interaction):
    """Audit command with no entries shows a message."""
    db.get_audit_log.return_value = []

    await cog.hammer_audit.callback(cog, interaction)

    msg = interaction.response.send_message.call_args[0][0]
    assert "no audit log" in msg.lower()


# ---------------------------------------------------------------------------
# Tests: /leaderboard
# ---------------------------------------------------------------------------


async def test_leaderboard_shows_all_categories(cog, db, interaction):
    """Leaderboard embed has 3 fields when all categories have data."""
    db.get_leaderboard_most_hours.return_value = [(111, 10.5), (222, 8.0)]
    db.get_leaderboard_longest_session.return_value = [(222, 5.0), (111, 3.2)]
    db.get_leaderboard_most_sessions.return_value = [(111, 12), (222, 8)]

    await cog.leaderboard.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert "Leaderboard" in embed.title
    assert len(embed.fields) == 3
    assert "10.5" in embed.fields[0].value
    assert "5.0" in embed.fields[1].value
    assert "12 sessions" in embed.fields[2].value


async def test_leaderboard_empty_data(cog, db, interaction):
    """No data returns a plain text message, not an embed."""
    db.get_leaderboard_most_hours.return_value = []
    db.get_leaderboard_longest_session.return_value = []
    db.get_leaderboard_most_sessions.return_value = []

    await cog.leaderboard.callback(cog, interaction)

    msg = interaction.response.send_message.call_args[0][0]
    assert "no playtime data" in msg.lower()


async def test_leaderboard_partial_data(cog, db, interaction):
    """Only some categories have data — embed still works."""
    db.get_leaderboard_most_hours.return_value = [(111, 5.0)]
    db.get_leaderboard_longest_session.return_value = []
    db.get_leaderboard_most_sessions.return_value = [(111, 3)]

    await cog.leaderboard.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    assert len(embed.fields) == 2
    field_names = [f.name for f in embed.fields]
    assert "Most Hours Played" in field_names
    assert "Most Frequent Player" in field_names
    assert "Longest Single Session" not in field_names


async def test_leaderboard_is_public(cog, db, interaction):
    """Leaderboard is sent publicly (not ephemeral)."""
    db.get_leaderboard_most_hours.return_value = [(111, 5.0)]
    db.get_leaderboard_longest_session.return_value = []
    db.get_leaderboard_most_sessions.return_value = []

    await cog.leaderboard.callback(cog, interaction)

    kwargs = interaction.response.send_message.call_args[1]
    assert kwargs.get("ephemeral") is not True


# ---------------------------------------------------------------------------
# Tests: /mystats enhancements
# ---------------------------------------------------------------------------


async def test_mystats_daily_breakdown_field(cog, db, interaction):
    """Daily breakdown field shows day abbreviations and hours."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 3.0
    db.get_active_session.return_value = None
    db.get_daily_breakdown.return_value = [
        ("2026-02-10", 1.0), ("2026-02-11", 0.0), ("2026-02-12", 2.5),
        ("2026-02-13", 0.0), ("2026-02-14", 0.5), ("2026-02-15", 3.0),
        ("2026-02-16", 0.0),
    ]

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    breakdown_field = next(
        (f for f in embed.fields if "Daily Breakdown" in f.name), None
    )
    assert breakdown_field is not None
    assert "1.0h" in breakdown_field.value
    assert "2.5h" in breakdown_field.value
    # Should contain day abbreviations
    assert "Tue" in breakdown_field.value or "Mon" in breakdown_field.value


async def test_mystats_session_stats_field(cog, db, interaction):
    """Session stats field shows count, longest, and average."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 5.0
    db.get_active_session.return_value = None
    db.get_session_stats.return_value = {
        "session_count": 10,
        "longest_session_hours": 3.5,
        "avg_session_hours": 1.2,
    }

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    stats_field = next(
        (f for f in embed.fields if "Session Stats" in f.name), None
    )
    assert stats_field is not None
    assert "10" in stats_field.value
    assert "3.5" in stats_field.value
    assert "1.2" in stats_field.value


async def test_mystats_warning_timeout_counts(cog, db, interaction):
    """Warnings & Timeouts field shows counts."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 5.0
    db.get_active_session.return_value = None
    db.get_warning_timeout_counts.return_value = {"warn": 3, "timeout": 1}

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    wt_field = next(
        (f for f in embed.fields if "Warnings & Timeouts" in f.name), None
    )
    assert wt_field is not None
    assert "3" in wt_field.value
    assert "1" in wt_field.value


async def test_mystats_zero_stats(cog, db, interaction):
    """All-zero stats still render gracefully."""
    db.get_user.return_value = User(user_id=123456789, opted_in=True)
    db.get_settings.return_value = DEFAULT_SETTINGS
    db.get_playtime_for_window.return_value = 0.0
    db.get_active_session.return_value = None

    await cog.mystats.callback(cog, interaction)

    embed = interaction.response.send_message.call_args[1]["embed"]
    stats_field = next(
        (f for f in embed.fields if "Session Stats" in f.name), None
    )
    assert stats_field is not None
    assert "0" in stats_field.value

    wt_field = next(
        (f for f in embed.fields if "Warnings & Timeouts" in f.name), None
    )
    assert wt_field is not None
