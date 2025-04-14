import logging
from datetime import UTC, datetime

import discord
from discord import ui

from .data.event import Event, create_event_message, load_event_data, save_event_data
from .data.response import Response, add_response, get_responses, remove_response

_log = logging.getLogger(__name__)


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
        # else:
        #     # Add a non-required placeholder if drinks aren't needed, or omit entirely
        #     self.drink_choice_input = ui.TextInput(
        #         label="🍺 Drink choice (Not required for this event)",
        #         placeholder="Type N/A or leave blank.",
        #         required=False,  # Make not required if drinks aren't needed
        #         custom_id="drink_choice_na",
        #     )
        #     self.add_item(self.drink_choice_input)

    @property
    def event_name(self) -> str:
        return self.event.event_name

    async def on_submit(self, interaction: discord.Interaction):
        # --- Validation ---
        extra_people_str = self.extra_people_input.value
        behave_confirm_str = self.behave_checkbox_input.value
        arrival_confirm_str = self.arrival_checkbox_input.value
        drink_choice_str = self.drink_choice_input.value if self.drink_choice_input else "N/A"

        if not extra_people_str.isdigit() or not (0 <= int(extra_people_str) <= 5):
            await error_message(interaction, "Extra people must be a number between 0 and 5.")
            return
        num_extra_people = int(extra_people_str)
        total_people = 1 + num_extra_people  # Submitter + extras

        if behave_confirm_str.lower() != "yes" or arrival_confirm_str.lower() != "yes":
            await error_message(interaction, "Please confirm behavior and arrival by typing 'Yes'.")
            return

        selected_drinks = []
        if self.event.has_drinks:
            if not drink_choice_str:
                await error_message(interaction, "Please specify your drink choice(s).")
                return

            # --- Case-Insensitive Drink Validation ---
            # 1. Convert user input to lowercase, strip whitespace, and remove empty entries
            raw_drinks_input = [drink.lower().strip() for drink in drink_choice_str.split(",")]
            raw_drinks_input = [d for d in raw_drinks_input if d]  # Filter out empty strings

            # 2. Convert allowed drinks to lowercase for comparison
            allowed_drinks_lower = [d.lower() for d in self.event.drinks]

            # 3. Check for invalid drinks (case-insensitive comparison)
            invalid_drinks = [d for d in raw_drinks_input if d not in allowed_drinks_lower]
            if invalid_drinks:
                # Show original case allowed drinks in the error message for clarity
                await error_message(
                    interaction,
                    f"Invalid drink choices: {', '.join(invalid_drinks)}. Choose from: {', '.join(self.event.drinks)}",
                )
                return
            # --- End Case-Insensitive Validation ---

            # Check count matches total people
            if len(raw_drinks_input) != total_people:
                await error_message(
                    interaction,
                    (
                        f"Please provide exactly {total_people} drink choice(s)"
                        "(one for you and each extra person), separated by commas."
                    ),
                )
                return
            selected_drinks = raw_drinks_input
        else:
            # If drinks aren't needed, allow empty or "N/A"
            if drink_choice_str and drink_choice_str.lower() != "n/a":
                await error_message(
                    interaction,
                    "Drinks are not required for this event. Please enter 'N/A' or leave the drink field blank.",
                )
                return
            selected_drinks = []  # Ensure it's an empty list

        # --- Create Response Object ---
        try:
            new_response = Response(
                user_id=interaction.user.id,
                username=interaction.user.name,
                extra_people=num_extra_people,
                behavior_confirmed=(behave_confirm_str.lower() == "yes"),
                arrival_confirmed=(arrival_confirm_str.lower() == "yes"),
                event_name=self.event.event_name,
                timestamp=datetime.now(UTC),  # Use timezone-aware UTC time
                drinks=selected_drinks,
            )
        except Exception as e:
            _log.error(f"Error creating Response object: {e}", exc_info=True)
            await error_message(interaction, "An internal error occurred creating your response.")
            return

        # --- Add Response using Util function ---
        success = add_response(self.event.event_name, new_response)

        if success:
            # Confirm submission
            drinks_msg = f"\n🍺 Drinks: {', '.join(selected_drinks)}" if selected_drinks else ""
            await interaction.response.send_message(
                f"✅ Attendance confirmed for **{self.event.event_name}**!\n"
                f"👥 Bringing: {num_extra_people} extra guest(s)\n"
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
        else:
            # User already responded
            await error_message(interaction, "You have already submitted a response for this event.")


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
        # Use remove_response from util
        removed = remove_response(self.event.event_name, interaction.user.id)

        if removed:
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
        else:
            await error_message(
                interaction,
                "You have not registered for this event, so you cannot withdraw.",
            )


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


# --- REFACTORED update_event_message ---
async def update_event_message(client: discord.Client, event: Event):
    """
    Updates an existing event message or sends a new one if not found.
    Provides more detailed logging for channel/message fetching issues.
    """
    if not isinstance(event, Event):
        _log.error(f"update_event_message received non-Event object: {type(event)}")
        return
    if not event.channel_id:
        _log.warning(f"Cannot update message for event '{event.event_name}': missing channel_id.")
        return

    # --- Step 1: Fetch Channel/Thread ---
    channel = None
    try:
        # Use get_channel which might return None or a cached object
        channel = client.get_channel(event.channel_id)
        if channel is None:
            channel = await client.fetch_channel(event.channel_id)
    except discord.errors.NotFound:
        _log.error(f"Channel/Thread ID {event.channel_id} for event '{event.event_name}' not found via fetch_channel.")
        return
    except discord.errors.Forbidden:
        _log.error(f"Bot lacks permissions to fetch channel/thread {event.channel_id} for event '{event.event_name}'.")
        return
    except Exception as e:
        # Catch unexpected errors during channel retrieval
        _log.exception(
            f"Unexpected error getting/fetching channel {event.channel_id} for event '{event.event_name}': {e}"
        )
        return

    # --- Step 2: Validate Channel ---
    if not isinstance(channel, discord.Thread):
        # Log more specifically when the type is wrong
        _log.error(
            f"Channel with ID {event.channel_id} for event '{event.event_name}' is not a Thread. "
            f"Found type: {type(channel).__name__}."
        )
        return

    # --- Step 3: Fetch Existing Message (if ID exists) ---
    message: discord.Message | None = None
    if event.message_id:
        try:
            message = await channel.fetch_message(event.message_id)
            _log.debug(f"Successfully fetched message {event.message_id} for event '{event.event_name}'.")
        except discord.errors.NotFound:
            _log.warning(
                f"Message ID {event.message_id} not found in thread {channel.id} for event '{event.event_name}'. "
                f"Will send a new message."
            )
            event.message_id = None  # Clear invalid ID so a new one is sent
        except discord.errors.Forbidden:
            _log.error(
                f"Bot lacks permissions to fetch message {event.message_id} in thread {channel.id} "
                f"for event '{event.event_name}'. Cannot update message."
            )
            return  # Cannot proceed without fetching
        except discord.HTTPException as e:
            _log.error(
                f"HTTP error fetching message {event.message_id} in thread {channel.id} "
                f"for event '{event.event_name}': {e}"
            )
            return  # Avoid proceeding if fetch failed unexpectedly
        except Exception as e:
            _log.exception(f"Unexpected error fetching message {event.message_id} for event '{event.event_name}': {e}")
            return  # Avoid proceeding on unknown errors

    # --- Step 4: Edit Existing Message or Send New One ---
    if message:
        # Edit existing message
        try:
            view = OpenEvent(event) if event.open else ClosedEvent(event)
            message_content = create_event_message(event)
            # Check if content/view actually needs updating (optional optimization)
            # if message.content == message_content and message.view == view: # Equality check for views might be hard
            #    _log.debug(f"Message {message.id} for event '{event.event_name}' already up-to-date.")
            #    return
            await message.edit(content=message_content, view=view)
            _log.info(f"Updated event message for '{event.event_name}' (ID: {message.id}) in thread {channel.id}")
        except discord.errors.Forbidden:
            _log.error(
                f"Bot lacks permissions to edit message {message.id} in thread {channel.id} "
                f"for event '{event.event_name}'."
            )
            # Continue, as the event state might be saved later, but log the failure.
        except discord.HTTPException as e:
            _log.error(f"Failed to update event message {message.id} for {event.event_name}: {e}")
        except Exception as e:
            _log.exception(f"Unexpected error updating event message {message.id} for {event.event_name}: {e}")
    else:
        # Send a new message (handles missing ID or NotFound error)
        # send_event_message handles its own errors and saving
        _log.info(f"Sending new event message for '{event.event_name}' to thread {channel.id}.")
        await send_event_message(channel, event)


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
