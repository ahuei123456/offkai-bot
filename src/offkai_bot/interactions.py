import logging
from datetime import UTC, datetime
from typing import cast

import discord
from discord import ui

from offkai_bot.errors import (
    BotCommandError,
    DuplicateResponseError,
    MissingChannelIDError,
    ResponseNotFoundError,
    ThreadAccessError,
    ThreadNotFoundError,
)

from .data.event import Event, create_event_message, load_event_data, save_event_data
from .data.response import Response, add_response, get_responses, remove_response

_log = logging.getLogger(__name__)


# --- Custom Exception for Validation ---
class ValidationError(Exception):
    """Custom exception for modal validation errors."""

    pass


# --- Helper ---
async def error_message(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(f"❌ {message}", ephemeral=True)


# Class to handle the modal for event attendance
class GatheringModal(ui.Modal):
    def __init__(
        self,
        *,
        event: Event,
        timeout=None,
    ):
        super().__init__(
            title=event.event_name,
            timeout=timeout,
            custom_id=f"modal_{event.event_name}",
        )
        self.event = event

        # Define fields (consider making drink choice conditional later if needed)
        self.extra_people_input: ui.TextInput = ui.TextInput(
            label="🧑 I am bringing extra people (0-5)",
            placeholder="Enter a number between 0-5",
            required=True,
            max_length=1,
            custom_id="extra_people",
        )
        self.behave_checkbox_input: ui.TextInput = ui.TextInput(
            label="✔ I will behave",
            placeholder="You must type 'Yes'",
            required=True,
            custom_id="behave_confirm",
        )
        self.arrival_checkbox_input: ui.TextInput = ui.TextInput(
            label="✔ I will arrive on time",  # Changed wording slightly
            placeholder="You must type 'Yes'",
            required=True,
            custom_id="arrival_confirm",
        )
        # Add other items
        self.add_item(self.extra_people_input)
        self.add_item(self.behave_checkbox_input)
        self.add_item(self.arrival_checkbox_input)

        # Dynamically add drink choice only if needed
        self.drink_choice_input: ui.TextInput | None = None
        if self.event.has_drinks:
            self.drink_choice_input = ui.TextInput(
                label="🍺 Drink choice(s) for you",  # Show available drinks
                placeholder=f"Choose from: {', '.join(self.event.drinks)}. Separate with commas.",
                required=True,
                custom_id="drink_choice",
            )
            self.add_item(self.drink_choice_input)

    @property
    def event_name(self) -> str:
        return self.event.event_name

    # --- Validation Helpers (Raising Exceptions) ---

    def _validate_extra_people(self, extra_people_str: str) -> int:
        """Validates the extra people input.

        Returns:
            int specifying the number of extra people.

        Raises:
            ValidationError: If input is invalid.
        """
        if not extra_people_str.isdigit() or not (0 <= int(extra_people_str) <= 5):
            raise ValidationError("Extra people must be a number between 0 and 5.")
        num_extra_people = int(extra_people_str)
        return num_extra_people

    def _validate_confirmations(self, behave_str: str, arrival_str: str) -> None:
        """Validates the confirmation inputs.

        Returns:
            Tuple containing (behavior_confirmed, arrival_confirmed).

        Raises:
            ValidationError: If confirmations are not 'Yes'.
        """
        behavior_confirmed = behave_str.lower() == "yes"
        arrival_confirmed = arrival_str.lower() == "yes"
        if not behavior_confirmed or not arrival_confirmed:
            raise ValidationError("Please confirm behavior and arrival by typing 'Yes'.")

    def _validate_drinks(self, drink_choice_str: str, total_people: int) -> list[str]:
        """Validates the drink input based on event settings and total people.

        Returns:
            List of validated drink choices (lowercase).

        Raises:
            ValidationError: If drink input is invalid.
        """
        selected_drinks: list[str] = []
        if self.event.has_drinks:
            if not drink_choice_str:
                raise ValidationError("Please specify your drink choice(s).")

            # Case-Insensitive Drink Validation
            raw_drinks_input = [drink.lower().strip() for drink in drink_choice_str.split(",")]
            raw_drinks_input = [d for d in raw_drinks_input if d]  # Filter out empty strings

            allowed_drinks_lower = [d.lower() for d in self.event.drinks]
            invalid_drinks = [d for d in raw_drinks_input if d not in allowed_drinks_lower]
            if invalid_drinks:
                raise ValidationError(
                    f"Invalid drink choices: {', '.join(invalid_drinks)}. Choose from: {', '.join(self.event.drinks)}"
                )

            # Check count matches total people
            if len(raw_drinks_input) != total_people:
                raise ValidationError(
                    f"Please provide exactly {total_people} drink choice(s) "
                    "(one for you and each extra person), separated by commas."
                )
            selected_drinks = raw_drinks_input
        else:
            # If drinks aren't needed, allow empty or "N/A"
            if drink_choice_str and drink_choice_str.lower() != "n/a":
                raise ValidationError(
                    "Drinks are not required for this event. Please enter 'N/A' or leave the drink field blank."
                )
            selected_drinks = []  # Ensure it's an empty list

        return selected_drinks

    async def _handle_successful_submission(self, interaction: discord.Interaction, response: Response):
        """Handles actions after a response is successfully added."""
        # Confirm submission
        drinks_msg = f"\n🍺 Drinks: {', '.join(response.drinks)}" if response.drinks else ""
        await interaction.response.send_message(
            f"✅ Attendance confirmed for **{self.event.event_name}**!\n"
            f"👥 Bringing: {response.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}",
            ephemeral=True,
        )
        # Add user to the thread
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.add_user(interaction.user)
            else:
                _log.warning(
                    f"Could not add user {interaction.user.id} to channel {interaction.channel_id} (not a thread?)."
                )
        except discord.HTTPException as e:
            _log.error(f"Failed to add user {interaction.user.id} to thread {interaction.channel_id}: {e}")

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Get Input Values
        extra_people_str = self.extra_people_input.value
        behave_confirm_str = self.behave_checkbox_input.value
        arrival_confirm_str = self.arrival_checkbox_input.value
        drink_choice_str = self.drink_choice_input.value if self.drink_choice_input else "N/A"

        try:
            # 2. Validate Inputs using Helpers (Raises ValidationError on failure)
            num_extra_people = self._validate_extra_people(extra_people_str)
            self._validate_confirmations(behave_confirm_str, arrival_confirm_str)
            selected_drinks = self._validate_drinks(drink_choice_str, num_extra_people + 1)

            # 3. Create Response Object (Only runs if validation passed)
            new_response = Response(
                user_id=interaction.user.id,
                username=interaction.user.name,
                extra_people=num_extra_people,  # Use validated value directly
                behavior_confirmed=True,  # Use validated value directly
                arrival_confirmed=True,  # Use validated value directly
                event_name=self.event.event_name,
                timestamp=datetime.now(UTC),
                drinks=selected_drinks,  # Use validated value directly
            )

            # 4. Add Response using Util function
            add_response(self.event.event_name, new_response)

            # 5. Handle Outcome
            await self._handle_successful_submission(interaction, new_response)

        except ValidationError as e:
            # Handle specific validation errors raised by helpers
            await error_message(interaction, str(e))
            # No return needed here, function ends after except block

        except DuplicateResponseError as e:
            await error_message(interaction, str(e))

        except Exception as e:
            # Catch any other unexpected errors during Response creation or add_response
            _log.error(f"Unexpected error during modal submission for {self.event.event_name}: {e}", exc_info=True)
            await error_message(interaction, "An internal error occurred processing your response.")
            # No return needed here


# --- Views ---
class EventView(ui.View):
    def __init__(self, event: Event):  # Expect Event object
        super().__init__(timeout=None)
        self.event = event  # Store the Event object

    @discord.ui.button(
        label="Attendance Count",
        style=discord.ButtonStyle.secondary,
        row=2,
        custom_id="count_button",  # Use secondary style
    )
    async def count(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Use get_responses from util
        event_responses = get_responses(self.event.event_name)

        num = sum(1 + response.extra_people for response in event_responses)

        await interaction.response.send_message(
            f"📝 Current registration count for **{self.event.event_name}**: {num}",
            ephemeral=True,
        )


class OpenEvent(EventView):
    def __init__(self, event: Event):  # Expect Event object
        super().__init__(event=event)  # Pass event to parent

    @discord.ui.button(
        label="Confirm Attendance",
        style=discord.ButtonStyle.success,
        row=0,
        custom_id="confirm_button",  # Use success style
    )
    async def respond(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Pass the Event object to the modal
        await interaction.response.send_modal(GatheringModal(event=self.event))

    @discord.ui.button(
        label="Withdraw Attendance",
        style=discord.ButtonStyle.danger,
        row=1,
        custom_id="withdraw_button",  # Use danger style
    )
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Call remove_response (raises ResponseNotFoundError on failure)
            remove_response(self.event.event_name, interaction.user.id)

            # --- Success Path (only runs if remove_response didn't raise error) ---
            await interaction.response.send_message(
                f"👋 Your attendance for **{self.event.event_name}** has been withdrawn.",
                ephemeral=True,
            )
            # Remove user from the thread
            try:
                if interaction.channel and isinstance(interaction.channel, discord.Thread):
                    await interaction.channel.remove_user(interaction.user)
                else:
                    _log.warning(
                        f"Could not remove user {interaction.user.id} "
                        f"from channel {interaction.channel_id} (not a thread?)."
                    )
            except discord.HTTPException as e:
                _log.error(f"Failed to remove user {interaction.user.id} from thread {interaction.channel_id}: {e}")
            # --- End Success Path ---

        except ResponseNotFoundError:
            # --- Failure Path (response wasn't found) ---
            # Use the error message directly, or customize if needed
            # The default message from the modified error is:
            # "❌ Could not find a response from user ID {user_id} for '{event_name}'."
            # Let's make it slightly more user-friendly for the button context:
            await error_message(
                interaction,
                f"❌ You have not registered for **{self.event.event_name}**, so you cannot withdraw.",
                # Alternatively, use str(e) if the default error message is preferred:
                # await error_message(interaction, str(e))
            )
            # --- End Failure Path ---

        except Exception as e:
            # Catch any other unexpected errors during removal or thread interaction
            _log.error(
                f"Unexpected error during withdrawal for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred while processing your withdrawal.")


class ClosedEvent(EventView):
    def __init__(self, event: Event):  # Expect Event object
        super().__init__(event=event)  # Pass event to parent

    @discord.ui.button(
        label="Responses Closed",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        row=0,
        custom_id="closed_button",
    )
    async def respond(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This button is disabled, so this callback shouldn't trigger
        # If it somehow does, send an ephemeral message
        await interaction.response.send_message("Responses are currently closed for this event.", ephemeral=True)


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
        MissingChannelIDError: If event.channel_id is None.
        ThreadNotFoundError: If the channel ID doesn't exist or the fetched channel is not a Thread.
        ThreadAccessError: If the bot lacks permissions to fetch the channel.
        Exception: For unexpected errors during fetching.
    """
    if not event.channel_id:
        # Raise immediately if ID is missing
        raise MissingChannelIDError(event.event_name)

    channel = None
    try:
        channel = client.get_channel(event.channel_id)
        # Fallback fetch if get_channel returns None (cache miss)
        if channel is None:
            _log.debug(f"get_channel returned None for {event.channel_id}, attempting fetch_channel.")
            channel = await client.fetch_channel(event.channel_id)

    except discord.errors.NotFound as e:
        # Channel ID does not exist on Discord
        raise ThreadNotFoundError(event.event_name, event.channel_id) from e
    except discord.errors.Forbidden as e:
        # Bot lacks permissions
        raise ThreadAccessError(event.event_name, event.channel_id, original_exception=e) from e
    except Exception as e:
        # Log unexpected errors during fetch but re-raise them
        _log.exception(
            f"Unexpected error getting/fetching channel {event.channel_id} for event '{event.event_name}': {e}"
        )
        raise  # Re-raise the original unexpected exception

    # Validate type
    if not isinstance(channel, discord.Thread):
        raise ThreadNotFoundError(event.event_name, event.channel_id)

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
                f"Bot lacks permissions to edit message {message.id} in thread {thread.id} for event '{event.event_name}'."
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

    _log.info("Finished loading and updating event messages.")
