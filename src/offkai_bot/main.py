import argparse
import logging
import sys
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

# --- Updated Imports ---
from offkai_bot import config
from offkai_bot.alerts.alerts import alert_loop

# Import only necessary data loaders for initial cache population
from offkai_bot.data.event import load_event_data
from offkai_bot.data.ranking import load_rankings
from offkai_bot.data.response import load_responses
from offkai_bot.errors import (
    BotCommandError,
    PinPermissionError,  # Import the error for handling
)
from offkai_bot.event_actions import (
    load_and_update_events,
)

# --- End Updated Imports ---

_log = logging.getLogger(__name__)
settings: dict[str, Any] = {}


class OffkaiClient(commands.Bot):
    def __init__(self, *, intents: discord.Intents):
        # Initialize commands.Bot. Command prefix is required but we only use slash commands.
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # Load extensions (Cogs)
        try:
            await self.load_extension("offkai_bot.cogs.general")
            await self.load_extension("offkai_bot.cogs.events")
            _log.info("Extensions loaded.")
        except Exception as e:
            _log.exception(f"Failed to load extensions: {e}")
            raise e

        # Load Data
        load_event_data()
        load_responses()  # Loads both attendees and waitlist
        load_rankings()
        _log.info("Initial data loaded into cache.")

        # Sync commands
        for guild_id in settings["GUILDS"]:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        _log.info("Commands synced.")

        await load_and_update_events(self)
        alert_loop.start()


intents = discord.Intents.default()
intents.message_content = True

client = OffkaiClient(intents=intents)


# --- Error Handler ---


@client.tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handles application command errors globally."""
    user_info = f"User: {interaction.user} ({interaction.user.id})"
    command_name = interaction.command.name if interaction.command else "Unknown"

    # First, handle discord.py's specific check failures directly from 'error'
    match error:
        case app_commands.MissingRole():
            message = "❌ You need the Offkai Organizer role to use this command."
            _log.warning(f"{user_info} - Missing Offkai Organizer role for command '{command_name}'.")
            await interaction.response.send_message(message, ephemeral=True)
            return  # Handled

        case app_commands.CheckFailure():
            message = "❌ You do not have permission to use this command."
            _log.warning(f"{user_info} - CheckFailure for command '{command_name}'.")
            await interaction.response.send_message(message, ephemeral=True)
            return  # Handled

    # For other errors, work with the 'original' error if it exists
    original_error = getattr(error, "original", error)
    message = ""

    # Now, match against the original error type
    match original_error:
        # --- Handle PinPermissionError gracefully ---
        # This error is not critical; the command succeeded but the pin failed.
        # We send a followup instead of the standard error message.
        case PinPermissionError() as e:
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"{user_info} - Handled ({type(e).__name__}): {e}")
            # The initial response was already sent by the command, so we use a followup
            await interaction.followup.send(str(e), ephemeral=True)
            return  # Handled

        # --- Unified Case for other custom errors ---
        case BotCommandError() as e:
            message = str(e)
            log_level = getattr(e, "log_level", logging.INFO)
            _log.log(log_level, f"{user_info} - Handled ({type(e).__name__}): {message}")

        # --- Specific Discord Errors (Keep separate) ---
        case discord.Forbidden():
            message = "❌ The bot lacks permissions to perform this action."
            _log.warning(f"{user_info} - Encountered discord.Forbidden for command '{command_name}'.")

        # --- Default Case for Unhandled Errors (Keep separate) ---
        case _:
            _log.error(
                f"{user_info} - Unhandled command error for '{command_name}': {error}",
                exc_info=original_error,
            )
            message = "❌ An unexpected error occurred. Please try again later or contact an admin."

    # Send the response (if a message was set)
    if message:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
        except discord.HTTPException as http_err:
            _log.error(f"{user_info} - Failed to send error response message: {http_err}")
        except Exception as e:
            _log.error(
                f"{user_info} - Exception sending error response message: {e}",
                exc_info=e,
            )


# Event to run when the client is ready
@client.event
async def on_ready():
    _log.info(f"Logged in as {client.user}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offkai Bot")
    parser.add_argument("--config-path", type=str, default="config.py")
    return parser.parse_args()


def main() -> None:
    global settings
    args = parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s")
    discord_logger = logging.getLogger("discord")
    discord_logger.setLevel(logging.WARNING)  # Reduce discord lib noise

    try:
        # Explicitly load the configuration ONCE at startup
        config.load_config(args.config_path)
    except config.ConfigError as e:
        _log.critical(f"Fatal Error: Failed to load configuration - {e}")
        sys.exit(1)

    # Now access the config via the accessor function
    settings = config.get_config()

    # Validate config before running
    if not settings["DISCORD_TOKEN"]:
        _log.critical("DISCORD_TOKEN is not set")
    elif not settings["GUILDS"]:
        _log.critical("GUILDS is not set")
    else:
        try:
            client.run(settings["DISCORD_TOKEN"], log_handler=None)  # Use basicConfig handler
        except Exception as e:
            _log.exception(f"Fatal error running bot: {e}")
