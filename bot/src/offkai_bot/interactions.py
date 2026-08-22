import logging
import random
from datetime import UTC, datetime

import discord
from discord import ui

from offkai_bot.data.event import Event, add_response_for_event
from offkai_bot.data.ranking import can_rank_message_sent, decrease_rank, get_rank, mark_achieved_rank, update_rank
from offkai_bot.data.response import (
    Response,
    WaitlistEntry,
    add_response,
    add_to_waitlist,
    get_effective_display_name,
    get_responses,
    get_waitlist,
    promote_from_waitlist,
    remove_from_waitlist,
    remove_response,
    restore_waitlist_entry,
)
from offkai_bot.errors import (
    DuplicateResponseError,
    ResponseNotFoundError,
)
from offkai_bot.messages import MILESTONE_MESSAGES
from offkai_bot.role_management import assign_event_role, remove_event_role
from offkai_bot.util import build_checkin_url

_log = logging.getLogger(__name__)


# --- Custom Exception for Validation ---
class ValidationError(Exception):
    """Custom exception for modal validation errors."""

    pass


# --- Helper ---
async def error_message(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(f"❌ {message}", ephemeral=True)


def validate_extra_people_input(extra_people_str: str) -> int:
    """Validates an extra-people modal input.

    Returns:
        int specifying the number of extra people.

    Raises:
        ValidationError: If input is invalid.
    """
    if not extra_people_str.isdigit() or not (0 <= int(extra_people_str) <= 5):
        raise ValidationError("Extra people must be a number between 0 and 5.")
    return int(extra_people_str)


def resolve_submitted_display_name(
    submitted_name: str,
    discord_display_name: str,
    username: str,
) -> str:
    """Resolve a submitted preferred name to the event-specific snapshot value."""

    submitted = submitted_name.strip() if isinstance(submitted_name, str) else ""
    discord_name = discord_display_name.strip() if isinstance(discord_display_name, str) else ""
    return submitted or discord_name or username


async def modal_error_message(interaction: discord.Interaction, event_name: str, message: str):
    dm_message = f"❌ I couldn't process your response for **{event_name}**.\n\n{message}"
    try:
        await interaction.user.send(dm_message)
    except (discord.Forbidden, discord.HTTPException) as e:
        _log.warning(
            "Could not DM modal submission error to user %s for event '%s': %s",
            interaction.user.id,
            event_name,
            e,
        )
        await error_message(interaction, message)
        return

    await interaction.response.send_message(
        "❌ I couldn't process your response. I've sent you a DM with the details.",
        ephemeral=True,
    )


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


async def promote_waitlist_batch(event: Event, client: discord.Client, freed_spots: int | None = None) -> list[int]:
    """
    Promote users from waitlist to fill available capacity.

    For events without a target capacity (unlimited capacity and never closed),
    freed_spots bounds the promotion to the headcount freed by a withdrawal so
    the confirmed total stays stable. If freed_spots is also None, there is no
    constraint to protect and the entire waitlist is promoted.

    Returns list of promoted user IDs.
    """
    promoted_user_ids: list[int] = []

    # Resolve guild for role assignment
    guild: discord.Guild | None = None
    if event.role_id and event.thread_id:
        channel = client.get_channel(event.thread_id)
        if isinstance(channel, discord.Thread):
            guild = channel.guild

    # Determine the target capacity for promotion
    # If event was closed with a specific count, don't exceed that count
    # Otherwise, use the max_capacity
    target_capacity: int | None = None
    if event.closed_attendance_count is not None:
        # Event was closed with X people, don't exceed min(closed_count, max_capacity)
        if event.max_capacity is not None:
            target_capacity = min(event.closed_attendance_count, event.max_capacity)
        else:
            target_capacity = event.closed_attendance_count
    else:
        # Event is still open or was never closed, use max_capacity
        target_capacity = event.max_capacity

    if target_capacity is None and freed_spots is not None:
        # Unlimited capacity, but a withdrawal freed a specific headcount:
        # backfill exactly that many spots so the confirmed total stays stable.
        target_capacity = get_current_attendance_count(event.event_name) + freed_spots

    while True:
        # Check if we should continue promoting
        # (if target_capacity is None there is no constraint: drain the whole waitlist)
        if target_capacity is not None:
            # Check if we're at target capacity
            current_count = get_current_attendance_count(event.event_name)
            if current_count >= target_capacity:
                break

            # Check if there's anyone on the waitlist
            waitlist = get_waitlist(event.event_name)
            if not waitlist:
                break

            # Check if the next person fits
            next_entry = waitlist[0]
            next_total_people = 1 + next_entry.extra_people
            remaining_capacity = target_capacity - current_count
            if next_total_people > remaining_capacity:
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
            extras_names=promoted_entry.extras_names,
            display_name=promoted_entry.display_name,
        )
        try:
            add_response_for_event(event, promoted_response)
        except Exception:
            # Roll back the waitlist pop so the user isn't dropped from both lists.
            restore_waitlist_entry(event.event_name, promoted_entry)
            raise
        promoted_user_ids.append(promoted_entry.user_id)

        # Assign event participant role
        if guild and event.role_id:
            await assign_event_role(guild, promoted_entry.user_id, event.role_id)

        # Notify the promoted user
        try:
            rsvp_url = build_checkin_url(promoted_entry.user_id, event.event_name)
            rsvp_link_msg = f"\n🔗 **RSVP Page / QR Code:** {rsvp_url}" if rsvp_url else ""
            rsvp_link_msg_jp = f"\n🔗 **RSVPページ / QRコード:** {rsvp_url}" if rsvp_url else ""

            promoted_user = await client.fetch_user(promoted_entry.user_id)
            await promoted_user.send(
                f"🎉 Great news! A spot has opened up for **{event.event_name}**!\n"
                f"You've been automatically moved from the waitlist to confirmed attendees.\n"
                f"{rsvp_link_msg}\n\n"
                f"🎉 朗報です！**{event.event_name}**に空きが出ました！\n"
                f"ウェイトリストから自動的に参加確定に移動されました。\n"
                f"{rsvp_link_msg_jp}\n\n"
                f"⚠️ **Important:** Withdrawing after the deadline is strongly discouraged. "
                f"If you withdraw late, you are fully responsible for any consequences, including "
                f"payment requests from the event organizer and potential server moderation action.\n\n"
                f"⚠️ **重要:** 締め切り後の辞退は強くお勧めしません。"
                f"遅れて辞退した場合、主催者からの支払い請求やサーバーのモデレーション措置を含む"
                f"すべての結果に対して、全責任を負います。"
            )
            _log.info("Promoted user %s from waitlist for event '%s'.", promoted_entry.user_id, event.event_name)
        except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            _log.warning(
                "Could not notify promoted user %s for event '%s': %s",
                promoted_entry.user_id,
                event.event_name,
                e,
            )

    return promoted_user_ids


