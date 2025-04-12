import config
import datetime
import discord
import logging

from datetime import datetime, UTC
from discord import app_commands
from interactions import (
    load_and_update_events,
    send_event_message,
    update_event_message,
    OpenEvent,
    ClosedEvent,
)
from util import (
    # Use cached loaders by default
    load_event_data,  # This now uses the cache
    save_event_data,
    load_responses,  # This now uses the cache
    save_responses,
    get_event,  # Returns Event object or None
    get_responses,  # Returns list[Response]
    add_response,  # Use if needed directly (usually not)
    remove_response,  # Use for delete_response command
    create_event_message,  # Use for creating/updating messages
    OFFKAI_MESSAGE,  # Keep if needed separately
    Event,  # Import the dataclass
    Response,  # Import the dataclass
)

_log = logging.getLogger(__name__)


class OffkaiClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        load_event_data()
        load_responses()
        _log.info("Initial data loaded into cache.")

        for guild_id in config.GUILD_IDS:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        _log.info("Commands synced.")

        await load_and_update_events(self)


intents = discord.Intents.default()
intents.message_content = True

client = OffkaiClient(intents=intents)

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
        await interaction.response.send_message(
            f"❌ An event named '{event_name}' already exists.", ephemeral=True
        )
        return

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
        await interaction.response.send_message(
            "❌ Invalid date format. Use YYYY-MM-DD HH:MM.", ephemeral=True
        )
        return

    if not interaction.guild or not isinstance(
        interaction.channel, discord.TextChannel
    ):
        await interaction.response.send_message(
            "❌ This command can only be used in a server text channel.", ephemeral=True
        )
        return

    # Create the thread
    try:
        thread = await interaction.channel.create_thread(
            name=event_name, type=discord.ChannelType.public_thread
        )
    except discord.HTTPException as e:
        _log.error(f"Failed to create thread for '{event_name}': {e}")
        await interaction.response.send_message(
            "❌ Failed to create the event thread. Check bot permissions.",
            ephemeral=True,
        )
        return

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
        await interaction.response.send_message(
            f"❌ Event '{event_name}' not found.", ephemeral=True
        )
        return
    if event.archived:
        await interaction.response.send_message(
            f"❌ Cannot modify an archived event ('{event_name}').", ephemeral=True
        )
        return

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
            await interaction.response.send_message(
                "❌ Invalid date format. Use YYYY-MM-DD HH:MM.", ephemeral=True
            )
            return
    if drinks is not None:
        # Empty string means clear drinks, otherwise parse
        event.drinks = (
            [d.strip().lower() for d in drinks.split(",") if d.strip()]
            if drinks
            else []
        )
        modified = True

    if not modified:
        await interaction.response.send_message(
            "❌ No changes provided to modify.", ephemeral=True
        )
        return

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
async def close_offkai(
    interaction: discord.Interaction, event_name: str, close_msg: str | None = None
):
    event = get_event(event_name)
    if not event:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' not found.", ephemeral=True
        )
        return
    if event.archived:
        await interaction.response.send_message(
            f"❌ Cannot close an archived event ('{event_name}').", ephemeral=True
        )
        return
    if not event.open:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' is already closed.", ephemeral=True
        )
        return

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
async def reopen_offkai(
    interaction: discord.Interaction, event_name: str, reopen_msg: str | None = None
):
    event = get_event(event_name)
    if not event:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' not found.", ephemeral=True
        )
        return
    if event.archived:
        await interaction.response.send_message(
            f"❌ Cannot reopen an archived event ('{event_name}').", ephemeral=True
        )
        return
    if event.open:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' is already open.", ephemeral=True
        )
        return

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
async def archive_offkai(interaction: discord.Interaction, event_name: str):
    event = get_event(event_name)
    if not event:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' not found.", ephemeral=True
        )
        return
    if event.archived:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' is already archived.", ephemeral=True
        )
        return

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
async def broadcast(interaction: discord.Interaction, event_name: str, message: str):
    event = get_event(event_name)
    if not event:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' not found.", ephemeral=True
        )
        return
    if not event.channel_id:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' does not have a channel ID set.", ephemeral=True
        )
        return

    channel = client.get_channel(event.channel_id)
    if not isinstance(channel, discord.Thread):
        await interaction.response.send_message(
            f"❌ Could not find thread channel for '{event_name}'.", ephemeral=True
        )
        return

    try:
        await channel.send(f"{message}")
        await interaction.response.send_message(
            f"📣 Sent broadcast to channel {channel.mention}.", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Bot lacks permission to send messages in {channel.mention}.",
            ephemeral=True,
        )
    except discord.HTTPException as e:
        _log.error(f"Failed to send broadcast to {channel.id}: {e}")
        await interaction.response.send_message(
            f"❌ Failed to send message to {channel.mention}.", ephemeral=True
        )


@client.tree.command(
    name="delete_response",
    description="Deletes a specific user's response to an offkai.",
    # guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.", member="The member whose response to remove."
)
@app_commands.checks.has_role("Offkai Organizer")
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
        await interaction.response.send_message(
            f"❌ Could not find a response from user {member.mention} for '{event_name}'.",
            ephemeral=True,
        )


@client.tree.command(
    name="attendance",
    description="Gets the list of attendees and count for an event.",
    # guilds=config.GUILDS,
)
@app_commands.describe(event_name="The name of the event.")
@app_commands.checks.has_role("Offkai Organizer")
async def attendance(interaction: discord.Interaction, event_name: str):
    event = get_event(event_name)
    if not event:
        await interaction.response.send_message(
            f"❌ Event '{event_name}' not found.", ephemeral=True
        )
        return

    responses = get_responses(event_name)  # Returns list[Response]

    if not responses:
        await interaction.response.send_message(
            f"No responses found for '{event_name}'.", ephemeral=True
        )
        return

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


@close_offkai.error
@reopen_offkai.error
@create_offkai.error
@modify_offkai.error
@archive_offkai.error
@delete_response.error
@attendance.error
@broadcast.error
async def on_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    original_error = getattr(error, "original", error)
    if isinstance(error, app_commands.MissingRole):
        # Fetch role name if possible for a friendlier message
        role_name = f"ID {config.ORGANIZER_ROLE_ID}"
        if interaction.guild:
            role = interaction.guild.get_role(config.ORGANIZER_ROLE_ID)
            if role:
                role_name = f"'{role.name}'"
        await interaction.response.send_message(
            f"❌ You need the {role_name} role to use this command.", ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.", ephemeral=True
        )
    # Add more specific error handling if needed
    elif isinstance(original_error, discord.Forbidden):
        await interaction.response.send_message(
            "❌ The bot lacks permissions to perform this action.", ephemeral=True
        )
    else:
        _log.error(f"Unhandled command error: {error}", exc_info=error)
        # Avoid sending detailed internal errors to users
        await interaction.response.send_message(
            "❌ An unexpected error occurred. Please try again later or contact an admin.",
            ephemeral=True,
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


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s"
    )
    discord_logger = logging.getLogger("discord")
    discord_logger.setLevel(logging.WARNING)  # Reduce discord lib noise

    # Validate config before running
    if not config.DISCORD_TOKEN:
        _log.critical("DISCORD_TOKEN is not set in config.py")
    elif not config.GUILD_IDS:
        _log.critical("GUILD_IDS is not set or empty in config.py")
    else:
        try:
            client.run(
                config.DISCORD_TOKEN, log_handler=None
            )  # Use basicConfig handler
        except Exception as e:
            _log.exception(f"Fatal error running bot: {e}")
