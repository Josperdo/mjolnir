"""
Admin cog for Mjolnir.
Provides commands for users to opt-in/out and admins to control the bot.
"""
import discord
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands


# Display labels for window types
WINDOW_LABELS = {
    "rolling_7d": "Rolling 7-Day",
    "daily": "Daily (24h)",
    "weekly": "Calendar Week",
    "session": "Per Session",
}


class Admin(commands.Cog):
    """Admin and user management commands."""

    def __init__(self, bot):
        """Initialize the admin cog."""
        self.bot = bot
        self.db = bot.db

    # ===== User Commands =====

    @app_commands.command(name="opt-in", description="Opt in to playtime tracking")
    async def opt_in(self, interaction: discord.Interaction):
        """Allow user to opt in to tracking."""
        # Set user as opted in
        self.db.set_user_opt_in(interaction.user.id, True)

        settings = self.db.get_settings()
        rules = self.db.get_threshold_rules()

        # Build rules summary grouped by window type
        rules_by_window: dict[str, list] = {}
        for rule in rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        rules_lines = []
        for window_type, window_rules in rules_by_window.items():
            label = WINDOW_LABELS.get(window_type, window_type)
            entries = []
            for r in window_rules:
                if r.action == "timeout":
                    entries.append(f"{r.hours}h = {r.duration_hours}h timeout")
                else:
                    entries.append(f"{r.hours}h = warning")
            rules_lines.append(f"**{label}:** {', '.join(entries)}")

        rules_text = "\n".join(rules_lines) if rules_lines else "No rules configured."

        await interaction.response.send_message(
            f"You've opted in to playtime tracking!\n\n"
            f"**Target game:** {settings.target_game}\n\n"
            f"**Thresholds:**\n{rules_text}\n\n"
            f"If you exceed a threshold, you may be warned or timed out.\n"
            f"Use `/opt-out` to stop tracking at any time.",
            ephemeral=True
        )

        print(f"{interaction.user.name} opted in to tracking")

    @app_commands.command(name="opt-out", description="Opt out of playtime tracking")
    async def opt_out(self, interaction: discord.Interaction):
        """Allow user to opt out of tracking."""
        # Set user as opted out
        self.db.set_user_opt_in(interaction.user.id, False)

        await interaction.response.send_message(
            "You've opted out of playtime tracking.\n\n"
            "Your previous play sessions are still saved, but we won't track new sessions.\n"
            "Use `/opt-in` if you change your mind!",
            ephemeral=True
        )

        print(f"{interaction.user.name} opted out of tracking")

    @app_commands.command(name="mystats", description="View your weekly playtime stats")
    async def mystats(self, interaction: discord.Interaction):
        """Show the invoking user their current playtime across all tracked windows."""
        user = self.db.get_user(interaction.user.id)
        if user is None or not user.opted_in:
            await interaction.response.send_message(
                "You're not currently opted in to playtime tracking.\n"
                "Use `/opt-in` to start!",
                ephemeral=True
            )
            return

        settings = self.db.get_settings()
        rules = self.db.get_threshold_rules()

        # Group rules by window type
        rules_by_window: dict[str, list] = {}
        for rule in rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        # If no rules exist, fall back to legacy single-threshold display
        if not rules:
            rules_by_window = {"rolling_7d": []}

        # Compute playtime for each window and find the closest threshold
        # Track the highest fill percentage for embed color
        max_fill_pct = 0.0

        embed = discord.Embed(title="Your Playtime Stats", color=discord.Color.green())

        # Get active session for live time calculation
        active_session = self.db.get_active_session(interaction.user.id, settings.target_game)
        active_elapsed = 0.0
        if active_session:
            active_elapsed = (
                datetime.now(timezone.utc) - active_session.start_time
            ).total_seconds() / 3600

        for window_type in ["rolling_7d", "daily", "weekly", "session"]:
            window_rules = rules_by_window.get(window_type)
            if not window_rules:
                continue

            label = WINDOW_LABELS.get(window_type, window_type)

            # Get base playtime (completed sessions)
            playtime = self.db.get_playtime_for_window(
                interaction.user.id, window_type
            )

            # Add active session elapsed time for non-session windows
            if window_type != "session" and active_elapsed > 0:
                playtime += active_elapsed

            # Find the next threshold the user hasn't exceeded yet
            next_threshold = None
            for r in window_rules:
                if playtime < r.hours:
                    next_threshold = r
                    break

            # Use highest rule as the bar cap if all exceeded
            bar_cap = next_threshold.hours if next_threshold else window_rules[-1].hours
            fill_pct = min(playtime / bar_cap, 1.0) if bar_cap > 0 else 0.0
            if fill_pct > max_fill_pct:
                max_fill_pct = fill_pct

            # Progress bar
            bar_length = 20
            filled = min(int(fill_pct * bar_length), bar_length)
            bar = "\u2588" * filled + "\u2591" * (bar_length - filled)

            # Next action text
            if next_threshold:
                remaining = max(next_threshold.hours - playtime, 0.0)
                next_text = f"{remaining:.1f}h until {next_threshold.action}"
            else:
                next_text = "All thresholds exceeded"

            embed.add_field(
                name=label,
                value=f"{bar}\n**{playtime:.1f}** / **{bar_cap}** hours\n{next_text}",
                inline=False,
            )

        # Active session field
        if active_session and active_elapsed > 0:
            embed.add_field(
                name="Active Session",
                value=f"**{active_elapsed:.1f} hrs** this session",
                inline=True,
            )

        # Upcoming thresholds summary
        upcoming_lines = []
        for window_type, window_rules in rules_by_window.items():
            label = WINDOW_LABELS.get(window_type, window_type)
            playtime = self.db.get_playtime_for_window(
                interaction.user.id, window_type
            )
            if window_type != "session" and active_elapsed > 0:
                playtime += active_elapsed

            pending = [r for r in window_rules if playtime < r.hours]
            if pending:
                entries = []
                for r in pending:
                    if r.action == "timeout":
                        entries.append(f"{r.hours}h (timeout {r.duration_hours}h)")
                    else:
                        entries.append(f"{r.hours}h (warn)")
                upcoming_lines.append(f"**{label}:** {', '.join(entries)}")

        if upcoming_lines:
            embed.add_field(
                name="Upcoming Thresholds",
                value="\n".join(upcoming_lines),
                inline=False,
            )

        # Set embed color based on closest threshold proximity
        if max_fill_pct >= 1.0:
            embed.color = discord.Color.red()
        elif max_fill_pct >= 0.75:
            embed.color = discord.Color.orange()
        elif max_fill_pct >= 0.5:
            embed.color = discord.Color.gold()
        else:
            embed.color = discord.Color.green()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ===== Admin Commands =====

    @app_commands.command(name="hammer", description="Control Mjolnir's tracking system")
    @app_commands.describe(action="Enable, disable, or check status of tracking")
    @app_commands.choices(action=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
        app_commands.Choice(name="status", value="status"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def hammer(self, interaction: discord.Interaction, action: str):
        """
        Admin command to control tracking.

        Args:
            interaction: Discord interaction
            action: 'on', 'off', or 'status'
        """
        settings = self.db.get_settings()

        if action == "on":
            if settings.tracking_enabled:
                await interaction.response.send_message(
                    "Tracking is already enabled.",
                    ephemeral=True
                )
            else:
                self.db.update_settings(tracking_enabled=True)
                await interaction.response.send_message(
                    "**Mjolnir activated!**\n\n"
                    "Playtime tracking is now **enabled**.\n"
                    f"Monitoring: **{settings.target_game}**",
                    ephemeral=False  # Public announcement
                )
                print("Tracking enabled by admin")

        elif action == "off":
            if not settings.tracking_enabled:
                await interaction.response.send_message(
                    "Tracking is already disabled.",
                    ephemeral=True
                )
            else:
                self.db.update_settings(tracking_enabled=False)
                await interaction.response.send_message(
                    "**Mjolnir deactivated.**\n\n"
                    "Playtime tracking is now **disabled**.\n"
                    "Active sessions will not be tracked.",
                    ephemeral=False  # Public announcement
                )
                print("Tracking disabled by admin")

        elif action == "status":
            # Get tracking status
            status_emoji = "ON" if settings.tracking_enabled else "OFF"
            status_text = "ENABLED" if settings.tracking_enabled else "DISABLED"

            # Get count of opted-in users
            opted_in_count = len(self.db.get_opted_in_users())

            # Get threshold rules
            rules = self.db.get_threshold_rules()

            # Create status embed
            embed = discord.Embed(
                title="Mjolnir Status",
                color=discord.Color.blue() if settings.tracking_enabled else discord.Color.red()
            )

            embed.add_field(
                name="Tracking Status",
                value=f"**{status_text}**",
                inline=True
            )

            embed.add_field(
                name="Opted-In Users",
                value=f"**{opted_in_count}** users",
                inline=True
            )

            embed.add_field(
                name="Target Game",
                value=f"**{settings.target_game}**",
                inline=False
            )

            # Announcement channel
            channel_text = "Not configured"
            if settings.announcement_channel_id:
                channel = self.bot.get_channel(settings.announcement_channel_id)
                channel_text = channel.mention if channel else f"ID: {settings.announcement_channel_id}"
            embed.add_field(
                name="Announcement Channel",
                value=channel_text,
                inline=True,
            )

            # Rules summary grouped by window
            if rules:
                rules_by_window: dict[str, list] = {}
                for rule in rules:
                    rules_by_window.setdefault(rule.window_type, []).append(rule)

                rules_lines = []
                for window_type, window_rules in rules_by_window.items():
                    label = WINDOW_LABELS.get(window_type, window_type)
                    entries = []
                    for r in window_rules:
                        if r.action == "timeout":
                            entries.append(f"{r.hours}h = {r.duration_hours}h timeout")
                        else:
                            entries.append(f"{r.hours}h = warning")
                    rules_lines.append(f"**{label}:** {', '.join(entries)}")

                embed.add_field(
                    name="Threshold Rules",
                    value="\n".join(rules_lines),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Threshold Rules",
                    value="No rules configured.",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

    @hammer.error
    async def hammer_error(self, interaction: discord.Interaction, error):
        """Handle errors for the hammer command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "You need **Administrator** permissions to use this command.",
                ephemeral=True
            )


async def setup(bot):
    """Load the Admin cog."""
    await bot.add_cog(Admin(bot))