# Discord's modal title cap is smaller than the custom_id cap, so a name that
# fits "modal_<event_name>" (see MAX_EVENT_NAME_LENGTH) can still be too long
# to display as the modal's title. Truncate the title only; custom_id keeps
# the full event name for identity.
MODAL_TITLE_MAX_LENGTH = 45


def _build_modal_title(event_name: str) -> str:
    if len(event_name) <= MODAL_TITLE_MAX_LENGTH:
        return event_name
    return event_name[: MODAL_TITLE_MAX_LENGTH - 1] + "…"


# Class to handle the modal for event attendance
class GatheringModal(ui.Modal):
    def __init__(
        self,
        *,
        event: Event,
        timeout=None,
    ):
        super().__init__(
            title=_build_modal_title(event.event_name),
            timeout=timeout,
            custom_id=f"modal_{event.event_name}",
        )
        self.event = event

        self.preferred_name_input: ui.TextInput = ui.TextInput(
            label="Name you'd like us to use",
            placeholder="Optional; leave blank to use your Discord display name",
            required=False,
            max_length=32,
            custom_id="preferred_name",
        )
        self.extra_people_input: ui.TextInput = ui.TextInput(
            label="🧑 I am bringing extra people (0-5)",
            placeholder="Enter a number between 0-5",
            required=True,
            max_length=1,
            custom_id="extra_people",
        )
        self.confirmation_input: ui.TextInput = ui.TextInput(
            label="I agree to behave and arrive on time",
            placeholder="Type Yes to confirm both",
            required=True,
            custom_id="behavior_arrival_confirm",
        )
        # These aliases keep older integrations from failing while the modal
        # itself uses one combined confirmation field.
        self.behave_checkbox_input: ui.TextInput = self.confirmation_input
        self.arrival_checkbox_input: ui.TextInput = self.confirmation_input

        self.add_item(self.preferred_name_input)
        self.add_item(self.extra_people_input)
        self.add_item(self.confirmation_input)

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

        self.extras_names_input: ui.TextInput = ui.TextInput(
            label="👥 Extras names",  # Show available drinks
            placeholder="Enter you extras names. Separate with commas.",
            required=False,
            custom_id="extras_names",
        )
        self.add_item(self.extras_names_input)

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
        return validate_extra_people_input(extra_people_str)

    def _validate_confirmations(self, confirmation_str: str, arrival_str: str | None = None) -> None:
        """Validate the combined acknowledgement, accepting case and padding variations."""

        confirmations = (confirmation_str,) if arrival_str is None else (confirmation_str, arrival_str)
        if not all(isinstance(value, str) and value.strip().casefold() == "yes" for value in confirmations):
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

    def _validate_extra_people_names(self, extras: str, num_extra: int) -> list[str]:
        if num_extra == 0:
            if extras.strip() != "":
                raise ValidationError("You specified 0 extra people, so please leave the extras names field empty.")
            return []

        # If they bring extra people, extras names are required
        if not extras.strip():
            raise ValidationError(
                f"Please provide exactly {num_extra} name(s) "
                "(one for each person you are bringing), separated by commas."
            )

        names = [name.strip() for name in extras.split(",")]
        # Filter out empty names to ensure they don't submit ",,," or similar
        non_empty_names = [name for name in names if name]

        if len(non_empty_names) != num_extra:
            raise ValidationError(
                f"Please provide exactly {num_extra} non-empty name(s) "
                "(one for each person you are bringing), separated by commas."
            )
        return non_empty_names

    async def _handle_successful_submission(self, interaction: discord.Interaction, response: Response):
        """Handles actions after a response is successfully added."""
        recorded_name = get_effective_display_name(response)
        rsvp_url = build_checkin_url(response.user_id, response.event_name)
        rsvp_link_msg = f"\n🔗 **RSVP Page / QR Code:** {rsvp_url}" if rsvp_url else ""
        rsvp_link_msg_jp = f"\n🔗 **RSVPページ / QRコード:** {rsvp_url}" if rsvp_url else ""

        # 1. Create the confirmation message string
        drinks_msg = f"\n🍺 Drinks: {', '.join(response.drinks)}" if response.drinks else ""
        drinks_msg_jp = f"\n🍺 飲み物: {', '.join(response.drinks)}" if response.drinks else ""
        confirmation_message = (
            f"✅ Attendance confirmed for **{self.event.event_name}**!\n"
            f"👤 Name recorded: {recorded_name}\n"
            f"👥 Bringing: {response.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}"
            f"{rsvp_link_msg}\n\n"
            f"✅ 参加確定: **{self.event.event_name}**\n"
            f"👤 登録名: {recorded_name}\n"
            f"👥 同伴者: {response.extra_people}名\n"
            f"✔ 行動確認済み\n"
            f"✔ 到着確認済み"
            f"{drinks_msg_jp}"
            f"{rsvp_link_msg_jp}\n\n"
            f"⚠️ **Important:** Withdrawing after the deadline is strongly discouraged. "
            f"If you withdraw late, you are fully responsible for any consequences, including "
            f"payment requests from the event organizer and potential server moderation action.\n\n"
            f"⚠️ **重要:** 締め切り後の辞退は強くお勧めしません。"
            f"遅れて辞退した場合、主催者からの支払い請求やサーバーのモデレーション措置を含む"
            f"すべての結果に対して、全責任を負います。"
        )

        # 2. Attempt to DM the user first
        try:
            await interaction.user.send(confirmation_message)
            # If DM succeeds, send a brief confirmation to the channel
            await interaction.response.send_message(
                f"✅ Your attendance is confirmed as **{recorded_name}**! I've sent you a DM with the details.",
                ephemeral=True,
            )
        except (discord.Forbidden, discord.HTTPException):
            # If DM fails, fall back to sending an ephemeral message in the channel
            await interaction.response.send_message(confirmation_message, ephemeral=True)

        # 3. Update rank and announce milestones regardless of whether the DM succeeded
        update_rank(interaction.user.id, interaction.user.name)
        rank = get_rank(interaction.user.id, interaction.user.name)
        if (
            rank in MILESTONE_MESSAGES
            and can_rank_message_sent(interaction.user.id)
            and isinstance(interaction.channel, discord.abc.Messageable)
        ):
            try:
                msg_template = random.choice(MILESTONE_MESSAGES[rank])
                # Milestone messages congratulate the user by mention; opt in to
                # user pings past the client-wide AllowedMentions.none() default.
                await interaction.channel.send(
                    msg_template.format(user_id=interaction.user.id),
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                mark_achieved_rank(interaction.user.id)
            except discord.HTTPException as e:
                _log.error(
                    "Failed to send milestone message for user %s in channel %s: %s",
                    interaction.user.id,
                    interaction.channel_id,
                    e,
                )

        # 4. Add user to the thread
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.add_user(interaction.user)
            else:
                _log.warning(
                    "Could not add user %s to thread %s (not a thread?).",
                    interaction.user.id,
                    interaction.channel_id,
                )
        except discord.HTTPException as e:
            _log.error("Failed to add user %s to thread %s: %s", interaction.user.id, interaction.channel_id, e)

        # 5. Assign event participant role
        if self.event.role_id and interaction.guild:
            await assign_event_role(interaction.guild, interaction.user.id, self.event.role_id)

    async def _handle_waitlist_submission(self, interaction: discord.Interaction, entry: WaitlistEntry):
        """Handles actions after a user is added to the waitlist."""
        recorded_name = get_effective_display_name(entry)
        # 1. Create the waitlist confirmation message
        drinks_msg = f"\n🍺 Drinks: {', '.join(entry.drinks)}" if entry.drinks else ""
        drinks_msg_jp = f"\n🍺 飲み物: {', '.join(entry.drinks)}" if entry.drinks else ""
        waitlist_message = (
            f"📋 You've been added to the waitlist for **{self.event.event_name}**!\n"
            f"👤 Name recorded: {recorded_name}\n"
            f"👥 Bringing: {entry.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}\n\n"
            f"📋 **{self.event.event_name}**のウェイトリストに追加されました！\n"
            f"👤 登録名: {recorded_name}\n"
            f"👥 同伴者: {entry.extra_people}名\n"
            f"✔ 行動確認済み\n"
            f"✔ 到着確認済み"
            f"{drinks_msg_jp}\n\n"
            f"You will be automatically added to the event if a spot opens up.\n"
            f"空きが出た場合、自動的にイベントに追加されます。\n\n"
            f"⚠️ **Important:** Withdrawing after the deadline is strongly discouraged. "
            f"If you withdraw late, you are fully responsible for any consequences, including "
            f"payment requests from the event organizer and potential server moderation action.\n\n"
            f"⚠️ **重要:** 締め切り後の辞退は強くお勧めしません。"
            f"遅れて辞退した場合、主催者からの支払い請求やサーバーのモデレーション措置を含む"
            f"すべての結果に対して、全責任を負います。\n\n"
            f"💰 **Note:** If no one drops out and you are still allowed to join the offkai, "
            f"you may be charged extra by the organizers.\n"
            f"💰 **注意:** 誰もキャンセルせず、それでもオフ会への参加が認められた場合、"
            f"主催者から追加料金が請求される場合があります。"
        )

        # 2. Attempt to DM the user first
        try:
            await interaction.user.send(waitlist_message)
            # If DM succeeds, send a brief confirmation to the channel
            await interaction.response.send_message(
                f"📋 You've been added to the waitlist as **{recorded_name}**! I've sent you a DM with the details.",
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
                    "Could not add user %s to thread %s (not a thread?).",
                    interaction.user.id,
                    interaction.channel_id,
                )
        except discord.HTTPException as e:
            _log.error("Failed to add user %s to thread %s: %s", interaction.user.id, interaction.channel_id, e)

    async def _handle_waitlist_capacity_exceeded(
        self, interaction: discord.Interaction, entry: WaitlistEntry, total_people_in_group: int, remaining_spots: int
    ):
        """Handles actions when a user's group exceeds capacity and is added to waitlist."""
        recorded_name = get_effective_display_name(entry)
        # 1. Create the capacity exceeded + waitlist message
        drinks_msg = f"\n🍺 Drinks: {', '.join(entry.drinks)}" if entry.drinks else ""
        drinks_msg_jp = f"\n🍺 飲み物: {', '.join(entry.drinks)}" if entry.drinks else ""
        waitlist_message = (
            f"❌ Sorry, your group of {total_people_in_group} people would exceed the capacity "
            f"for **{self.event.event_name}**.\n"
            f"Only {remaining_spots} spot(s) remaining out of {self.event.max_capacity} total.\n\n"
            f"📋 For now you will be added to the waiting list.\n"
            f"👤 Name recorded: {recorded_name}\n"
            f"👥 Bringing: {entry.extra_people} extra guest(s)\n"
            f"✔ Behavior Confirmed\n"
            f"✔ Arrival Confirmed"
            f"{drinks_msg}\n\n"
            f"❌ 申し訳ありませんが、{total_people_in_group}名のグループは"
            f"**{self.event.event_name}**の定員を超えてしまいます。\n"
            f"定員{self.event.max_capacity}名中、残り{remaining_spots}名分です。\n\n"
            f"📋 現在ウェイトリストに追加されています。\n"
            f"👤 登録名: {recorded_name}\n"
            f"👥 同伴者: {entry.extra_people}名\n"
            f"✔ 行動確認済み\n"
            f"✔ 到着確認済み"
            f"{drinks_msg_jp}\n\n"
            f"You can choose to leave the offkai and re-apply with fewer people, "
            f"or stay on the waitlist and be automatically added if a spot opens up.\n"
            f"人数を減らして再申請するか、ウェイトリストに残って空きが出た場合に"
            f"自動的に追加されるのをお待ちいただけます。\n\n"
            f"💰 **Note:** If no one drops out and you are still allowed to join the offkai, "
            f"you may be charged extra by the organizers.\n"
            f"💰 **注意:** 誰もキャンセルせず、それでもオフ会への参加が認められた場合、"
            f"主催者から追加料金が請求される場合があります。"
        )

        # 2. Attempt to DM the user first
        try:
            await interaction.user.send(waitlist_message)
            # If DM succeeds, send a brief confirmation to the channel
            await interaction.response.send_message(
                "📋 Your group exceeds capacity. You've been added to the waitlist! "
                f"Your name is recorded as **{recorded_name}**. I've sent you a DM with the details.",
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
                    "Could not add user %s to thread %s (not a thread?).",
                    interaction.user.id,
                    interaction.channel_id,
                )
        except discord.HTTPException as e:
            _log.error("Failed to add user %s to thread %s: %s", interaction.user.id, interaction.channel_id, e)

    async def _send_capacity_reached_message(self, interaction: discord.Interaction):
        """Sends a message to the thread when capacity is first reached."""
        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(
                    f"⚠️ **Maximum capacity has been reached for {self.event.event_name}!**\n"
                    f"New registrations will be added to the waitlist.\n\n"
                    f"⚠️ **{self.event.event_name}の定員に達しました！**\n"
                    f"新規登録はウェイトリストに追加されます。"
                )
                _log.info("Sent capacity reached message to thread for event '%s'.", self.event.event_name)
            else:
                _log.warning("Could not send capacity message to thread %s (not a thread?).", interaction.channel_id)
        except discord.HTTPException as e:
            _log.error("Failed to send capacity message to thread %s: %s", interaction.channel_id, e)

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Get Input Values
        preferred_name_str = self.preferred_name_input.value
        extra_people_str = self.extra_people_input.value
        confirmation_str = self.confirmation_input.value
        drink_choice_str = self.drink_choice_input.value if self.drink_choice_input else "N/A"
        extra_names_str = self.extras_names_input.value

        try:
            # 2. Validate Inputs using Helpers (Raises ValidationError on failure)
            num_extra_people = self._validate_extra_people(extra_people_str)
            # Older callers may still replace the two compatibility aliases.
            # Prefer the combined field whenever it has a value.
            if not isinstance(confirmation_str, str) or not confirmation_str.strip():
                aliases_replaced = (
                    self.behave_checkbox_input is not self.confirmation_input
                    or self.arrival_checkbox_input is not self.confirmation_input
                )
                if aliases_replaced:
                    self._validate_confirmations(
                        self.behave_checkbox_input.value,
                        self.arrival_checkbox_input.value,
                    )
                else:
                    self._validate_confirmations(confirmation_str)
            else:
                self._validate_confirmations(confirmation_str)
            selected_drinks = self._validate_drinks(drink_choice_str, num_extra_people + 1)
            extra_people_names = self._validate_extra_people_names(extra_names_str, num_extra_people)

            # 3. Calculate total people in this registration
            total_people_in_group = 1 + num_extra_people
            username = interaction.user.name
            resolved_display_name = resolve_submitted_display_name(
                preferred_name_str,
                getattr(interaction.user, "display_name", ""),
                username,
            )

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
                    extras_names=extra_people_names,
                    display_name=resolved_display_name,
                )

                add_to_waitlist(self.event.event_name, new_entry)

                # Send waitlist confirmation
                await self._handle_waitlist_submission(interaction, new_entry)

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
                    extras_names=extra_people_names,
                    display_name=resolved_display_name,
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
                    extras_names=extra_people_names,
                    display_name=resolved_display_name,
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
            _log.info(
                "Rejected modal submission for event '%s' by user %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
            )
            await modal_error_message(interaction, self.event.event_name, str(e))
            # No return needed here, function ends after except block

        except DuplicateResponseError as e:
            await modal_error_message(interaction, self.event.event_name, str(e))

        except Exception as e:
            # Catch any other unexpected errors during Response creation or add_response
            _log.error("Unexpected error during modal submission for %s: %s", self.event.event_name, e, exc_info=True)
            await error_message(interaction, "An internal error occurred processing your response.")
            # No return needed here


