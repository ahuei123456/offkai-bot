import logging
from datetime import UTC, datetime

import discord
from discord import ui

from offkai_bot.errors import (
    DuplicateResponseError,
    ResponseNotFoundError,
)

from .data.event import Event
from .data.response import (
    Response,
    WaitlistEntry,
    add_response,
    add_to_waitlist,
    get_responses,
    get_waitlist,
    promote_from_waitlist,
    remove_from_waitlist,
    remove_response,
)

_log = logging.getLogger(__name__)


# --- Custom Exception for Validation ---
class ValidationError(Exception):
    """Custom exception for modal validation errors."""

    pass


# --- Helper ---
async def error_message(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(f"❌ {message}", ephemeral=True)


def get_current_attendance_count(event_name: str) -> int:
    """Calculate total current attendance including extra people."""
    responses = get_responses(event_name)
    return sum(1 + response.extra_people for response in responses)


def is_event_at_capacity(event: Event) -> bool:
    """Check if the event has reached its maximum capacity."""
    if event.max_capacity is None:
        return False  # Unlimited capacity

    current_count = get_current_attendance_count(event.event_name)
    return current_count >= event.max_capacity


def would_exceed_capacity(event: Event, num_people: int) -> bool:
    """Check if adding num_people would exceed the event's capacity."""
    if event.max_capacity is None:
        return False  # Unlimited capacity

    current_count = get_current_attendance_count(event.event_name)
    return (current_count + num_people) > event.max_capacity


def get_remaining_capacity(event: Event) -> int | None:
    """Get the number of remaining spots. Returns None if unlimited capacity."""
    if event.max_capacity is None:
        return None

    current_count = get_current_attendance_count(event.event_name)
    return max(0, event.max_capacity - current_count)


async def promote_waitlist_batch(event: Event, client: discord.Client) -> list[int]:
    """
    Promote users from waitlist to fill available capacity.

    Returns list of promoted user IDs.
    """
    promoted_user_ids: list[int] = []
    promoted_count = 0

    while True:
        # Check if we should continue promoting
        if event.max_capacity is None:
            # No capacity limit, only promote one person (original behavior for unlimited events)
            if promoted_count >= 1:
                break
        else:
            # Check if we're at capacity
            if is_event_at_capacity(event):
                break

            # Check if there's anyone on the waitlist
            waitlist = get_waitlist(event.event_name)
            if not waitlist:
                break

            # Check if the next person fits
            next_entry = waitlist[0]
            next_total_people = 1 + next_entry.extra_people
            remaining_capacity = get_remaining_capacity(event)
            if remaining_capacity is not None and next_total_people > remaining_capacity:
                # Next person doesn't fit, stop promoting
                break

        # Promote the next person
        promoted_entry = promote_from_waitlist(event.event_name)
        if not promoted_entry:
            # Waitlist is empty
            break

        # Convert waitlist entry to regular response
        promoted_response = Response(
            user_id=promoted_entry.user_id,
            username=promoted_entry.username,
            extra_people=promoted_entry.extra_people,
            behavior_confirmed=promoted_entry.behavior_confirmed,
            arrival_confirmed=promoted_entry.arrival_confirmed,
            event_name=promoted_entry.event_name,
            timestamp=promoted_entry.timestamp,
            drinks=promoted_entry.drinks,
        )
        add_response(event.event_name, promoted_response)
        promoted_count += 1
        promoted_user_ids.append(promoted_entry.user_id)

        # Notify the promoted user
        try:
            promoted_user = await client.fetch_user(promoted_entry.user_id)
            await promoted_user.send(
                f"🎉 Great news! A spot has opened up for **{event.event_name}**!\n"
                f"You've been automatically moved from the waitlist to confirmed attendees.\n\n"
                f"⚠️ **Important:** Withdrawing after the deadline is strongly discouraged. "
                f"If you withdraw late, you are fully responsible for any consequences, including "
                f"payment requests from the event organizer and potential server moderation action."
            )
            _log.info(f"Promoted user {promoted_entry.user_id} from waitlist for event '{event.event_name}'.")
        except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            _log.warning(f"Could not notify promoted user {promoted_entry.user_id} for event '{event.event_name}': {e}")

    return promoted_user_ids


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
        # 1. Create the confirmation message string
        drinks_msg = f"\n🍺 Drinks: {', '.join(response.drinks)}" if response.drinks else ""
        confirmation_message = (
            f"✅ Attendance confirmed for **{self.event.event_name}**!\n"
            f"👥 Bringing: {response.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}\n\n"
            f"⚠️ **Important:** Withdrawing after the deadline is strongly discouraged. "
            f"If you withdraw late, you are fully responsible for any consequences, including "
            f"payment requests from the event organizer and potential server moderation action."
        )

        # 2. Attempt to DM the user first
        try:
            await interaction.user.send(confirmation_message)
            # If DM succeeds, send a brief confirmation to the channel
            await interaction.response.send_message(
                "✅ Your attendance is confirmed! I've sent you a DM with the details.", ephemeral=True
            )
        except (discord.Forbidden, discord.HTTPException):
            # 3. If DM fails, fall back to sending an ephemeral message in the channel
            await interaction.response.send_message(confirmation_message, ephemeral=True)

        # 4. Add user to the thread
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.add_user(interaction.user)
            else:
                _log.warning(
                    f"Could not add user {interaction.user.id} to thread {interaction.channel_id} (not a thread?)."
                )
        except discord.HTTPException as e:
            _log.error(f"Failed to add user {interaction.user.id} to thread {interaction.channel_id}: {e}")

    async def _handle_waitlist_submission(self, interaction: discord.Interaction, entry: WaitlistEntry):
        """Handles actions after a user is added to the waitlist."""
        # 1. Create the waitlist confirmation message
        drinks_msg = f"\n🍺 Drinks: {', '.join(entry.drinks)}" if entry.drinks else ""
        waitlist_message = (
            f"📋 You've been added to the waitlist for **{self.event.event_name}**!\n"
            f"👥 Bringing: {entry.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}\n\n"
            f"You will be automatically added to the event if a spot opens up.\n\n"
            f"⚠️ **Important:** Withdrawing after the deadline is strongly discouraged. "
            f"If you withdraw late, you are fully responsible for any consequences, including "
            f"payment requests from the event organizer and potential server moderation action."
        )

        # 2. Attempt to DM the user first
        try:
            await interaction.user.send(waitlist_message)
            # If DM succeeds, send a brief confirmation to the channel
            await interaction.response.send_message(
                "📋 You've been added to the waitlist! I've sent you a DM with the details.", ephemeral=True
            )
        except (discord.Forbidden, discord.HTTPException):
            # 3. If DM fails, fall back to sending an ephemeral message in the channel
            await interaction.response.send_message(waitlist_message, ephemeral=True)

        # 4. Add user to the thread
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.add_user(interaction.user)
            else:
                _log.warning(
                    f"Could not add user {interaction.user.id} to thread {interaction.channel_id} (not a thread?)."
                )
        except discord.HTTPException as e:
            _log.error(f"Failed to add user {interaction.user.id} to thread {interaction.channel_id}: {e}")

    async def _handle_waitlist_capacity_exceeded(
        self, interaction: discord.Interaction, entry: WaitlistEntry, total_people_in_group: int, remaining_spots: int
    ):
        """Handles actions when a user's group exceeds capacity and is added to waitlist."""
        # 1. Create the capacity exceeded + waitlist message
        drinks_msg = f"\n🍺 Drinks: {', '.join(entry.drinks)}" if entry.drinks else ""
        waitlist_message = (
            f"❌ Sorry, your group of {total_people_in_group} people would exceed the capacity "
            f"for **{self.event.event_name}**.\n"
            f"Only {remaining_spots} spot(s) remaining out of {self.event.max_capacity} total.\n\n"
            f"📋 For now you will be added to the waiting list.\n"
            f"👥 Bringing: {entry.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}\n\n"
            f"You can choose to leave the offkai and re-apply with fewer people, "
            f"or stay on the waitlist and be automatically added if a spot opens up."
        )

        # 2. Attempt to DM the user first
        try:
            await interaction.user.send(waitlist_message)
            # If DM succeeds, send a brief confirmation to the channel
            await interaction.response.send_message(
                "📋 Your group exceeds capacity. You've been added to the waitlist! "
                "I've sent you a DM with the details.",
                ephemeral=True,
            )
        except (discord.Forbidden, discord.HTTPException):
            # 3. If DM fails, fall back to sending an ephemeral message in the channel
            await interaction.response.send_message(waitlist_message, ephemeral=True)

        # 4. Add user to the thread
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.add_user(interaction.user)
            else:
                _log.warning(
                    f"Could not add user {interaction.user.id} to thread {interaction.channel_id} (not a thread?)."
                )
        except discord.HTTPException as e:
            _log.error(f"Failed to add user {interaction.user.id} to thread {interaction.channel_id}: {e}")

    async def _send_capacity_reached_message(self, interaction: discord.Interaction):
        """Sends a message to the thread when capacity is first reached."""
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(
                    f"⚠️ **Maximum capacity has been reached for {self.event.event_name}!**\n"
                    f"New registrations will be added to the waitlist."
                )
                _log.info(f"Sent capacity reached message to thread for event '{self.event.event_name}'.")
            else:
                _log.warning(f"Could not send capacity message to thread {interaction.channel_id} (not a thread?).")
        except discord.HTTPException as e:
            _log.error(f"Failed to send capacity message to thread {interaction.channel_id}: {e}")

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

            # 3. Calculate total people in this registration
            total_people_in_group = 1 + num_extra_people

            # 4. Check if event has reached capacity, if deadline has passed, or if event is closed
            is_past_deadline = self.event.is_past_deadline
            is_closed = not self.event.open
            at_capacity = is_event_at_capacity(self.event)

            # 5. Determine whether to add to responses or waitlist
            # If deadline has passed OR event is closed OR event is at capacity, add to waitlist
            if is_past_deadline or is_closed or at_capacity:
                # Add to waitlist
                new_entry = WaitlistEntry(
                    user_id=interaction.user.id,
                    username=interaction.user.name,
                    extra_people=num_extra_people,
                    behavior_confirmed=True,
                    arrival_confirmed=True,
                    event_name=self.event.event_name,
                    timestamp=datetime.now(UTC),
                    drinks=selected_drinks,
                )

                add_to_waitlist(self.event.event_name, new_entry)

                # Send waitlist confirmation
                await self._handle_waitlist_submission(interaction, new_entry)

                # Check if this is the first time capacity was reached - send thread message
                # Only send this if capacity just reached (not if deadline passed or event closed)
                if at_capacity and not is_past_deadline and not is_closed:
                    current_count = get_current_attendance_count(self.event.event_name)
                    if current_count == self.event.max_capacity:
                        await self._send_capacity_reached_message(interaction)

            elif would_exceed_capacity(self.event, total_people_in_group):
                # Registration would exceed capacity - add to waitlist with special message
                remaining = get_remaining_capacity(self.event)
                # would_exceed_capacity only returns True when there's a capacity limit
                assert remaining is not None, "Capacity should be set if would_exceed_capacity is True"

                # Create waitlist entry
                new_entry = WaitlistEntry(
                    user_id=interaction.user.id,
                    username=interaction.user.name,
                    extra_people=num_extra_people,
                    behavior_confirmed=True,
                    arrival_confirmed=True,
                    event_name=self.event.event_name,
                    timestamp=datetime.now(UTC),
                    drinks=selected_drinks,
                )

                # Add to waitlist
                add_to_waitlist(self.event.event_name, new_entry)

                # Send capacity exceeded + waitlist confirmation
                await self._handle_waitlist_capacity_exceeded(interaction, new_entry, total_people_in_group, remaining)

            else:
                # Event is not at capacity and deadline hasn't passed - add to regular responses
                new_response = Response(
                    user_id=interaction.user.id,
                    username=interaction.user.name,
                    extra_people=num_extra_people,
                    behavior_confirmed=True,
                    arrival_confirmed=True,
                    event_name=self.event.event_name,
                    timestamp=datetime.now(UTC),
                    drinks=selected_drinks,
                )

                add_response(self.event.event_name, new_response)
                await self._handle_successful_submission(interaction, new_response)

                # Check if we just reached capacity
                if self.event.max_capacity is not None and not is_past_deadline and not is_closed:
                    current_count = get_current_attendance_count(self.event.event_name)
                    if current_count == self.event.max_capacity:
                        await self._send_capacity_reached_message(interaction)

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
        removed_from_responses = False
        try:
            # Try to remove from responses first
            remove_response(self.event.event_name, interaction.user.id)
            removed_from_responses = True

        except ResponseNotFoundError:
            # User not in responses, try waitlist
            try:
                remove_from_waitlist(self.event.event_name, interaction.user.id)
                removed_from_responses = False
            except ResponseNotFoundError:
                # User not in responses or waitlist
                await error_message(
                    interaction,
                    f"❌ You have not registered for **{self.event.event_name}**, so you cannot withdraw.",
                )
                return

        except Exception as e:
            # Catch any other unexpected errors during removal
            _log.error(
                f"Unexpected error during withdrawal for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred while processing your withdrawal.")
            return

        # --- Success Path (user was removed from either responses or waitlist) ---
        try:
            # 1. Create the withdrawal message string
            withdrawal_message = f"👋 Your attendance for **{self.event.event_name}** has been withdrawn."

            # 2. Attempt to DM the user first
            try:
                await interaction.user.send(withdrawal_message)
                # If DM succeeds, send a brief confirmation to the channel
                await interaction.response.send_message(
                    "✅ Your withdrawal is confirmed. I've sent you a DM.", ephemeral=True
                )
            except (discord.Forbidden, discord.HTTPException):
                # 3. If DM fails, fall back to sending an ephemeral message in the channel
                await interaction.response.send_message(withdrawal_message, ephemeral=True)

            # 4. Remove user from the thread
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

            # 5. Promote users from the waitlist only if removed from responses
            # (not from waitlist, since that doesn't free up capacity)
            if removed_from_responses:
                await promote_waitlist_batch(self.event, interaction.client)

        except Exception as e:
            # Catch any errors during notification/promotion
            _log.error(
                f"Error during post-withdrawal actions for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
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

    @discord.ui.button(
        label="Join Waitlist",
        style=discord.ButtonStyle.primary,
        row=1,
        custom_id="join_waitlist_closed_button",
    )
    async def join_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show the modal to join waitlist
        await interaction.response.send_modal(GatheringModal(event=self.event))

    @discord.ui.button(
        label="Withdraw Attendance",
        style=discord.ButtonStyle.danger,
        row=2,
        custom_id="withdraw_button_closed",
    )
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        removed_from_responses = False
        try:
            # Try to remove from responses first
            remove_response(self.event.event_name, interaction.user.id)
            removed_from_responses = True

        except ResponseNotFoundError:
            # User not in responses, try waitlist
            try:
                remove_from_waitlist(self.event.event_name, interaction.user.id)
                removed_from_responses = False
            except ResponseNotFoundError:
                # User not in responses or waitlist
                await error_message(
                    interaction,
                    f"❌ You have not registered for **{self.event.event_name}**, so you cannot withdraw.",
                )
                return

        except Exception as e:
            # Catch any other unexpected errors during removal
            _log.error(
                f"Unexpected error during withdrawal for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred while processing your withdrawal.")
            return

        # --- Success Path (user was removed from either responses or waitlist) ---
        try:
            # 1. Create the withdrawal message string
            withdrawal_message = (
                f"👋 Your attendance for **{self.event.event_name}** has been withdrawn.\n\n"
                f"⚠️ **Important:** Withdrawing after responses are closed is your full responsibility. "
                f"You may be contacted by the event organizer for payment if needed. "
                f"Failure to comply may result in server moderation action."
            )

            # 2. Attempt to DM the user first
            try:
                await interaction.user.send(withdrawal_message)
                # If DM succeeds, send a brief confirmation to the channel
                await interaction.response.send_message(
                    "✅ Your withdrawal is confirmed. I've sent you a DM.", ephemeral=True
                )
            except (discord.Forbidden, discord.HTTPException):
                # 3. If DM fails, fall back to sending an ephemeral message in the channel
                await interaction.response.send_message(withdrawal_message, ephemeral=True)

            # 4. Remove user from the thread
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

            # 4.5. Notify event creator about withdrawal (only after responses are closed)
            if self.event.creator_id:
                try:
                    creator = await interaction.client.fetch_user(self.event.creator_id)
                    await creator.send(
                        f"⚠️ **Withdrawal Notification**\n\n"
                        f"User {interaction.user.mention} ({interaction.user.name}) "
                        f"has withdrawn from **{self.event.event_name}**.\n"
                        f"This withdrawal occurred after responses were closed."
                    )
                    _log.info(
                        f"Notified creator {self.event.creator_id} about withdrawal by {interaction.user.id} "
                        f"from closed event '{self.event.event_name}'."
                    )
                except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                    _log.warning(
                        f"Could not notify creator {self.event.creator_id} about withdrawal "
                        f"from event '{self.event.event_name}': {e}"
                    )

            # 5. Promote users from the waitlist only if removed from responses
            # (not from waitlist, since that doesn't free up capacity)
            if removed_from_responses:
                await promote_waitlist_batch(self.event, interaction.client)

        except Exception as e:
            # Catch any errors during notification/promotion
            _log.error(
                f"Error during post-withdrawal actions for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
            )


class PostDeadlineEvent(EventView):
    """View shown after the deadline has passed - allows joining the waitlist only."""

    def __init__(self, event: Event):  # Expect Event object
        super().__init__(event=event)  # Pass event to parent

    @discord.ui.button(
        label="Join Waitlist",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="join_waitlist_button",
    )
    async def join_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show the same modal, but it will add to waitlist since deadline has passed
        await interaction.response.send_modal(GatheringModal(event=self.event))

    @discord.ui.button(
        label="Withdraw Attendance",
        style=discord.ButtonStyle.danger,
        row=1,
        custom_id="withdraw_button_deadline",
    )
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        removed_from_responses = False
        try:
            # Try to remove from responses first
            remove_response(self.event.event_name, interaction.user.id)
            removed_from_responses = True

        except ResponseNotFoundError:
            # User not in responses, try waitlist
            try:
                remove_from_waitlist(self.event.event_name, interaction.user.id)
                removed_from_responses = False
            except ResponseNotFoundError:
                # User not in responses or waitlist
                await error_message(
                    interaction,
                    f"❌ You have not registered for **{self.event.event_name}**, so you cannot withdraw.",
                )
                return

        except Exception as e:
            # Catch any other unexpected errors during removal
            _log.error(
                f"Unexpected error during withdrawal for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred while processing your withdrawal.")
            return

        # --- Success Path (user was removed from either responses or waitlist) ---
        try:
            # 1. Create the withdrawal message string
            withdrawal_message = (
                f"👋 Your attendance for **{self.event.event_name}** has been withdrawn.\n\n"
                f"⚠️ **Important:** Withdrawing after the deadline is your full responsibility. "
                f"You may be contacted by the event organizer for payment if needed. "
                f"Failure to comply may result in server moderation action."
            )

            # 2. Attempt to DM the user first
            try:
                await interaction.user.send(withdrawal_message)
                # If DM succeeds, send a brief confirmation to the channel
                await interaction.response.send_message(
                    "✅ Your withdrawal is confirmed. I've sent you a DM.", ephemeral=True
                )
            except (discord.Forbidden, discord.HTTPException):
                # 3. If DM fails, fall back to sending an ephemeral message in the channel
                await interaction.response.send_message(withdrawal_message, ephemeral=True)

            # 4. Remove user from the thread
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

            # 4.5. Notify event creator about withdrawal (only after deadline)
            if self.event.creator_id:
                try:
                    creator = await interaction.client.fetch_user(self.event.creator_id)
                    await creator.send(
                        f"⚠️ **Withdrawal Notification**\n\n"
                        f"User {interaction.user.mention} ({interaction.user.name}) "
                        f"has withdrawn from **{self.event.event_name}**.\n"
                        f"This withdrawal occurred after the deadline."
                    )
                    _log.info(
                        f"Notified creator {self.event.creator_id} about withdrawal by {interaction.user.id} "
                        f"from post-deadline event '{self.event.event_name}'."
                    )
                except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                    _log.warning(
                        f"Could not notify creator {self.event.creator_id} about withdrawal "
                        f"from event '{self.event.event_name}': {e}"
                    )

            # 5. Promote users from the waitlist only if removed from responses
            # (not from waitlist, since that doesn't free up capacity)
            if removed_from_responses:
                await promote_waitlist_batch(self.event, interaction.client)

        except Exception as e:
            # Catch any errors during notification/promotion
            _log.error(
                f"Error during post-withdrawal actions for {self.event.event_name} by {interaction.user.id}: {e}",
                exc_info=True,
            )
