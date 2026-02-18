"""
Logging configuration for Mjolnir.
"""
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Configure application-wide logging for Mjolnir.

    Sets a consistent format on the root 'app' logger and quiets
    discord.py's own verbose loggers down to WARNING so they don't
    drown out bot output.
    """
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not app_logger.handlers:
        app_logger.addHandler(handler)

    # discord.py is chatty at DEBUG/INFO; keep it at WARNING unless debugging
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
