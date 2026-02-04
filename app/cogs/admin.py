"""
Admin cog for Mjolnir.
Provides commands for users to opt-in/out and admins to control the bot.
"""
import discord
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands


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

        await interaction.response.send_message(
            f"✅ You've opted in to playtime tracking!\n\n"
            f"**Target game:** {settings.target_game}\n"
            f"**Weekly limit:** {settings.weekly_threshold_hours} hours\n"
            f"**Timeout duration:** {settings.timeout_duration_hours} hours\n\n"
            f"⚠️ If you exceed the weekly limit, you'll be timed out automatically.\n"
            f"Use `/opt-out` to stop tracking at any time.",
            ephemeral=True
        )

        print(f"✅ {interaction.user.name} opted in to tracking")

    @app_commands.command(name="opt-out", description="Opt out of playtime tracking")
    async def opt_out(self, interaction: discord.Interaction):
        """Allow user to opt out of tracking."""
        # Set user as opted out
        self.db.set_user_opt_in(interaction.user.id, False)

        await interaction.response.send_message(
            "👋 You've opted out of playtime tracking.\n\n"
            "Your previous play sessions are still saved, but we won't track new sessions.\n"
            "Use `/opt-in` if you change your mind!",
            ephemeral=True
        )

        print(f"👋 {interaction.user.name} opted out of tracking")

    @app_commands.command(name="mystats", description="View your weekly playtime stats")
    async def mystats(self, interaction: discord.Interaction):
        """Show the invoking user their current weekly playtime and remaining headroom."""
        user = self.db.get_user(interaction.user.id)
        if user is None or not user.opted_in:
            await interaction.response.send_message(
                "You're not currently opted in to playtime tracking.\n"
                "Use `/opt-in` to start!",
                ephemeral=True
            )
            return

        settings = self.db.get_settings()
        threshold = settings.weekly_threshold_hours

        # Completed sessions only — active sessions have no end_time yet
        weekly_hours = self.db.get_weekly_playtime(interaction.user.id)

        # If there's a live session, add its elapsed time on top
        active_session = self.db.get_active_session(interaction.user.id, settings.target_game)
        if active_session:
            elapsed = (datetime.now(timezone.utc) - active_session.start_time).total_seconds()
            weekly_hours += elapsed / 3600

        # Progress bar: 20 chars of █/░, capped at full
        bar_length = 20
        filled = min(int((weekly_hours / threshold) * bar_length), bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        # Color shifts as the user approaches the threshold
        if weekly_hours >= threshold:
            color = discord.Color.red()
        elif weekly_hours >= threshold * 0.75 and weekly_hours < threshold:
            color = discord.Color.orange()
        elif weekly_hours >= threshold * 0.5 and weekly_hours < threshold * 0.75:
            color = discord.Color.gold()
        else:
            color = discord.Color.green()

        remaining = max(threshold - weekly_hours, 0.0)

        embed = discord.Embed(title="📊 Your Weekly Playtime", color=color)

        embed.add_field(
            name=settings.target_game,
            value=f"{bar}\n**{weekly_hours:.1f}** / **{threshold}** hours",
            inline=False
        )

        embed.add_field(
            name="Remaining",
            value=f"**{remaining:.1f} hrs** before timeout" if remaining > 0 else "⚠️ Threshold exceeded",
            inline=True
        )

        if active_session:
            session_hours = (datetime.now(timezone.utc) - active_session.start_time).total_seconds() / 3600
            embed.add_field(
                name="🎮 Active Session",
                value=f"**{session_hours:.1f} hrs** this session",
                inline=True
            )

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
                    "ℹ️ Tracking is already enabled.",
                    ephemeral=True
                )
            else:
                self.db.update_settings(tracking_enabled=True)
                await interaction.response.send_message(
                    "🔨 **Mjolnir activated!**\n\n"
                    "Playtime tracking is now **enabled**.\n"
                    f"Monitoring: **{settings.target_game}**",
                    ephemeral=False  # Public announcement
                )
                print("🔨 Tracking enabled by admin")

        elif action == "off":
            if not settings.tracking_enabled:
                await interaction.response.send_message(
                    "ℹ️ Tracking is already disabled.",
                    ephemeral=True
                )
            else:
                self.db.update_settings(tracking_enabled=False)
                await interaction.response.send_message(
                    "🛑 **Mjolnir deactivated.**\n\n"
                    "Playtime tracking is now **disabled**.\n"
                    "Active sessions will not be tracked.",
                    ephemeral=False  # Public announcement
                )
                print("🛑 Tracking disabled by admin")

        elif action == "status":
            # Get tracking status
            status_emoji = "✅" if settings.tracking_enabled else "❌"
            status_text = "ENABLED" if settings.tracking_enabled else "DISABLED"

            # Get count of opted-in users
            opted_in_count = len(self.db.get_opted_in_users())

            # Create status embed
            embed = discord.Embed(
                title="🔨 Mjolnir Status",
                color=discord.Color.blue() if settings.tracking_enabled else discord.Color.red()
            )

            embed.add_field(
                name="Tracking Status",
                value=f"{status_emoji} **{status_text}**",
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

            embed.add_field(
                name="Weekly Threshold",
                value=f"**{settings.weekly_threshold_hours}** hours",
                inline=True
            )

            embed.add_field(
                name="Timeout Duration",
                value=f"**{settings.timeout_duration_hours}** hours",
                inline=True
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

    @hammer.error
    async def hammer_error(self, interaction: discord.Interaction, error):
        """Handle errors for the hammer command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need **Administrator** permissions to use this command.",
                ephemeral=True
            )


async def setup(bot):
    """Load the Admin cog."""
    await bot.add_cog(Admin(bot))