class InterestCheckModal(ui.Modal):
    """Minimal modal for interest checks: just the group size, no commitments."""

    def __init__(
        self,
        *,
        event: Event,
        timeout=None,
    ):
        # Short "imodal_" prefix keeps the custom_id within Discord's 100-char
        # cap for names up to MAX_EVENT_NAME_LENGTH (see GatheringModal).
        super().__init__(
            title=_build_modal_title(event.event_name),
            timeout=timeout,
            custom_id=f"imodal_{event.event_name}",
        )
        self.event = event

        self.preferred_name_input: ui.TextInput = ui.TextInput(
            label="Name you'd like us to use",
            placeholder="Optional; leave blank to use your Discord display name",
            required=False,
            max_length=32,
            custom_id="preferred_name",
        )
        self.extra_people_input: ui.TextInput = ui.TextInput(
            label="🧑 Extra people you'd bring (0-5)",
            placeholder="Enter a number between 0-5",
            required=True,
            max_length=1,
            custom_id="interest_extra_people",
        )
        self.add_item(self.preferred_name_input)
        self.add_item(self.extra_people_input)

    @property
    def event_name(self) -> str:
        return self.event.event_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # The modal can remain open in a user's client after the interest
            # check has been closed, so re-check its state at submission time.
            if not self.event.open or self.event.is_past_deadline:
                await error_message(interaction, "This interest check is no longer accepting responses.")
                return

            num_extra_people = validate_extra_people_input(self.extra_people_input.value)
            resolved_display_name = resolve_submitted_display_name(
                self.preferred_name_input.value,
                getattr(interaction.user, "display_name", ""),
                interaction.user.name,
            )

            new_response = Response(
                user_id=interaction.user.id,
                username=interaction.user.name,
                extra_people=num_extra_people,
                behavior_confirmed=False,
                arrival_confirmed=False,
                event_name=self.event.event_name,
                timestamp=datetime.now(UTC),
                drinks=[],
                extras_names=[],
                display_name=resolved_display_name,
            )
            add_response(self.event.event_name, new_response)

            # Interest is non-binding: no DM, no rank/milestone update, no role.
            group_size = 1 + num_extra_people
            await interaction.response.send_message(
                f"🙋 Thanks! You're counted as interested in **{self.event.event_name}** "
                f"as **{resolved_display_name}** "
                f"({group_size} {'person' if group_size == 1 else 'people'}).\n"
                f"🙋 ありがとうございます！**{self.event.event_name}**に"
                f"{resolved_display_name}さんとして"
                f"興味あり（{group_size}名）として記録されました。",
                ephemeral=True,
            )

            # Add user to the thread so they can be reached for follow-ups.
            try:
                if interaction.channel and isinstance(interaction.channel, discord.Thread):
                    await interaction.channel.add_user(interaction.user)
                else:
                    _log.warning(
                        "Could not add user %s to thread %s (not a thread?).",
                        interaction.user.id,
                        interaction.channel_id,
                    )
            except discord.HTTPException as e:
                _log.error("Failed to add user %s to thread %s: %s", interaction.user.id, interaction.channel_id, e)

            await _refresh_interest_check_message(interaction.client, self.event)

        except ValidationError as e:
            await error_message(interaction, str(e))

        except DuplicateResponseError as e:
            # The error message already carries the ❌ prefix.
            await interaction.response.send_message(str(e), ephemeral=True)

        except Exception as e:
            _log.error(
                "Unexpected error during interest check submission for %s: %s",
                self.event.event_name,
                e,
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred processing your response.")


async def _refresh_interest_check_message(client: discord.Client, event: Event) -> None:
    """Re-renders the interest check announcement so the live count stays current."""
    # Imported locally: event_actions imports this module at import time.
    from offkai_bot.event_actions import update_event_message

    try:
        await update_event_message(client, event)
    except Exception as e:
        # The response is already recorded; a stale count is not worth failing the interaction.
        _log.error("Failed to refresh interest check message for '%s': %s", event.event_name, e, exc_info=True)


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
        freed_spots = 0
        try:
            # Try to remove from responses first
            removed_response = remove_response(self.event.event_name, interaction.user.id)
            decrease_rank(interaction.user.id, interaction.user.name)
            removed_from_responses = True
            freed_spots = 1 + removed_response.extra_people

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
                "Unexpected error during withdrawal for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred while processing your withdrawal.")
            return

        # --- Success Path (user was removed from either responses or waitlist) ---
        try:
            # 1. Create the withdrawal message string
            withdrawal_message = (
                f"👋 Your attendance for **{self.event.event_name}** has been withdrawn.\n"
                f"👋 **{self.event.event_name}**への参加が取り消されました。"
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
                        "Could not remove user %s from channel %s (not a thread?).",
                        interaction.user.id,
                        interaction.channel_id,
                    )
            except discord.HTTPException as e:
                _log.error(
                    "Failed to remove user %s from thread %s: %s",
                    interaction.user.id,
                    interaction.channel_id,
                    e,
                )

            # 5. Remove event participant role if removed from responses
            if removed_from_responses and self.event.role_id and interaction.guild:
                await remove_event_role(interaction.guild, interaction.user.id, self.event.role_id)

            # 6. Promote users from the waitlist only if removed from responses
            # (not from waitlist, since that doesn't free up capacity)
            if removed_from_responses:
                await promote_waitlist_batch(self.event, interaction.client, freed_spots=freed_spots)

        except Exception as e:
            # Catch any errors during notification/promotion
            _log.error(
                "Error during post-withdrawal actions for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
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
        freed_spots = 0
        try:
            # Try to remove from responses first
            removed_response = remove_response(self.event.event_name, interaction.user.id)
            decrease_rank(interaction.user.id, interaction.user.name)
            removed_from_responses = True
            freed_spots = 1 + removed_response.extra_people

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
                "Unexpected error during withdrawal for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
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
                f"Failure to comply may result in server moderation action.\n\n"
                f"👋 **{self.event.event_name}**への参加が取り消されました。\n\n"
                f"⚠️ **重要:** 締め切り後の辞退はご自身の全責任となります。"
                f"主催者から支払いについて連絡が来る場合があります。"
                f"従わない場合、サーバーのモデレーション措置が取られる可能性があります。"
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
                        "Could not remove user %s from channel %s (not a thread?).",
                        interaction.user.id,
                        interaction.channel_id,
                    )
            except discord.HTTPException as e:
                _log.error(
                    "Failed to remove user %s from thread %s: %s",
                    interaction.user.id,
                    interaction.channel_id,
                    e,
                )

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
                        "Notified creator %s about withdrawal by %s from closed event '%s'.",
                        self.event.creator_id,
                        interaction.user.id,
                        self.event.event_name,
                    )
                except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                    _log.warning(
                        "Could not notify creator %s about withdrawal from event '%s': %s",
                        self.event.creator_id,
                        self.event.event_name,
                        e,
                    )

            # 5. Remove event participant role if removed from responses
            if removed_from_responses and self.event.role_id and interaction.guild:
                await remove_event_role(interaction.guild, interaction.user.id, self.event.role_id)

            # 6. Promote users from the waitlist only if removed from responses
            # (not from waitlist, since that doesn't free up capacity)
            if removed_from_responses:
                await promote_waitlist_batch(self.event, interaction.client, freed_spots=freed_spots)

        except Exception as e:
            # Catch any errors during notification/promotion
            _log.error(
                "Error during post-withdrawal actions for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
                exc_info=True,
            )


