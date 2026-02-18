"""
Watcher cog for Mjolnir.
Monitors user presence and tracks playtime for all configured games.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import discord
from discord.ext import commands, tasks

from app.core.models import PlaySession, ThresholdRule
from app.core.rules import evaluate_rules, get_highest_action, get_roast


def _group_by_window(rules: List[ThresholdRule]) -> Dict[str, List[ThresholdRule]]:
    """Partition a list of rules into a dict keyed by window_type."""
    grouped: Dict[str, List[ThresholdRule]] = {}
    for rule in rules:
        grouped.setdefault(rule.window_type, []).append(rule)
    return grouped


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
        Called when a user's presence changes.
        Checks all enabled tracked games and starts/stops sessions accordingly.
        """
        settings = self.db.get_settings()
        if not settings.tracking_enabled:
            return

        user = self.db.get_user(after.id)
        if not user or not user.opted_in or user.exempt:
            return

        tracked_games = [g for g in self.db.get_tracked_games() if g.enabled]
        if not tracked_games:
            return

        for tracked_game in tracked_games:
            game_name = tracked_game.game_name

            # Respect per-game opt-out
            if self.db.is_user_excluded_from_game(after.id, game_name):
                continue

            before_active = self._get_game_activity(before, game_name)
            after_active = self._get_game_activity(after, game_name)

            if before_active is None and after_active is not None:
                await self._handle_game_start(after, game_name)
            elif before_active is not None and after_active is None:
                await self._handle_game_stop(after, game_name)

    def _get_game_activity(self, member: discord.Member, target_game: str) -> Optional[discord.Activity]:
        """
        Return the matching activity if the member is playing target_game, else None.
        Matching is case-insensitive substring.
        """
        if not member.activities:
            return None
        for activity in member.activities:
            if isinstance(activity, (discord.Game, discord.Activity)):
                if activity.type == discord.ActivityType.playing:
                    if activity.name and target_game.lower() in activity.name.lower():
                        return activity
        return None

    async def _handle_game_start(self, member: discord.Member, game_name: str):
        """Handle when a user starts playing a tracked game."""
        active_session = self.db.get_active_session(member.id, game_name)
        if active_session:
            return  # Already tracking this game

        session = self.db.start_session(member.id, game_name)
        print(f"Started tracking {member.name} playing {game_name} (Session ID: {session.id})")

    async def _handle_game_stop(self, member: discord.Member, game_name: str):
        """Handle when a user stops playing a tracked game."""
        active_session = self.db.get_active_session(member.id, game_name)
        if not active_session:
            return

        completed_session = self.db.end_session(active_session.id)
        if not completed_session:
            return

        print(f"Stopped tracking {member.name} playing {game_name} "
              f"(Duration: {completed_session.duration_hours:.2f}h)")

        await self._check_threshold(member, completed_session)

    async def _check_threshold(self, member: discord.Member,
                               completed_session: Optional[PlaySession] = None):
        """
        Evaluate all threshold rules across every scope:
          - Global rules  (game_name=None, group_id=None): applied per tracked game
          - Game-specific rules: applied only when that game's session ends
          - Group rules: applied based on combined playtime of the group
        Applies the most severe newly-triggered action, then sends proactive warnings.
        """
        settings = self.db.get_settings()
        all_rules = self.db.get_threshold_rules()
        if not all_rules:
            return

        self._apply_cooldown(member.id, settings.cooldown_days)

        game_name = completed_session.game_name if completed_session else ""

        # Partition rules by scope
        global_rules = [r for r in all_rules if r.game_name is None and r.group_id is None]
        game_rules = [
            r for r in all_rules
            if r.game_name and r.game_name.lower() == game_name.lower()
        ]
        group_ids = self.db.get_groups_containing_game(game_name)

        all_newly_triggered: List[ThresholdRule] = []

        # --- Global rules (deduped per-game so each game gets its own trigger) ---
        for window_type, window_rules in _group_by_window(global_rules).items():
            playtime = self.db.get_playtime_for_game_window(
                member.id, game_name, window_type, completed_session
            )
            already = {
                r.id for r in window_rules
                if self.db.has_threshold_been_triggered(
                    member.id, r.id, window_type, game_name=game_name
                )
            }
            all_newly_triggered.extend(evaluate_rules(window_rules, playtime, already))

        # --- Game-specific rules ---
        for window_type, window_rules in _group_by_window(game_rules).items():
            playtime = self.db.get_playtime_for_game_window(
                member.id, game_name, window_type, completed_session
            )
            already = {
                r.id for r in window_rules
                if self.db.has_threshold_been_triggered(member.id, r.id, window_type)
            }
            all_newly_triggered.extend(evaluate_rules(window_rules, playtime, already))

        # --- Group rules ---
        for group_id in group_ids:
            group_rules = [r for r in all_rules if r.group_id == group_id]
            for window_type, window_rules in _group_by_window(group_rules).items():
                playtime = self.db.get_playtime_for_group_window(
                    member.id, group_id, window_type, completed_session
                )
                already = {
                    r.id for r in window_rules
                    if self.db.has_threshold_been_triggered(member.id, r.id, window_type)
                }
                all_newly_triggered.extend(evaluate_rules(window_rules, playtime, already))

        if all_newly_triggered:
            for rule in all_newly_triggered:
                # Global rules record with game_name for per-game dedup;
                # game-specific and group rules record with None.
                dedup_game = game_name if (rule.game_name is None and rule.group_id is None) else None
                self.db.record_threshold_event(
                    member.id, rule.id, rule.window_type, game_name=dedup_game
                )

            highest = get_highest_action(all_newly_triggered)
            if highest is not None:
                if highest.action == "timeout" and highest.duration_hours:
                    await self._apply_timeout(member, highest, game_name)
                elif highest.action == "warn":
                    await self._send_warning(member, highest, game_name)
            return  # Skip proactive warnings when a threshold was crossed

        await self._check_proactive_warnings(
            member, all_rules, completed_session, settings, game_name
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
        all_rules: List[ThresholdRule],
        completed_session: Optional[PlaySession],
        settings,
        game_name: str,
    ):
        """Send a DM when the user is approaching the next unfired threshold."""
        pct = settings.warning_threshold_pct
        if pct <= 0:
            return

        global_rules = [r for r in all_rules if r.game_name is None and r.group_id is None]
        game_rules = [
            r for r in all_rules
            if r.game_name and r.game_name.lower() == game_name.lower()
        ]
        group_ids = self.db.get_groups_containing_game(game_name)

        async def _warn_for_scope(rules, playtime_fn, dedup_game=None):
            for window_type, window_rules in _group_by_window(rules).items():
                playtime = playtime_fn(window_type)
                for rule in window_rules:
                    if playtime >= rule.hours:
                        continue  # Already exceeded
                    if playtime < rule.hours * pct:
                        break  # Not close enough; rules are sorted ascending
                    if self.db.has_proactive_warning_been_sent(
                        member.id, rule.id, window_type, game_name=dedup_game
                    ):
                        break  # Already warned this window
                    await self._send_proactive_warning(member, rule, playtime, dedup_game)
                    self.db.record_proactive_warning(
                        member.id, rule.id, window_type, game_name=dedup_game
                    )
                    break  # Only warn about the closest upcoming rule per window

        await _warn_for_scope(
            global_rules,
            lambda wt: self.db.get_playtime_for_game_window(
                member.id, game_name, wt, completed_session
            ),
            dedup_game=game_name,
        )
        await _warn_for_scope(
            game_rules,
            lambda wt: self.db.get_playtime_for_game_window(
                member.id, game_name, wt, completed_session
            ),
        )
        for group_id in group_ids:
            g_rules = [r for r in all_rules if r.group_id == group_id]
            await _warn_for_scope(
                g_rules,
                lambda wt, gid=group_id: self.db.get_playtime_for_group_window(
                    member.id, gid, wt, completed_session
                ),
            )

    def _get_announcement_channel(self) -> Optional[discord.TextChannel]:
        """Get the configured announcement channel, or None if not set."""
        settings = self.db.get_settings()
        if not settings.announcement_channel_id:
            return None
        return self.bot.get_channel(settings.announcement_channel_id)

    async def _apply_timeout(self, member: discord.Member, rule: ThresholdRule,
                             game_name: str = ""):
        """Apply a timeout and post a public roast (or DM as fallback)."""
        timeout_duration = timedelta(hours=rule.duration_hours)
        custom_roasts = self.db.get_custom_roasts()
        roast = get_roast("timeout", custom_roasts)

        game_label = f" in {game_name}" if game_name else ""
        try:
            await member.timeout(
                timeout_duration,
                reason=f"Playtime threshold exceeded ({rule.hours}h {rule.window_type}{game_label})"
            )
            print(f"Timed out {member.name} for {rule.duration_hours}h "
                  f"(rule: {rule.hours}h {rule.window_type}{game_label})")
        except discord.Forbidden:
            print(f"Failed to timeout {member.name} (missing permissions)")
            return
        except discord.HTTPException as e:
            print(f"Failed to timeout {member.name}: {e}")
            return

        embed = discord.Embed(title="Timeout Notice", color=discord.Color.red())
        embed.add_field(name="Threshold", value=f"{rule.hours}h ({rule.window_type})", inline=True)
        embed.add_field(name="Timeout Duration", value=f"{rule.duration_hours}h", inline=True)
        if game_name:
            embed.add_field(name="Game", value=game_name, inline=True)

        channel = self._get_announcement_channel()
        if channel:
            try:
                await channel.send(f"{member.mention} {roast}", embed=embed)
                return
            except (discord.Forbidden, discord.HTTPException):
                pass

        try:
            await member.send(f"{roast}", embed=embed)
        except discord.Forbidden:
            print(f"Could not DM {member.name}")

    async def _send_warning(self, member: discord.Member, rule: ThresholdRule,
                            game_name: str = ""):
        """Post a public warning roast (or DM as fallback)."""
        custom_roasts = self.db.get_custom_roasts()
        roast = get_roast("warn", custom_roasts)

        embed = discord.Embed(title="Playtime Warning", color=discord.Color.gold())
        embed.add_field(name="Threshold", value=f"{rule.hours}h ({rule.window_type})", inline=True)
        if game_name:
            embed.add_field(name="Game", value=game_name, inline=True)

        channel = self._get_announcement_channel()
        if channel:
            try:
                await channel.send(f"{member.mention} {roast}", embed=embed)
                return
            except (discord.Forbidden, discord.HTTPException):
                pass

        try:
            await member.send(f"{roast}", embed=embed)
        except discord.Forbidden:
            print(f"Could not DM {member.name}")

    async def _send_proactive_warning(self, member: discord.Member, rule: ThresholdRule,
                                      playtime: float, game_name: Optional[str] = None):
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

        game_context = f" in **{game_name}**" if game_name else ""
        message = (
            f"You've played **{playtime:.1f}h**{game_context} {window_label}. "
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

        if now.weekday() != settings.weekly_recap_day:
            return
        if now.hour != settings.weekly_recap_hour:
            return

        if settings.last_weekly_recap_at:
            days_since = (now - settings.last_weekly_recap_at).total_seconds() / 86400
            if days_since < 1:
                return

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
                continue

            embed = discord.Embed(title="Your Weekly Recap", color=discord.Color.blue())
            embed.add_field(name="Total Playtime",
                            value=f"**{summary['total_hours']:.1f}h**", inline=True)
            embed.add_field(name="Sessions",
                            value=f"**{summary['session_count']}**", inline=True)
            embed.add_field(name="Longest Session",
                            value=f"**{summary['longest_session_hours']:.1f}h**", inline=True)
            if summary["busiest_day"]:
                embed.add_field(name="Busiest Day",
                                value=f"**{summary['busiest_day']}**", inline=True)

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
                pass

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
