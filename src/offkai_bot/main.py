# src/offkai_bot/main.py
import argparse
import contextlib
import functools
import logging
import sys
from typing import Any

import discord
from discord import app_commands

# --- Updated Imports ---
from . import config

# Import data handling functions from the new 'data' package
from .data.event import (
    add_event,
    archive_event,
    get_event,
    load_event_data,
    save_event_data,
    set_event_open_status,
    update_event_details,
)
from .data.response import calculate_attendance, load_responses, remove_response
from .errors import (
    BotCommandError,
    BroadcastPermissionError,
    BroadcastSendError,
    DuplicateEventError,
    EventNotFoundError,
    InvalidChannelTypeError,
    MissingChannelIDError,
    ResponseNotFoundError,
    ThreadAccessError,
    ThreadCreationError,
    ThreadNotFoundError,
)
from .interactions import fetch_thread_for_event, load_and_update_events, send_event_message, update_event_message

# Import remaining general utils
from .util import parse_drinks, parse_event_datetime, validate_interaction_context

# --- End Updated Imports ---

_log = logging.getLogger(__name__)
settings: dict[str, Any] = {}


class OffkaiClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        load_event_data()
        load_responses()
        _log.info("Initial data loaded into cache.")

        for guild_id in settings["GUILDS"]:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        _log.info("Commands synced.")

        await load_and_update_events(self)


intents = discord.Intents.default()
intents.message_content = True

client = OffkaiClient(intents=intents)

# --- Logging ---


def log_command_usage(func):
    """Decorator to log command usage details, including 'event_name' if present."""

    @functools.wraps(func)  # Preserves original function metadata (name, docstring)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        command_name = interaction.command.name if interaction.command else "Unknown"
        user_info = f"{interaction.user} ({interaction.user.id})"
        guild_info = f"Guild: {interaction.guild_id}" if interaction.guild_id else "DM"
        channel_info = f"Channel: {interaction.channel_id}"

        # --- Add event_name logging ---
        event_name_arg = kwargs.get("event_name")  # Safely get 'event_name' from kwargs
        event_info = ""
        if event_name_arg is not None:
            # Ensure it's a string before logging, just in case
            event_info = f" for Event: '{str(event_name_arg)}'"
        # --- End event_name logging ---

        _log.info(
            # Append event_info to the existing log message if it was found
            f"Command triggered: '{command_name}' by {user_info} in {guild_info} {channel_info}{event_info}"
        )

        # Call the original command function
        try:
            result = await func(interaction, *args, **kwargs)
            return result
        except Exception as e:
            # Let the global error handler catch and log/report the error
            raise e

    return wrapper


# --- Commands ---


@app_commands.checks.has_role("Offkai Organizer")
@client.tree.command()
async def hello(interaction: discord.Interaction):
    """Says hello!"""
    await interaction.response.send_message(f"Hi, {interaction.user.mention}")


