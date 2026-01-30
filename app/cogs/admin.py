"""
Admin cog for Mjolnir.
Provides commands for users to opt-in/out and admins to control the bot.
"""
import discord
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
