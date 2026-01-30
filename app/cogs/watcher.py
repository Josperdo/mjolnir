"""
Watcher cog for Mjolnir.
Monitors user presence and tracks playtime for the target game.
"""
from datetime import timedelta, timezone

import discord
from discord.ext import commands


class Watcher(commands.Cog):
    """Monitors user activity and enforces playtime limits."""

    def __init__(self, bot):
        """Initialize the watcher cog."""
        self.bot = bot
        self.db = bot.db

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

        # Check if user is opted in
        user = self.db.get_user(after.id)
        if not user or not user.opted_in:
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
        print(f"▶️  {member.name} started playing {game_name} (Session ID: {session.id})")

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
        print(f"⏹️  {member.name} stopped playing {game_name} (Duration: {duration_hours:.2f}h)")

        # Check if user has exceeded weekly threshold
        await self._check_threshold(member)

    async def _check_threshold(self, member: discord.Member):
        """
        Check if user has exceeded the weekly playtime threshold.
        If so, apply a timeout.

        Args:
            member: Discord member to check
        """
        settings = self.db.get_settings()

        # Get weekly playtime
        weekly_hours = self.db.get_weekly_playtime(member.id)

        # Check if threshold exceeded
        if weekly_hours > settings.weekly_threshold_hours:
            # Calculate timeout duration
            timeout_duration = timedelta(hours=settings.timeout_duration_hours)

            try:
                # Apply timeout
                await member.timeout(
                    timeout_duration,
                    reason=f"Exceeded weekly playtime limit ({weekly_hours:.1f}h / {settings.weekly_threshold_hours}h)"
                )

                print(f"🔨 {member.name} timed out for {settings.timeout_duration_hours}h "
                      f"(played {weekly_hours:.1f}h this week)")

                # Try to send a DM to the user
                try:
                    await member.send(
                        f"⚠️ You've been timed out for **{settings.timeout_duration_hours} hours**.\n\n"
                        f"**Reason:** You've played {settings.target_game} for "
                        f"**{weekly_hours:.1f} hours** this week, exceeding the "
                        f"**{settings.weekly_threshold_hours}h** limit.\n\n"
                        f"Take a break and we'll see you when the timeout expires!"
                    )
                except discord.Forbidden:
                    # User has DMs disabled
                    print(f"   ⚠️  Could not DM {member.name} (DMs disabled)")

            except discord.Forbidden:
                print(f"   ❌ Failed to timeout {member.name} (missing permissions)")
            except discord.HTTPException as e:
                print(f"   ❌ Failed to timeout {member.name}: {e}")


async def setup(bot):
    """Load the Watcher cog."""
    await bot.add_cog(Watcher(bot))
