"""
Watcher cog for Mjolnir.
Monitors user presence and tracks playtime for the target game.
"""
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from app.core.models import PlaySession, ThresholdRule
from app.core.rules import evaluate_rules, get_highest_action, get_roast


class Watcher(commands.Cog):
    """Monitors user activity and enforces playtime limits."""

    def __init__(self, bot):
        """Initialize the watcher cog."""
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        """Start background tasks when cog is loaded."""
        self.weekly_recap_loop.start()

    def cog_unload(self):
        """Clean up when cog is unloaded."""
        self.weekly_recap_loop.cancel()

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """
        Called when a user's presence changes (e.g., starts/stops playing a game).

        Args:
            before: Member state before the update
            after: Member state after the update
        """
        # Get current settings
        settings = self.db.get_settings()

        # Skip if tracking is disabled
        if not settings.tracking_enabled:
            return

        # Check if user is opted in and not exempt
        user = self.db.get_user(after.id)
        if not user or not user.opted_in:
            return

        if user.exempt:
            return

        # Get game activity before and after
        before_game = self._get_game_activity(before, settings.target_game)
        after_game = self._get_game_activity(after, settings.target_game)

        # Case 1: User started playing the target game
        if before_game is None and after_game is not None:
            await self._handle_game_start(after, settings.target_game)

        # Case 2: User stopped playing the target game
        elif before_game is not None and after_game is None:
            await self._handle_game_stop(after, settings.target_game)

    def _get_game_activity(self, member: discord.Member, target_game: str) -> discord.Activity:
        """
        Check if member is playing the target game.

        Args:
            member: Discord member to check
            target_game: Name of the game to look for

        Returns:
            The game activity if found, None otherwise
        """
        if not member.activities:
            return None

        for activity in member.activities:
            # Check for Game or Playing activity
            if isinstance(activity, (discord.Game, discord.Activity)):
                if activity.type == discord.ActivityType.playing:
                    # Case-insensitive match
                    if activity.name and target_game.lower() in activity.name.lower():
                        return activity

        return None

    async def _handle_game_start(self, member: discord.Member, game_name: str):
        """
        Handle when a user starts playing the target game.

        Args:
            member: Discord member who started playing
            game_name: Name of the game they started playing
        """
        # Check if there's already an active session (shouldn't happen, but safety check)
        active_session = self.db.get_active_session(member.id, game_name)
        if active_session:
            return  # Already tracking

        # Start new session
        session = self.db.start_session(member.id, game_name)
        print(f"Started tracking {member.name} playing {game_name} (Session ID: {session.id})")

    async def _handle_game_stop(self, member: discord.Member, game_name: str):
        """
        Handle when a user stops playing the target game.

        Args:
            member: Discord member who stopped playing
            game_name: Name of the game they stopped playing
        """
        # Get active session
        active_session = self.db.get_active_session(member.id, game_name)
        if not active_session:
            return  # No active session to end

        # End the session
        completed_session = self.db.end_session(active_session.id)
        if not completed_session:
            return

        duration_hours = completed_session.duration_hours
        print(f"Stopped tracking {member.name} playing {game_name} (Duration: {duration_hours:.2f}h)")

        # Check if user has exceeded any thresholds
        await self._check_threshold(member, completed_session)

    async def _check_threshold(self, member: discord.Member,
                               completed_session: PlaySession = None):
        """
        Evaluate all threshold rules across all window types.
        Applies the most severe newly-triggered action, then checks
        for proactive approaching-threshold warnings.

        Args:
            member: Discord member to check
            completed_session: The session that just ended (used for session window)
        """
        settings = self.db.get_settings()
        rules = self.db.get_threshold_rules()
        if not rules:
            return

        # Cooldown: if user has been clean for cooldown_days, reset events
        self._apply_cooldown(member.id, settings.cooldown_days)

        # Group rules by window_type
        rules_by_window: dict[str, list[ThresholdRule]] = {}
        for rule in rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        # Collect all newly triggered rules across all windows
        all_newly_triggered: list[ThresholdRule] = []

        for window_type, window_rules in rules_by_window.items():
            # Get playtime for this window
            playtime = self.db.get_playtime_for_window(
                member.id, window_type, session=completed_session
            )

            # Get already-triggered rule IDs for this user in this window
            already_triggered = set()
            for rule in window_rules:
                if self.db.has_threshold_been_triggered(member.id, rule.id, window_type):
                    already_triggered.add(rule.id)

            # Evaluate which rules are newly triggered
            newly_triggered = evaluate_rules(window_rules, playtime, already_triggered)
            all_newly_triggered.extend(newly_triggered)

        if all_newly_triggered:
            # Record all triggered events
            for rule in all_newly_triggered:
                self.db.record_threshold_event(member.id, rule.id, rule.window_type)

            # Apply the most severe action
            highest = get_highest_action(all_newly_triggered)
            if highest is not None:
                if highest.action == "timeout" and highest.duration_hours:
                    await self._apply_timeout(member, highest)
                elif highest.action == "warn":
                    await self._send_warning(member, highest)
            return  # Skip proactive warnings if a threshold was actually crossed

        # Proactive warnings for approaching thresholds
        await self._check_proactive_warnings(
            member, rules_by_window, completed_session, settings
        )

    def _apply_cooldown(self, user_id: int, cooldown_days: int):
        """Clear threshold events if user has been clean for cooldown_days."""
        if cooldown_days <= 0:
            return
        last_event_time = self.db.get_last_threshold_event_time(user_id)
        if last_event_time is None:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        if last_event_time < cutoff:
            cleared = self.db.clear_threshold_events(user_id)
            if cleared:
                print(f"Cooldown: cleared {cleared} threshold events for user {user_id}")

    async def _check_proactive_warnings(
        self,
        member: discord.Member,
        rules_by_window: dict[str, list[ThresholdRule]],
        completed_session: PlaySession,
        settings,
    ):
        """Send a DM when the user is approaching the next unfired threshold."""
        pct = settings.warning_threshold_pct
        if pct <= 0:
            return

        for window_type, window_rules in rules_by_window.items():
            playtime = self.db.get_playtime_for_window(
                member.id, window_type, session=completed_session
            )

            # Find the next rule the user hasn't exceeded yet
            for rule in window_rules:
                if playtime >= rule.hours:
                    continue  # Already exceeded

                # Check if approaching (at or above pct of threshold)
                if playtime < rule.hours * pct:
                    break  # Not close enough, and rules are sorted ascending

                # Check dedup
                if self.db.has_proactive_warning_been_sent(
                    member.id, rule.id, window_type
                ):
                    break  # Already warned for this rule in this window

                # Send the proactive warning
                await self._send_proactive_warning(member, rule, playtime)
                self.db.record_proactive_warning(
                    member.id, rule.id, window_type
                )
                break  # Only warn about the closest upcoming rule

    def _get_announcement_channel(self) -> discord.TextChannel | None:
        """Get the configured announcement channel, or None if not set."""
        settings = self.db.get_settings()
        if not settings.announcement_channel_id:
            return None
        return self.bot.get_channel(settings.announcement_channel_id)

    async def _apply_timeout(self, member: discord.Member, rule: ThresholdRule):
        """Apply a timeout and post a public roast (or DM as fallback)."""
        timeout_duration = timedelta(hours=rule.duration_hours)
        custom_roasts = self.db.get_custom_roasts()
        roast = get_roast("timeout", custom_roasts)

        try:
            await member.timeout(
                timeout_duration,
                reason=f"Playtime threshold exceeded ({rule.hours}h {rule.window_type})"
            )
            print(f"Timed out {member.name} for {rule.duration_hours}h "
                  f"(rule: {rule.hours}h {rule.window_type})")
        except discord.Forbidden:
            print(f"Failed to timeout {member.name} (missing permissions)")
            return
        except discord.HTTPException as e:
            print(f"Failed to timeout {member.name}: {e}")
            return

        # Build the embed
        embed = discord.Embed(
            title="Timeout Notice",
            color=discord.Color.red(),
        )
        embed.add_field(name="Threshold", value=f"{rule.hours}h ({rule.window_type})", inline=True)
        embed.add_field(name="Timeout Duration", value=f"{rule.duration_hours}h", inline=True)

        # Post publicly or fall back to DM
        channel = self._get_announcement_channel()
        if channel:
            try:
                await channel.send(
                    f"{member.mention} {roast}",
                    embed=embed,
                )
                return
            except (discord.Forbidden, discord.HTTPException):
                pass  # Fall through to DM

        # Fallback: DM
        try:
            await member.send(f"{roast}", embed=embed)
        except discord.Forbidden:
            print(f"Could not DM {member.name}")

    async def _send_warning(self, member: discord.Member, rule: ThresholdRule):
        """Post a public warning roast (or DM as fallback)."""
        custom_roasts = self.db.get_custom_roasts()
        roast = get_roast("warn", custom_roasts)

        embed = discord.Embed(
            title="Playtime Warning",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Threshold", value=f"{rule.hours}h ({rule.window_type})", inline=True)

        # Post publicly or fall back to DM
        channel = self._get_announcement_channel()
        if channel:
            try:
                await channel.send(
                    f"{member.mention} {roast}",
                    embed=embed,
                )
                return
            except (discord.Forbidden, discord.HTTPException):
                pass  # Fall through to DM

        # Fallback: DM
        try:
            await member.send(f"{roast}", embed=embed)
        except discord.Forbidden:
            print(f"Could not DM {member.name}")


    async def _send_proactive_warning(self, member: discord.Member,
                                      rule: ThresholdRule, playtime: float):
        """DM user that they are approaching a threshold."""
        remaining = rule.hours - playtime
        if rule.action == "timeout":
            action_text = f"a **{rule.duration_hours}h** timeout"
        else:
            action_text = "a warning"

        window_label = {
            "rolling_7d": "this week",
            "daily": "today",
            "weekly": "this calendar week",
            "session": "this session",
        }.get(rule.window_type, rule.window_type)

        message = (
            f"You've played **{playtime:.1f}h** {window_label}. "
            f"At **{rule.hours}h**, you'll get {action_text}. "
            f"(**{remaining:.1f}h** remaining)"
        )

        try:
            await member.send(message)
            print(f"Proactive warning sent to {member.name}: "
                  f"{playtime:.1f}h / {rule.hours}h {rule.window_type}")
        except discord.Forbidden:
            print(f"Could not DM proactive warning to {member.name}")


    # ===== Weekly Recap =====

    @tasks.loop(minutes=30)
    async def weekly_recap_loop(self):
        """Check if it's time to send the weekly recap."""
        settings = self.db.get_settings()
        now = datetime.now(timezone.utc)

        # Check if current day/hour matches schedule
        if now.weekday() != settings.weekly_recap_day:
            return
        if now.hour != settings.weekly_recap_hour:
            return

        # Dedup: don't send if already sent this week
        if settings.last_weekly_recap_at:
            days_since = (now - settings.last_weekly_recap_at).total_seconds() / 86400
            if days_since < 1:
                return  # Already sent within last 24 hours

        await self._send_weekly_summary_dms()
        await self._send_shame_leaderboard()

        self.db.update_settings(last_weekly_recap_at=now)
        print(f"Weekly recap sent at {now.strftime('%Y-%m-%d %H:%M UTC')}")

    @weekly_recap_loop.before_loop
    async def before_weekly_recap(self):
        """Wait for the bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()

    async def _send_weekly_summary_dms(self):
        """Send a weekly summary DM to each opted-in user."""
        user_ids = self.db.get_opted_in_users()

        for user_id in user_ids:
            summary = self.db.get_weekly_summary(user_id)
            if summary["session_count"] == 0:
                continue  # No sessions last week, skip

            embed = discord.Embed(
                title="Your Weekly Recap",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Total Playtime",
                value=f"**{summary['total_hours']:.1f}h**",
                inline=True,
            )
            embed.add_field(
                name="Sessions",
                value=f"**{summary['session_count']}**",
                inline=True,
            )
            embed.add_field(
                name="Longest Session",
                value=f"**{summary['longest_session_hours']:.1f}h**",
                inline=True,
            )
            if summary["busiest_day"]:
                embed.add_field(
                    name="Busiest Day",
                    value=f"**{summary['busiest_day']}**",
                    inline=True,
                )

            # Try to find the member in any guild and DM them
            member = None
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    break

            if not member:
                continue

            try:
                await member.send(embed=embed)
            except discord.Forbidden:
                pass  # User has DMs disabled

    async def _send_shame_leaderboard(self):
        """Post a weekly shame leaderboard to the announcement channel."""
        channel = self._get_announcement_channel()
        if not channel:
            return

        most_hours = self.db.get_leaderboard_most_hours()
        if not most_hours:
            return

        embed = discord.Embed(
            title="Weekly Shame Board",
            description="Last week's biggest offenders:",
            color=discord.Color.dark_red(),
        )

        lines = [
            f"{i+1}. <@{uid}> — {hours:.1f}h"
            for i, (uid, hours) in enumerate(most_hours)
        ]
        embed.add_field(name="Most Hours Played", value="\n".join(lines), inline=False)

        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            print("Failed to post weekly shame leaderboard")


async def setup(bot):
    """Load the Watcher cog."""
    await bot.add_cog(Watcher(bot))
