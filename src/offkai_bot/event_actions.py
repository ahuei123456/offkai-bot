# src/offkai_bot/event_actions.py
import contextlib
import logging
from datetime import timedelta

import discord

from offkai_bot.alerts.task import CloseOffkaiTask, SendMessageTask

from .data.event import Event, create_event_message, load_event_data, save_event_data, set_event_open_status
from .errors import AlertTimeInPastError, BotCommandError, MissingChannelIDError, ThreadAccessError, ThreadNotFoundError
from .interactions import ClosedEvent, OpenEvent

_log = logging.getLogger(__name__)


async def perform_close_event(client: discord.Client, event_name: str, close_msg: str | None = None) -> Event:
    """
    Performs the core logic for closing an event.

    Args:
        client: The discord client instance.
        event_name: The name of the event to close.
        close_msg: An optional message to send to the event thread.

    Returns:
        The updated Event object.

    Raises:
        EventNotFoundError: If the event doesn't exist.
        # Other potential errors from underlying functions
    """
    _log.info(f"Attempting to close event '{event_name}'...")

    # 1. Update status in data store (raises EventNotFoundError if not found)
    closed_event = set_event_open_status(event_name, target_open_status=False)

    # 2. Save the change
    save_event_data()
    _log.info(f"Event '{event_name}' status set to closed and data saved.")

    # 3. Update the message view
    await update_event_message(client, closed_event)
    _log.info(f"Updated persistent message for event '{event_name}'.")

    # 4. Send closing message to thread (if provided and possible)
    if close_msg:
        try:
            # Fetch the thread using the helper.
            thread = await fetch_thread_for_event(client, closed_event)
            try:
                await thread.send(f"**Responses Closed:**\n{close_msg}")
                _log.info(f"Sent closing message to thread {thread.id} for event '{event_name}'.")
            except discord.HTTPException as e:
                _log.warning(f"Could not send closing message to thread {thread.id} for event '{event_name}': {e}")

        except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"Could not send closing message for event '{event_name}': {e}")
        except Exception as e:
            _log.exception(f"Unexpected error sending closing message for event '{event_name}': {e}")
    else:
        _log.info(f"No closing message provided for event '{event_name}'.")

    return closed_event  # Return the updated event object


# --- Event Message Handling ---


async def send_event_message(channel: discord.Thread, event: Event):
    """Sends a new event message and saves the message ID."""
    if not isinstance(event, Event):
        _log.error(f"send_event_message received non-Event object: {type(event)}")
        return

    view = OpenEvent(event) if event.open else ClosedEvent(event)
    try:
        message_content = create_event_message(event)  # Use util function
        message = await channel.send(message_content, view=view)
        await message.pin(reason=None)  # pin the message for easier access when the thread gets longer
        event.message_id = message.id  # Update the Event object directly
        save_event_data()  # Save the list containing the updated event
        _log.info(f"Sent new event message for '{event.event_name}' (ID: {message.id}) in channel {channel.id}")
    except discord.HTTPException as e:
        _log.error(f"Failed to send event message for {event.event_name} in channel {channel.id}: {e}")
    except Exception as e:
        _log.exception(f"Unexpected error sending event message for {event.event_name}: {e}")


# --- REFACTORED fetch_thread_for_event ---
async def fetch_thread_for_event(client: discord.Client, event: Event) -> discord.Thread:
    """
    Fetches and validates the discord.Thread for an event.

    Returns:
        discord.Thread: The validated thread object.

    Raises:
        MissingChannelIDError: If event.thread_id is None.
        ThreadNotFoundError: If the channel ID doesn't exist or the fetched channel is not a Thread.
        ThreadAccessError: If the bot lacks permissions to fetch the channel.
        Exception: For unexpected errors during fetching.
    """
    if not event.thread_id:
        # Raise immediately if ID is missing
        raise MissingChannelIDError(event.event_name)

    channel = None
    try:
        channel = client.get_channel(event.thread_id)
        # Fallback fetch if get_channel returns None (cache miss)
        if channel is None:
            _log.debug(f"get_channel returned None for {event.thread_id}, attempting fetch_channel.")
            channel = await client.fetch_channel(event.thread_id)

    except discord.errors.NotFound as e:
        # Channel ID does not exist on Discord
        raise ThreadNotFoundError(event.event_name, event.thread_id) from e
    except discord.errors.Forbidden as e:
        # Bot lacks permissions
        raise ThreadAccessError(event.event_name, event.thread_id, original_exception=e) from e
    except Exception as e:
        # Log unexpected errors during fetch but re-raise them
        _log.exception(
            f"Unexpected error getting/fetching channel {event.thread_id} for event '{event.event_name}': {e}"
        )
        raise  # Re-raise the original unexpected exception

    # Validate type
    if not isinstance(channel, discord.Thread):
        raise ThreadNotFoundError(event.event_name, event.thread_id)

    # No need for cast, type checker knows it's a Thread if no error was raised
    return channel


# --- END REFACTORED fetch_thread_for_event ---


