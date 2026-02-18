"""
Main bot initialization for Mjolnir.
Handles bot setup, cog loading, and startup.
"""
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from app.core.logging import setup_logging
from app.core.store import Database

logger = logging.getLogger(__name__)


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
        await self.load_extension("app.cogs.admin")
        await self.load_extension("app.cogs.watcher")

        await self.tree.sync()
        logger.info("Slash commands synced")

    async def on_ready(self):
        """Called when the bot is ready and connected to Discord."""
        logger.info("Mjolnir is ready")
        logger.info("Logged in as: %s (%d)", self.user.name, self.user.id)
        logger.info("Connected to %d server(s)", len(self.guilds))

        settings = self.db.get_settings()
        status = "ENABLED" if settings.tracking_enabled else "DISABLED"
        logger.info(
            "Tracking: %s | Target game: %s | Weekly threshold: %sh",
            status, settings.target_game, settings.weekly_threshold_hours,
        )

    async def close(self):
        """Cleanup when bot shuts down."""
        logger.info("Shutting down Mjolnir")
        self.db.close()
        await super().close()


def main():
    """Entry point for the bot."""
    load_dotenv()
    setup_logging()

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.critical(
            "DISCORD_BOT_TOKEN not found in environment variables — "
            "create a .env file with your bot token"
        )
        sys.exit(1)

    bot = Mjolnir()

    try:
        # log_handler=None prevents discord.py from adding its own handler
        bot.run(token, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        raise


if __name__ == "__main__":
    main()
