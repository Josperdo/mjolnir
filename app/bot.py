"""
Main bot initialization for Mjolnir.
Handles bot setup, cog loading, and startup.
"""
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from app.core.store import Database


class Mjolnir(commands.Bot):
    """Custom bot class for Mjolnir."""

    def __init__(self):
        """Initialize the Mjolnir bot."""
        # Define intents - we need presence updates and members
        intents = discord.Intents.default()
        intents.presences = True  # Required to track what users are playing
        intents.members = True    # Required to access member information
        intents.message_content = True  # For prefix commands if needed

        super().__init__(
            command_prefix="!",  # Fallback prefix (mainly using slash commands)
            intents=intents,
            help_command=None  # Disable default help command
        )

        # Initialize database
        db_path = os.getenv("DATABASE_PATH", "mjolnir.db")
        self.db = Database(db_path)

    async def setup_hook(self):
        """Called when the bot is starting up. Load cogs here."""
        # Load cogs
        await self.load_extension("app.cogs.admin")
        await self.load_extension("app.cogs.watcher")

        # Sync slash commands with Discord
        await self.tree.sync()
        print("✅ Slash commands synced")

    async def on_ready(self):
        """Called when the bot is ready and connected to Discord."""
        print(f"🔨 Mjolnir is ready!")
        print(f"   Logged in as: {self.user.name} ({self.user.id})")
        print(f"   Connected to {len(self.guilds)} server(s)")

        # Get settings to display status
        settings = self.db.get_settings()
        status = "ENABLED" if settings.tracking_enabled else "DISABLED"
        print(f"   Tracking: {status}")
        print(f"   Target game: {settings.target_game}")
        print(f"   Weekly threshold: {settings.weekly_threshold_hours}h")

    async def close(self):
        """Cleanup when bot shuts down."""
        print("🛑 Shutting down Mjolnir...")
        self.db.close()
        await super().close()


def main():
    """Entry point for the bot."""
    # Load environment variables
    load_dotenv()

    # Check for required token
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Error: DISCORD_BOT_TOKEN not found in environment variables")
        print("   Please create a .env file with your bot token")
        sys.exit(1)

    # Create and run bot
    bot = Mjolnir()

    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\n⚠️  Received shutdown signal")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