@client.tree.command(
    name="create_offkai",
    description="Create a new offkai in the current channel.",
)
@app_commands.describe(
    event_name="The name of the event.",
    venue="The offkai venue.",
    address="The address of the offkai venue.",
    google_maps_link="A link to the venue on Google Maps.",
    date_time="The date and time (YYYY-MM-DD HH:MM). Assumed JST.",  # Clarify timezone assumption
    drinks="Optional: Comma-separated list of allowed drinks.",
    announce_msg="Optional: A message to post in the main channel.",
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def create_offkai(
    interaction: discord.Interaction,
    event_name: str,
    venue: str,
    address: str,
    google_maps_link: str,
    date_time: str,
    drinks: str | None = None,
    announce_msg: str | None = None,
):
    # 1. Business Logic Validation
    with contextlib.suppress(EventNotFoundError):
        if get_event(event_name):
            raise DuplicateEventError(event_name)

    # 2. Input Parsing/Transformation
    event_datetime = parse_event_datetime(date_time)
    drinks_list = parse_drinks(drinks)

    # 3. Context Validation
    validate_interaction_context(interaction)

    # --- Discord Interaction Block ---
    try:
        assert isinstance(interaction.channel, discord.TextChannel)
        thread = await interaction.channel.create_thread(name=event_name, type=discord.ChannelType.public_thread)
    except discord.HTTPException as e:
        _log.error(f"Failed to create thread for '{event_name}': {e}")
        raise ThreadCreationError(event_name, e)
    except AssertionError:
        _log.error("Interaction channel was unexpectedly not a TextChannel after validation.")
        raise InvalidChannelTypeError()
    # --- End Discord Interaction Block ---

    # --- Steps 4 & 5 Replaced ---
    # Call the new function in the data layer
    new_event = add_event(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=google_maps_link,
        event_datetime=event_datetime,
        thread_id=thread.id,
        drinks_list=drinks_list,
        announce_msg=announce_msg,  # Pass announce_msg if stored on Event
    )
    # --- End Replacement ---

    # 6. Further Discord Interaction
    await send_event_message(thread, new_event)  # Handles saving after message send

    # 7. User Feedback
    announce_text = f"# Offkai Created: {event_name}\n\n"
    if announce_msg:  # Use original announce_msg for the response
        announce_text += f"{announce_msg}\n\n"
    announce_text += f"Join the discussion and RSVP here: {thread.mention}"
    await interaction.response.send_message(announce_text)


@client.tree.command(
    name="modify_offkai",
    description="Modifies an existing offkai event.",
)
@app_commands.describe(
    event_name="The name of the event to modify.",
    venue="Optional: The new venue.",
    address="Optional: The new address.",
    google_maps_link="Optional: The new Google Maps link.",
    date_time="Optional: The new date and time (YYYY-MM-DD HH:MM).",
    drinks="Optional: New comma-separated list of allowed drinks. Overwrites existing.",
    update_msg="Message to post in the event thread announcing the update.",
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def modify_offkai(
    interaction: discord.Interaction,
    event_name: str,
    update_msg: str,
    venue: str | None = None,
    address: str | None = None,
    google_maps_link: str | None = None,
    date_time: str | None = None,  # Keep as string input
    drinks: str | None = None,  # Keep as string input
):
    # 1. Call the data layer function to handle validation and modification
    #    This function will raise exceptions on failure (e.g., not found, archived, no changes)
    modified_event = update_event_details(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=google_maps_link,
        date_time_str=date_time,  # Pass the raw string
        drinks_str=drinks,  # Pass the raw string
    )

    # 2. Save the changes to disk (if modification was successful)
    save_event_data()

    # 3. Update the persistent message in the Discord thread
    await update_event_message(client, modified_event)

    # 4. Send the update announcement message (REFACTORED BLOCK)
    try:
        # Fetch the thread using the helper.
        # This handles missing ID, not found, wrong type, and access errors by raising.
        thread = await fetch_thread_for_event(client, modified_event)

        # If fetch_thread_for_event succeeded, 'thread' is a valid discord.Thread
        try:
            await thread.send(f"**Event Updated:**\n{update_msg}")
        except discord.HTTPException as e:
            # Log warning for send failure, but don't fail the command
            _log.warning(f"Could not send update message to thread {thread.id} for event '{event_name}': {e}")

    except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
        # Log specific errors related to getting the thread, but don't fail the command
        # Use the error's defined log level if available, otherwise default to WARNING
        log_level = getattr(e, "log_level", logging.WARNING)
        _log.log(log_level, f"Could not send update message for event '{event_name}': {e}")
    except Exception as e:
        # Log unexpected errors during the thread fetching/sending process
        _log.exception(f"Unexpected error sending update message for event '{event_name}': {e}")
    # --- END REFACTORED BLOCK ---

    # 5. Send confirmation response to the interaction
    await interaction.response.send_message(
        f"✅ Event '{event_name}' modified successfully. Announcement posted in thread (if possible)."
    )


@client.tree.command(
    name="close_offkai",
    description="Close responses for an offkai.",
)
@app_commands.describe(
    event_name="The name of the event.",
    close_msg="Optional: Message for the event thread.",
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def close_offkai(interaction: discord.Interaction, event_name: str, close_msg: str | None = None):
    # 1. Call data layer function for validation and modification
    closed_event = set_event_open_status(event_name, target_open_status=False)

    # 2. Save the change
    save_event_data()

    # 3. Update the message view
    await update_event_message(client, closed_event)

    # 4. Send closing message to thread (if provided and possible) (REFACTORED BLOCK)
    if close_msg:
        try:
            # Fetch the thread using the helper.
            # This handles missing ID, not found, wrong type, and access errors by raising.
            thread = await fetch_thread_for_event(client, closed_event)

            # If fetch_thread_for_event succeeded, 'thread' is a valid discord.Thread
            try:
                await thread.send(f"**Responses Closed:**\n{close_msg}")
            except discord.HTTPException as e:
                # Log warning for send failure, but don't fail the command
                _log.warning(f"Could not send closing message to thread {thread.id} for event '{event_name}': {e}")

        except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
            # Log specific errors related to getting the thread, but don't fail the command
            # Use the error's defined log level if available, otherwise default to WARNING
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"Could not send closing message for event '{event_name}': {e}")
        except Exception as e:
            # Log unexpected errors during the thread fetching/sending process
            _log.exception(f"Unexpected error sending closing message for event '{event_name}': {e}")
    # --- END REFACTORED BLOCK ---

    # 5. Send confirmation response
    await interaction.response.send_message(f"✅ Responses for '{event_name}' have been closed.")


@client.tree.command(
    name="reopen_offkai",
    description="Reopen responses for an offkai.",
    # guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.",
    reopen_msg="Optional: Message for the event thread.",
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def reopen_offkai(interaction: discord.Interaction, event_name: str, reopen_msg: str | None = None):
    # 1. Call data layer function for validation and modification
    reopened_event = set_event_open_status(event_name, target_open_status=True)

    # 2. Save the change
    save_event_data()

    # 3. Update the message view
    await update_event_message(client, reopened_event)

    # 4. Send reopening message to thread (if provided and possible) (REFACTORED BLOCK)
    if reopen_msg:
        try:
            # Fetch the thread using the helper.
            # This handles missing ID, not found, wrong type, and access errors by raising.
            thread = await fetch_thread_for_event(client, reopened_event)

            # If fetch_thread_for_event succeeded, 'thread' is a valid discord.Thread
            try:
                await thread.send(f"**Responses Reopened:**\n{reopen_msg}")
            except discord.HTTPException as e:
                # Log warning for send failure, but don't fail the command
                _log.warning(f"Could not send reopening message to thread {thread.id} for event '{event_name}': {e}")

        except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
            # Log specific errors related to getting the thread, but don't fail the command
            # Use the error's defined log level if available, otherwise default to WARNING
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"Could not send reopening message for event '{event_name}': {e}")
        except Exception as e:
            # Log unexpected errors during the thread fetching/sending process
            _log.exception(f"Unexpected error sending reopening message for event '{event_name}': {e}")
    # --- END REFACTORED BLOCK ---

    # 5. Send confirmation response
    await interaction.response.send_message(f"✅ Responses for '{event_name}' have been reopened.")


@client.tree.command(
    name="archive_offkai",
    description="Archive an offkai.",
    # guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.",
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def archive_offkai(interaction: discord.Interaction, event_name: str):
    # 1. Call data layer function for validation and modification
    archived_event = archive_event(event_name)

    # 2. Save the change
    save_event_data()

    # 3. Update the message view (always update after archiving as 'open' is set to False)
    await update_event_message(client, archived_event)

    # 4. Optionally archive the Discord thread itself (REFACTORED BLOCK)
    try:
        # Fetch the thread using the helper.
        # This handles missing ID, not found, wrong type, and access errors by raising.
        thread = await fetch_thread_for_event(client, archived_event)

        # If fetch succeeded, 'thread' is a valid discord.Thread
        if not thread.archived:  # Check if already archived before trying to edit
            try:
                await thread.edit(archived=True, locked=True)  # Archive and lock
                _log.info(f"Archived thread {thread.id} for event '{event_name}'.")
            except discord.HTTPException as e:
                # Log warning for edit failure, but don't fail the command
                _log.warning(f"Could not archive thread {thread.id}: {e}")
        # else: # Optional: Log if thread was already archived
        #     _log.info(f"Thread {thread.id} for event '{event_name}' was already archived.")

    except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
        # Log specific errors related to getting the thread, but don't fail the command
        # Use the error's defined log level if available, otherwise default to WARNING
        log_level = getattr(e, "log_level", logging.WARNING)
        _log.log(log_level, f"Could not archive thread for event '{event_name}': {e}")
    except Exception as e:
        # Log unexpected errors during the thread fetching/editing process
        _log.exception(f"Unexpected error archiving thread for event '{event_name}': {e}")
    # --- END REFACTORED BLOCK ---

    # 5. Send confirmation response
    await interaction.response.send_message(f"✅ Event '{event_name}' has been archived.")


@client.tree.command(
    name="broadcast",
    description="Sends a message to the offkai channel.",
    # guilds=config.GUILDS,
)
@app_commands.describe(event_name="The name of the event.", message="Message to broadcast.")
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def broadcast(interaction: discord.Interaction, event_name: str, message: str):
    event = get_event(event_name)

    thread = await fetch_thread_for_event(client, event)

    try:
        await thread.send(f"{message}")
        await interaction.response.send_message(f"📣 Sent broadcast to channel {thread.mention}.", ephemeral=True)
    except discord.Forbidden as e:
        raise BroadcastPermissionError(thread, e)
    except discord.HTTPException as e:
        raise BroadcastSendError(thread, e)


@client.tree.command(
    name="delete_response",
    description="Deletes a specific user's response to an offkai.",
    # guilds=config.GUILDS,
)
@app_commands.describe(event_name="The name of the event.", member="The member whose response to remove.")
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def delete_response(interaction: discord.Interaction, event_name: str, member: discord.Member):
    # 1. Check if the event exists first (get_event raises EventNotFoundError if not found)
    event = get_event(event_name)

    # 2. Attempt to remove the response using the data layer function
    #    This will now raise ResponseNotFoundError if the response doesn't exist.
    #    No try...except needed here, let the global handler catch ResponseNotFoundError.
    remove_response(event_name, member.id)

    # --- Success Path (only runs if remove_response didn't raise error) ---
    await interaction.response.send_message(
        f"🚮 Deleted response from user {member.mention} for '{event_name}'.",
        ephemeral=True,
    )

    # Try removing user from thread (event object is already available)
    if event.channel_id:
        thread = client.get_channel(event.channel_id)
        if isinstance(thread, discord.Thread):
            try:
                await thread.remove_user(member)
                _log.info(f"Removed user {member.id} from thread {thread.id} for event '{event_name}'.")
            except discord.HTTPException as e:
                # Log error but don't fail the command for this optional step
                _log.error(f"Failed to remove user {member.id} from thread {thread.id}: {e}")
        else:
            _log.warning(f"Could not find thread {event.channel_id} to remove user for event '{event_name}'.")
    else:
        _log.warning(f"Event '{event_name}' is missing channel_id, cannot remove user from thread.")
    # --- End Success Path ---


@client.tree.command(
    name="attendance",
    description="Gets the list of attendees and count for an event.",
    # guilds=config.GUILDS,
)
@app_commands.describe(event_name="The name of the event.")
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def attendance(interaction: discord.Interaction, event_name: str):
    # 1. Check if event exists
    get_event(event_name)

    # 2. Calculate attendance using the data layer function
    total_count, attendee_list = calculate_attendance(event_name)

    # 3. Format output string for Discord
    output = f"**Attendance for {event_name}**\n\n"
    output += f"Total Attendees: **{total_count}**\n\n"
    # Add numbering to the list provided by the data layer
    output += "\n".join(f"{i + 1}. {name}" for i, name in enumerate(attendee_list))

    # 4. Handle potential message length limits
    if len(output) > 1900:  # Leave buffer for ephemeral message header
        output = output[:1900] + "\n... (list truncated)"

    # 5. Send response
    await interaction.response.send_message(output, ephemeral=True)


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
            # Keep specific logging here as it's not a BotCommandError
            _log.warning(f"{user_info} - Missing Offkai Organizer role for command '{command_name}'.")
            await interaction.response.send_message(message, ephemeral=True)
            return  # Handled

        case app_commands.CheckFailure():
            message = "❌ You do not have permission to use this command."
            # Keep specific logging here
            _log.warning(f"{user_info} - CheckFailure for command '{command_name}'.")
            await interaction.response.send_message(message, ephemeral=True)
            return  # Handled

    # For other errors, work with the 'original' error if it exists
    original_error = getattr(error, "original", error)
    message = ""

    # Now, match against the original error type
    match original_error:
        # --- Unified Case for ALL handled custom errors ---
        case BotCommandError() as e:
            message = str(e)
            # Use the log level defined in the error class
            log_level = getattr(e, "log_level", logging.INFO)  # Get level, default INFO if missing
            _log.log(log_level, f"{user_info} - Handled ({type(e).__name__}): {message}")

        # --- Specific Discord Errors (Keep separate) ---
        case discord.Forbidden():
            message = "❌ The bot lacks permissions to perform this action."
            # Keep specific logging here
            _log.warning(f"{user_info} - Encountered discord.Forbidden for command '{command_name}'.")

        # --- Default Case for Unhandled Errors (Keep separate) ---
        case _:
            # Keep specific logging here
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


# --- Autocomplete Functions ---
async def event_autocomplete_base(
    interaction: discord.Interaction, current: str, *, open_status: bool | None = None
) -> list[app_commands.Choice[str]]:
    """Base autocomplete function filtering by name and optionally open status."""
    events = load_event_data()  # Use cached loader
    choices = []
    for event in events:
        if event.archived:  # Always exclude archived
            continue
        # Filter by open status if specified
        if open_status is not None and event.open != open_status:
            continue
        # Filter by current input
        if current.lower() in event.event_name.lower():
            choices.append(app_commands.Choice(name=event.event_name, value=event.event_name))
    # Limit choices to Discord's max (25)
    return choices[:25]


@modify_offkai.autocomplete("event_name")
@close_offkai.autocomplete("event_name")
@broadcast.autocomplete("event_name")
@delete_response.autocomplete("event_name")
@attendance.autocomplete("event_name")
async def offkai_autocomplete_active(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for active (non-archived) events."""
    return await event_autocomplete_base(interaction, current, open_status=None)


@reopen_offkai.autocomplete("event_name")
async def offkai_autocomplete_closed_only(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for closed, non-archived events."""
    return await event_autocomplete_base(interaction, current, open_status=False)


@archive_offkai.autocomplete("event_name")
async def offkai_autocomplete_all_non_archived(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete specifically for archive command (any non-archived event)."""
    # Same logic as active for now, but separate for clarity if needed later
    return await event_autocomplete_base(interaction, current, open_status=None)


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
    try:
        # Explicitly load the configuration ONCE at startup
        config.load_config(args.config_path)
    except config.ConfigError as e:
        print(f"Fatal Error: Failed to load configuration - {e}", file=sys.stderr)
        sys.exit(1)

    # Now access the config via the accessor function
    settings = config.get_config()

    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s")
    discord_logger = logging.getLogger("discord")
    discord_logger.setLevel(logging.WARNING)  # Reduce discord lib noise

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