class InterestCheckEvent(EventView):
    """View for open interest checks: non-binding register/withdraw only."""

    def __init__(self, event: Event):
        super().__init__(event=event)

    @discord.ui.button(
        label="🙋 I'm interested",
        style=discord.ButtonStyle.success,
        row=0,
        custom_id="interest_button",
    )
    async def register_interest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(InterestCheckModal(event=self.event))

    @discord.ui.button(
        label="Withdraw interest",
        style=discord.ButtonStyle.danger,
        row=1,
        custom_id="interest_withdraw_button",
    )
    async def withdraw_interest(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            remove_response(self.event.event_name, interaction.user.id)
        except ResponseNotFoundError:
            await error_message(
                interaction,
                f"You have not registered interest in **{self.event.event_name}**.",
            )
            return
        except Exception as e:
            _log.error(
                "Unexpected error during interest withdrawal for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
                exc_info=True,
            )
            await error_message(interaction, "An internal error occurred while processing your withdrawal.")
            return

        # Interest is non-binding: no warning DMs, no rank change, no waitlist promotion.
        await interaction.response.send_message(
            f"👋 Your interest in **{self.event.event_name}** has been withdrawn.\n"
            f"👋 **{self.event.event_name}**への興味ありが取り消されました。",
            ephemeral=True,
        )

        try:
            if interaction.channel and isinstance(interaction.channel, discord.Thread):
                await interaction.channel.remove_user(interaction.user)
        except discord.HTTPException as e:
            _log.error(
                "Failed to remove user %s from thread %s: %s",
                interaction.user.id,
                interaction.channel_id,
                e,
            )

        await _refresh_interest_check_message(interaction.client, self.event)


class InterestCheckClosedEvent(EventView):
    """View for closed interest checks: the tally is a snapshot, no more input."""

    def __init__(self, event: Event):
        super().__init__(event=event)

    @discord.ui.button(
        label="Interest check closed",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        row=0,
        custom_id="interest_closed_button",
    )
    async def closed(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This button is disabled, so this callback shouldn't trigger
        await interaction.response.send_message("This interest check is closed.", ephemeral=True)


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
        freed_spots = 0
        try:
            # Try to remove from responses first
            removed_response = remove_response(self.event.event_name, interaction.user.id)
            decrease_rank(interaction.user.id, interaction.user.name)
            removed_from_responses = True
            freed_spots = 1 + removed_response.extra_people

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
                "Unexpected error during withdrawal for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
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
                f"Failure to comply may result in server moderation action.\n\n"
                f"👋 **{self.event.event_name}**への参加が取り消されました。\n\n"
                f"⚠️ **重要:** 締め切り後の辞退はご自身の全責任となります。"
                f"主催者から支払いについて連絡が来る場合があります。"
                f"従わない場合、サーバーのモデレーション措置が取られる可能性があります。"
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
                        "Could not remove user %s from channel %s (not a thread?).",
                        interaction.user.id,
                        interaction.channel_id,
                    )
            except discord.HTTPException as e:
                _log.error(
                    "Failed to remove user %s from thread %s: %s",
                    interaction.user.id,
                    interaction.channel_id,
                    e,
                )

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
                        "Notified creator %s about withdrawal by %s from post-deadline event '%s'.",
                        self.event.creator_id,
                        interaction.user.id,
                        self.event.event_name,
                    )
                except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                    _log.warning(
                        "Could not notify creator %s about withdrawal from event '%s': %s",
                        self.event.creator_id,
                        self.event.event_name,
                        e,
                    )

            # 5. Remove event participant role if removed from responses
            if removed_from_responses and self.event.role_id and interaction.guild:
                await remove_event_role(interaction.guild, interaction.user.id, self.event.role_id)

            # 6. Promote users from the waitlist only if removed from responses
            # (not from waitlist, since that doesn't free up capacity)
            if removed_from_responses:
                await promote_waitlist_batch(self.event, interaction.client, freed_spots=freed_spots)

        except Exception as e:
            # Catch any errors during notification/promotion
            _log.error(
                "Error during post-withdrawal actions for %s by %s: %s",
                self.event.event_name,
                interaction.user.id,
                e,
                exc_info=True,
            )
