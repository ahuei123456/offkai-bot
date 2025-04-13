import config
import datetime
import discord
import functools
import argparse
import logging
import sys

from datetime import datetime
from typing import Any # Or use a dict, or define a simple class

import discord
from discord import app_commands
from errors import *
from .interactions import (
    load_and_update_events,
    send_event_message,
    update_event_message,
)
from .util import (
    # Use cached loaders by default
    load_event_data,  # This now uses the cache
    save_event_data,
    load_responses,  # This now uses the cache
    get_event,  # Returns Event object or None
    get_responses,  # Returns list[Response]
    remove_response,  # Use for delete_response command
    Event,  # Import the dataclass
)

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
    drinks: str | None = None,  # Make optional
    announce_msg: str | None = None,
):
    # Check for duplicate event name
    if get_event(event_name):
        raise DuplicateEventError(event_name)

    try:
        # TODO: Handle timezone properly. Assuming JST for now.
        # Consider using discord's timestamp format or requiring timezone.
        event_dt_naive = datetime.strptime(date_time, r"%Y-%m-%d %H:%M")
        # If assuming JST (UTC+9), create an aware datetime object
        # This requires `pytz` or Python 3.9+ `zoneinfo`
        # from zoneinfo import ZoneInfo # Python 3.9+
        # jst = ZoneInfo("Asia/Tokyo")
        # event_datetime = event_dt_naive.replace(tzinfo=jst)
        # For simplicity without external libs/newer Python, store naive or UTC
        event_datetime = event_dt_naive  # Store naive time, display assumes JST
    except ValueError:
        raise InvalidDateTimeFormat()

    if not interaction.guild or not isinstance(
        interaction.channel, discord.TextChannel
    ):
        raise InvalidChannelTypeError()

    # Create the thread
    try:
        thread = await interaction.channel.create_thread(
            name=event_name, type=discord.ChannelType.public_thread
        )
    except discord.HTTPException as e:
        _log.error(f"Failed to create thread for '{event_name}': {e}")
        raise ThreadCreationError(event_name, e)

    # Prepare drinks list
    drinks_list = []
    if drinks:
        drinks_list = [d.strip() for d in drinks.split(",") if d.strip()]

    # Create Event object
    new_event = Event(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=google_maps_link,
        event_datetime=event_datetime,
        channel_id=thread.id,
        message_id=None,  # Will be set by send_event_message
        open=True,
        archived=False,
        drinks=drinks_list,
        message=None,  # message field in Event is less useful now, format_details is key
    )

    # Add to cache and save
    events = load_event_data()  # Load cached
    events.append(new_event)
    # Note: message_id is not set yet. send_event_message will handle saving after sending.

    # Send initial message (this will also save the event list with the message ID)
    await send_event_message(thread, new_event)  # Pass the list to save

    # Send confirmation/announcement in original channel
    announce_text = f"# Offkai Created: {event_name}\n\n"
    if announce_msg:
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
    date_time: str | None = None,
    drinks: str | None = None,
):
    event = get_event(event_name)
    if not event:
        raise EventNotFound(event_name)
    if event.archived:
        raise EventArchivedError(event_name, "modify")

    # Update fields if provided
    modified = False
    if venue is not None:
        event.venue = venue
        modified = True
    if address is not None:
        event.address = address
        modified = True
    if google_maps_link is not None:
        event.google_maps_link = google_maps_link
        modified = True
    if date_time is not None:
        try:
            # Apply same timezone logic as create_offkai if needed
            event_dt_naive = datetime.strptime(date_time, r"%Y-%m-%d %H:%M")
            event.event_datetime = event_dt_naive  # Store naive
            modified = True
        except ValueError:
            raise InvalidDateTimeFormat()
    if drinks is not None:
        # Empty string means clear drinks, otherwise parse
        event.drinks = (
            [d.strip().lower() for d in drinks.split(",") if d.strip()]
            if drinks
            else []
        )
        modified = True

    if not modified:
        raise NoChangesProvidedError()

    # Save the modified event data
    save_event_data()  # Just save the current cache state

    # Update the message in the thread
    await update_event_message(client, event)  # Pass list for potential resend

    # Send update announcement to thread
    if event.channel_id:
        thread = client.get_channel(event.channel_id)
        if isinstance(thread, discord.Thread):
            try:
                await thread.send(f"**Event Updated:**\n{update_msg}")
            except discord.HTTPException as e:
                _log.warning(
                    f"Could not send update message to thread {thread.id}: {e}"
                )
        else:
            _log.warning(
                f"Could not find thread {event.channel_id} to send update message."
            )

    await interaction.response.send_message(
        f"✅ Event '{event_name}' modified successfully. Announcement posted in thread."
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
async def close_offkai(
    interaction: discord.Interaction, event_name: str, close_msg: str | None = None
):
    event = get_event(event_name)
    if not event:
        raise EventNotFound(event_name)
    if event.archived:
        raise EventArchivedError(event_name, "close")
    if not event.open:
        raise EventAlreadyClosed(event_name)

    event.open = False
    save_event_data()  # Save the change

    # Update the message view
    await update_event_message(client, event)

    # Send closing message to thread
    if close_msg and event.channel_id:
        thread = client.get_channel(event.channel_id)
        if isinstance(thread, discord.Thread):
            try:
                await thread.send(f"**Responses Closed:**\n{close_msg}")
            except discord.HTTPException as e:
                _log.warning(
                    f"Could not send closing message to thread {thread.id}: {e}"
                )

    await interaction.response.send_message(
        f"✅ Responses for '{event_name}' have been closed."
    )


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
async def reopen_offkai(
    interaction: discord.Interaction, event_name: str, reopen_msg: str | None = None
):
    event = get_event(event_name)
    if not event:
        raise EventNotFound(event_name)
    if event.archived:
        raise EventArchivedError(event_name, "reopen")
    if event.open:
        raise EventAlreadyOpen(event_name)

    event.open = True
    save_event_data()  # Save the change

    # Update the message view
    await update_event_message(client, event)

    # Send reopening message to thread
    if reopen_msg and event.channel_id:
        thread = client.get_channel(event.channel_id)
        if isinstance(thread, discord.Thread):
            try:
                await thread.send(f"**Responses Reopened:**\n{reopen_msg}")
            except discord.HTTPException as e:
                _log.warning(
                    f"Could not send reopening message to thread {thread.id}: {e}"
                )

    await interaction.response.send_message(
        f"✅ Responses for '{event_name}' have been reopened."
    )


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
    event = get_event(event_name)
    if not event:
        raise EventNotFound(event_name)
    if event.archived:
        raise EventAlreadyArchived(event_name)

    event.archived = True
    # Optionally close the event if archiving
    if event.open:
        event.open = False
        # Update message one last time if it was open
        await update_event_message(client, event)

    save_event_data()  # Save the change

    # Optionally archive the thread itself
    if event.channel_id:
        thread = client.get_channel(event.channel_id)
        if isinstance(thread, discord.Thread) and not thread.archived:
            try:
                await thread.edit(archived=True, locked=True)  # Archive and lock
                _log.info(f"Archived thread {thread.id} for event '{event_name}'.")
            except discord.HTTPException as e:
                _log.warning(f"Could not archive thread {thread.id}: {e}")

    await interaction.response.send_message(
        f"✅ Event '{event_name}' has been archived."
    )


@client.tree.command(
    name="broadcast",
    description="Sends a message to the offkai channel.",
    # guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.", message="Message to broadcast."
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def broadcast(interaction: discord.Interaction, event_name: str, message: str):
    event = get_event(event_name)
    if not event:
        raise EventNotFound()
    if not event.channel_id:
        raise MissingChannelIDError(event_name)

    channel = client.get_channel(event.channel_id)
    if not isinstance(channel, discord.Thread):
        raise ThreadNotFoundError(event_name, event.channel_id)

    try:
        await channel.send(f"{message}")
        await interaction.response.send_message(
            f"📣 Sent broadcast to channel {channel.mention}.", ephemeral=True
        )
    except discord.Forbidden as e:
        raise BroadcastPermissionError(channel, e)
    except discord.HTTPException as e:
        raise BroadcastSendError(channel, e)


@client.tree.command(
    name="delete_response",
    description="Deletes a specific user's response to an offkai.",
    # guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.", member="The member whose response to remove."
)
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def delete_response(
    interaction: discord.Interaction, event_name: str, member: discord.Member
):
    # Use the util function
    removed = remove_response(event_name, member.id)

    if removed:
        await interaction.response.send_message(
            f"🚮 Deleted response from user {member.mention} for '{event_name}'.",
            ephemeral=True,
        )
        # Try removing user from thread
        event = get_event(event_name)
        if event and event.channel_id:
            thread = client.get_channel(event.channel_id)
            if isinstance(thread, discord.Thread):
                try:
                    await thread.remove_user(member)
                except discord.HTTPException:
                    pass  # Ignore if user wasn't in thread or other issue
    else:
        raise ResponseNotFound(event_name, member.mention)


@client.tree.command(
    name="attendance",
    description="Gets the list of attendees and count for an event.",
    # guilds=config.GUILDS,
)
@app_commands.describe(event_name="The name of the event.")
@app_commands.checks.has_role("Offkai Organizer")
@log_command_usage
async def attendance(interaction: discord.Interaction, event_name: str):
    event = get_event(event_name)
    if not event:
        raise EventNotFound(event_name)

    responses = get_responses(event_name)  # Returns list[Response]

    if not responses:
        raise NoResponsesFound(event_name)

    attendee_list = []
    total_count = 0
    for response in responses:
        # Add the main person
        attendee_list.append(f"{response.username}")
        total_count += 1
        # Add extra people
        for i in range(response.extra_people):
            attendee_list.append(f"{response.username} +{i+1}")
            total_count += 1

    # Format output
    output = f"**Attendance for {event_name}**\n\n"
    output += f"Total Attendees: **{total_count}**\n\n"
    output += "\n".join(f"{i+1}. {name}" for i, name in enumerate(attendee_list))

    # Handle potential message length limits for Discord
    if len(output) > 1900:  # Leave buffer for ephemeral message header
        output = output[:1900] + "\n... (list truncated)"

    await interaction.response.send_message(output, ephemeral=True)


# --- Error Handler ---


@client.tree.error
async def on_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    """Handles application command errors globally."""
    user_info = f"User: {interaction.user} ({interaction.user.id})"
    command_name = interaction.command.name if interaction.command else "Unknown"

    # First, handle discord.py's specific check failures directly from 'error'
    match error:
        case app_commands.MissingRole():
            message = f"❌ You need the Offkai Organizer role to use this command."
            _log.warning(
                f"{user_info} - Missing Offkai Organizer role for command '{command_name}'."
            )
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
    log_handled_error = True  # Flag to control logging for handled cases

    # Now, match against the original error type
    # Specific cases needing special handling (e.g., WARNING log) FIRST
    match original_error:
        # --- Cases needing WARNING level logging ---
        case (
            MissingChannelIDError()
            | ThreadNotFoundError()
            | ThreadCreationError()  # Already logged error when raised, but log context here
            | BroadcastPermissionError()
            | BroadcastSendError()  # Already logged error when raised, but log context here
            | InvalidChannelTypeError()
        ) as e:  # Added InvalidChannelTypeError here as potential setup issue
            message = str(e)
            _log.warning(
                f"{user_info} - Handled Warning ({type(e).__name__}): {message}"
            )

        # --- General Case for most handled custom errors (INFO level) ---
        case BotCommandError() as e:  # Catches any OTHER BotCommandError subclass
            message = str(e)
            _log.info(f"{user_info} - Handled Info ({type(e).__name__}): {message}")

        # --- Specific Discord Errors ---
        case discord.Forbidden():
            message = "❌ The bot lacks permissions to perform this action."
            _log.warning(
                f"{user_info} - Encountered discord.Forbidden for command '{command_name}'."
            )

        # --- Default Case for Unhandled Errors ---
        case _:
            log_handled_error = False  # Don't log again below, already logged here
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
            _log.error(
                f"{user_info} - Failed to send error response message: {http_err}"
            )
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
            choices.append(
                app_commands.Choice(name=event.event_name, value=event.event_name)
            )
    # Limit choices to Discord's max (25)
    return choices[:25]


@modify_offkai.autocomplete("event_name")
@close_offkai.autocomplete("event_name")
@broadcast.autocomplete("event_name")
@delete_response.autocomplete("event_name")
@attendance.autocomplete("event_name")
async def offkai_autocomplete_active(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
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
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s"
    )
    discord_logger = logging.getLogger("discord")
    discord_logger.setLevel(logging.WARNING)  # Reduce discord lib noise

    # Validate config before running
    if not settings["DISCORD_TOKEN"]:
        _log.critical("DISCORD_TOKEN is not set")
    elif not settings["GUILDS"]:
        _log.critical("GUILDS is not set")
    else:
        try:
            client.run(
                settings["DISCORD_TOKEN"], log_handler=None
            )  # Use basicConfig handler
        except Exception as e:
            _log.exception(f"Fatal error running bot: {e}")
