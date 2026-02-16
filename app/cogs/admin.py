"""
Admin cog for Mjolnir.
Provides commands for users to opt-in/out and admins to control the bot.
"""
import discord
from datetime import datetime, timezone
from typing import Optional

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

    hammer = app_commands.Group(
        name="hammer",
        description="Control Mjolnir's tracking system",
        default_permissions=discord.Permissions(administrator=True),
    )

    rules = app_commands.Group(
        name="rules",
        description="Manage threshold rules",
        parent=hammer,
    )

    @hammer.command(name="on", description="Enable playtime tracking")
    async def hammer_on(self, interaction: discord.Interaction):
        """Enable playtime tracking."""
        settings = self.db.get_settings()

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
                ephemeral=False
            )
            print("Tracking enabled by admin")

    @hammer.command(name="off", description="Disable playtime tracking")
    async def hammer_off(self, interaction: discord.Interaction):
        """Disable playtime tracking."""
        settings = self.db.get_settings()

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
                ephemeral=False
            )
            print("Tracking disabled by admin")

    @hammer.command(name="status", description="View Mjolnir's current status and configuration")
    async def hammer_status(self, interaction: discord.Interaction):
        """Show bot status, settings, and rule summary."""
        settings = self.db.get_settings()
        status_text = "ENABLED" if settings.tracking_enabled else "DISABLED"
        opted_in_count = len(self.db.get_opted_in_users())
        rules = self.db.get_threshold_rules()

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

        channel_text = "Not configured"
        if settings.announcement_channel_id:
            channel = self.bot.get_channel(settings.announcement_channel_id)
            channel_text = channel.mention if channel else f"ID: {settings.announcement_channel_id}"
        embed.add_field(
            name="Announcement Channel",
            value=channel_text,
            inline=True,
        )

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

    # ----- /hammer setchannel -----

    @hammer.command(
        name="setchannel",
        description="Set the announcement channel for threshold alerts"
    )
    @app_commands.describe(channel="The text channel to send announcements to")
    async def hammer_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        """Set the announcement channel."""
        self.db.update_settings(announcement_channel_id=channel.id)
        await interaction.response.send_message(
            f"Announcement channel set to {channel.mention}.",
            ephemeral=True
        )
        print(f"Announcement channel set to #{channel.name} by admin")

    # ----- /hammer setgame -----

    @hammer.command(name="setgame", description="Change the target game to monitor")
    @app_commands.describe(game="The game name to track (case-insensitive matching)")
    async def hammer_setgame(self, interaction: discord.Interaction, game: str):
        """Change the target game being tracked."""
        game = game.strip()
        if not game:
            await interaction.response.send_message(
                "Game name cannot be empty.", ephemeral=True
            )
            return

        self.db.update_settings(target_game=game)
        await interaction.response.send_message(
            f"Target game updated to **{game}**.",
            ephemeral=True
        )
        print(f"Target game changed to '{game}' by admin")

    # ----- /hammer rules list -----

    @rules.command(name="list", description="View all threshold rules")
    async def rules_list(self, interaction: discord.Interaction):
        """Display every threshold rule grouped by window type."""
        all_rules = self.db.get_threshold_rules()

        if not all_rules:
            await interaction.response.send_message(
                "No threshold rules configured.\n"
                "Use `/hammer rules add` to create one.",
                ephemeral=True
            )
            return

        rules_by_window: dict[str, list] = {}
        for rule in all_rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        embed = discord.Embed(title="Threshold Rules", color=discord.Color.blue())

        for window_type in ["rolling_7d", "daily", "weekly", "session"]:
            window_rules = rules_by_window.get(window_type)
            if not window_rules:
                continue

            label = WINDOW_LABELS.get(window_type, window_type)
            lines = []
            for r in window_rules:
                if r.action == "timeout":
                    lines.append(
                        f"`#{r.id}` — **{r.hours}h** = "
                        f"**{r.duration_hours}h** timeout"
                    )
                else:
                    lines.append(f"`#{r.id}` — **{r.hours}h** = warning")
            embed.add_field(name=label, value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----- /hammer rules add -----

    @rules.command(name="add", description="Add a new threshold rule")
    @app_commands.describe(
        hours="Playtime threshold in hours",
        action="Action to take when threshold is reached",
        duration="Timeout duration in hours (required for timeout action)",
        window="Time window for this rule",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="warn", value="warn"),
            app_commands.Choice(name="timeout", value="timeout"),
        ],
        window=[
            app_commands.Choice(name="Rolling 7-Day", value="rolling_7d"),
            app_commands.Choice(name="Daily (24h)", value="daily"),
            app_commands.Choice(name="Calendar Week", value="weekly"),
            app_commands.Choice(name="Per Session", value="session"),
        ],
    )
    async def rules_add(
        self,
        interaction: discord.Interaction,
        hours: float,
        action: str,
        window: str,
        duration: Optional[int] = None,
    ):
        """Add a threshold rule after validating inputs."""
        if hours <= 0:
            await interaction.response.send_message(
                "Hours must be greater than 0.", ephemeral=True
            )
            return

        if action == "timeout" and (duration is None or duration <= 0):
            await interaction.response.send_message(
                "A timeout rule requires a positive duration (hours).",
                ephemeral=True
            )
            return

        if action == "warn":
            duration = None

        rule = self.db.add_threshold_rule(
            hours=hours,
            action=action,
            duration_hours=duration,
            window_type=window,
        )

        label = WINDOW_LABELS.get(window, window)
        if action == "timeout":
            desc = f"**{hours}h** = **{duration}h** timeout"
        else:
            desc = f"**{hours}h** = warning"

        await interaction.response.send_message(
            f"Rule `#{rule.id}` added to **{label}**:\n{desc}",
            ephemeral=True
        )
        print(f"Threshold rule #{rule.id} added by admin")

    # ----- /hammer rules remove -----

    @rules.command(name="remove", description="Remove a threshold rule by ID")
    @app_commands.describe(rule_id="The rule ID to remove (shown in rules list)")
    async def rules_remove(self, interaction: discord.Interaction, rule_id: int):
        """Delete a threshold rule."""
        deleted = self.db.delete_threshold_rule(rule_id)

        if deleted:
            await interaction.response.send_message(
                f"Rule `#{rule_id}` has been removed.",
                ephemeral=True
            )
            print(f"Threshold rule #{rule_id} removed by admin")
        else:
            await interaction.response.send_message(
                f"No rule found with ID `#{rule_id}`.",
                ephemeral=True
            )


async def setup(bot):
    """Load the Admin cog."""
    await bot.add_cog(Admin(bot))