async def _fetch_event_message(thread: discord.Thread, event: Event) -> discord.Message | None:
    """Fetches the existing event message. Returns None if not found/fetchable, clears event.message_id if not found."""
    if not event.message_id:
        return None  # No ID to fetch

    try:
        message = await thread.fetch_message(event.message_id)
        _log.debug(f"Successfully fetched message {event.message_id} for event '{event.event_name}'.")
        return message
    except discord.errors.NotFound:
        _log.warning(
            f"Message ID {event.message_id} not found in thread {thread.id} for event '{event.event_name}'. "
            f"Will send a new message."
        )
        event.message_id = None  # Clear invalid ID
        return None
    except discord.errors.Forbidden:
        _log.error(
            f"Bot lacks permissions to fetch message {event.message_id} in thread {thread.id} "
            f"for event '{event.event_name}'. Cannot update message."
        )
        return None  # Cannot proceed
    except discord.HTTPException as e:
        _log.error(
            f"HTTP error fetching message {event.message_id} in thread {thread.id} for event '{event.event_name}': {e}"
        )
        return None  # Avoid proceeding if fetch failed unexpectedly
    except Exception as e:
        _log.exception(f"Unexpected error fetching message {event.message_id} for event '{event.event_name}': {e}")
        return None  # Avoid proceeding on unknown errors


# --- REFACTORED update_event_message ---
async def update_event_message(client: discord.Client, event: Event):
    """
    Updates an existing event message or sends a new one if not found.
    Orchestrates fetching channel/message and performing the update/send action.
    Handles errors during thread fetching gracefully.
    """
    if not isinstance(event, Event):
        _log.error(f"update_event_message received non-Event object: {type(event)}")
        return

    # 1. Fetch and Validate Thread - Catch expected errors
    thread: discord.Thread | None = None
    try:
        thread = await fetch_thread_for_event(client, event)
    except BotCommandError as e:
        # Log handled errors from fetch_thread_for_event and stop processing for this event
        # Use the error's defined log level
        log_level = getattr(e, "log_level", logging.WARNING)
        _log.log(log_level, f"Failed to get thread for event '{event.event_name}': {e}")
        return
    except Exception as e:
        # Log unexpected errors during fetch and stop processing
        _log.exception(f"Unexpected error fetching thread for event '{event.event_name}': {e}")
        return

    # If fetch succeeded, thread is guaranteed to be a discord.Thread

    # 2. Fetch Existing Message (if applicable)
    message = await _fetch_event_message(thread, event)
    # If fetching failed due to permissions/HTTP error, message will be None, and we stop.
    # If message was not found (NotFound), message is None, and event.message_id is cleared.
    if message is None and event.message_id is not None:
        # This condition means fetching failed due to permissions/HTTP error, not just NotFound
        # Error was already logged by _fetch_event_message, so just return
        return

    # 3. Determine Action: Edit or Send New
    view = OpenEvent(event) if event.open else ClosedEvent(event)
    message_content = create_event_message(event)

    if message:
        # Edit existing message
        try:
            await message.edit(content=message_content, view=view)
            _log.info(f"Updated event message for '{event.event_name}' (ID: {message.id}) in thread {thread.id}")
        except discord.errors.Forbidden:
            _log.error(
                f"Bot lacks permissions to edit message {message.id} in thread {thread.id} "
                f"for event '{event.event_name}'."
            )
        except discord.HTTPException as e:
            _log.error(f"Failed to update event message {message.id} for {event.event_name}: {e}")
        except Exception as e:
            _log.exception(f"Unexpected error updating event message {message.id} for {event.event_name}: {e}")
    else:
        # Send a new message (handles missing ID or NotFound error during fetch)
        _log.info(f"Sending new event message for '{event.event_name}' to thread {thread.id}.")
        await send_event_message(thread, event)


async def load_and_update_events(client: discord.Client):
    """Loads events on startup and ensures their messages/views are up-to-date."""
    _log.info("Loading and updating event messages...")
    events = load_event_data()
    if not events:
        _log.info("No events found to load.")
        return

    for event in events:
        if not event.archived:
            # Pass only the client and event
            await update_event_message(client, event)

            # Register deadline close alerts
            thread = await fetch_thread_for_event(client, event)
            register_deadline_reminders(client, event, thread)

    _log.info("Finished loading and updating event messages.")


def register_deadline_reminders(client: discord.Client, event: Event, thread: discord.Thread):
    _log.info(f"Registering deadline reminders for event '{event.event_name}'.")

    from offkai_bot.alerts.alerts import register_alert

    if event.event_deadline and not event.is_past_deadline:
        with contextlib.suppress(AlertTimeInPastError):
            register_alert(event.event_deadline, CloseOffkaiTask(client=client, event_name=event.event_name))
            _log.info(f"Registered auto-close task for '{event.event_name}'.")

            if event.channel_id:
                register_alert(
                    event.event_deadline - timedelta(days=1),
                    SendMessageTask(
                        client=client,
                        channel_id=event.channel_id,
                        message=f"24 hours until registration deadline for {event.event_name}! "
                        f"See {thread.mention} for details.",
                    ),
                )
                _log.info(f"Registered 24 hour reminder for '{event.event_name}'.")

                register_alert(
                    event.event_deadline - timedelta(days=3),
                    SendMessageTask(
                        client=client,
                        channel_id=event.channel_id,
                        message=f"3 days until registration deadline for {event.event_name}! "
                        f"See {thread.mention} for details.",
                    ),
                )
                _log.info(f"Registered 3 day reminder for '{event.event_name}'.")

                register_alert(
                    event.event_deadline - timedelta(days=7),
                    SendMessageTask(
                        client=client,
                        channel_id=event.channel_id,
                        message=f"1 week until registration deadline for {event.event_name}! "
                        f"See {thread.mention} for details.",
                    ),
                )

                _log.info(f"Registered 1 week reminder for '{event.event_name}'.")
