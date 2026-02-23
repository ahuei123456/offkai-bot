import logging

import discord

from offkai_bot.data.event import (
    Event,
    create_event_message,
    save_event_data,
    set_event_open_status,
)
from offkai_bot.errors import (
    BotCommandError,
    MissingChannelIDError,
    PinPermissionError,
    ThreadAccessError,
    ThreadNotFoundError,
)
from offkai_bot.interactions import ClosedEvent, OpenEvent, PostDeadlineEvent

_log = logging.getLogger(__name__)


def get_event_view(event: Event):
    """Determines the appropriate view for an event based on its state."""
    if not event.open:
        return ClosedEvent(event)
    elif event.is_past_deadline:
        return PostDeadlineEvent(event)
    else:
        return OpenEvent(event)


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
    """Sends a new event message, pins it, and saves the message ID."""
    if not isinstance(event, Event):
        _log.error(f"send_event_message received non-Event object: {type(event)}")
        return

    view = get_event_view(event)
    message = None
    try:
        message_content = create_event_message(event)  # Use util function
        message = await channel.send(message_content, view=view)

        # Update and save the event BEFORE trying to pin. This ensures the message
        # is tracked even if pinning fails.
        event.message_id = message.id
        save_event_data()
        _log.info(f"Sent new event message for '{event.event_name}' (ID: {message.id}) in channel {channel.id}")

        # Now, attempt to pin the message
        await message.pin(reason="New event message.")

    except discord.Forbidden as e:
        # This will catch permission errors on both .send() and .pin()
        if message:  # If message exists, send succeeded and pin failed
            _log.warning(f"Failed to pin message for '{event.event_name}' due to permissions: {e}")
            raise PinPermissionError(channel, e) from e
        else:  # Send itself failed
            _log.error(f"Failed to send event message for {event.event_name} in channel {channel.id}: {e}")
            raise  # Re-raise the original Forbidden error
    except discord.HTTPException as e:
        # Catch other HTTP errors from send or pin
        _log.error(f"Failed to send or pin event message for {event.event_name} in channel {channel.id}: {e}")
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
    view = get_event_view(event)
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


