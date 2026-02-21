import contextlib
import logging

import discord
from discord import app_commands
from discord.ext import commands

from offkai_bot.data.event import (
    add_event,
    archive_event,
    get_event,
    load_event_data,
    save_event_data,
    set_event_open_status,
    update_event_details,
)
from offkai_bot.data.response import (
    Response,
    add_response,
    calculate_attendance,
    calculate_drinks,
    calculate_waitlist,
    get_waitlist,
    promote_specific_from_waitlist,
    remove_response,
)
from offkai_bot.errors import (
    BroadcastPermissionError,
    BroadcastSendError,
    DuplicateEventError,
    EventNotFoundError,
    InvalidChannelTypeError,
    MissingChannelIDError,
    PinPermissionError,
    ThreadAccessError,
    ThreadCreationError,
    ThreadNotFoundError,
)
from offkai_bot.event_actions import (
    fetch_thread_for_event,
    perform_close_event,
    register_deadline_reminders,
    send_event_message,
    update_event_message,
)
from offkai_bot.util import (
    log_command_usage,
    parse_drinks,
    parse_event_datetime,
    validate_event_datetime,
    validate_event_deadline,
    validate_interaction_context,
)

_log = logging.getLogger(__name__)


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="create_offkai",
        description="Create a new offkai in the current channel.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
        venue="The offkai venue.",
        address="The address of the offkai venue.",
        google_maps_link="A link to the venue on Google Maps.",
        date_time="The date and time of the event (YYYY-MM-DD HH:MM). Assumed JST.",
        deadline="The date and time of the deadline to sign up (YYYY-MM-DD HH:MM). Assumed JST.",
        drinks="Optional: Comma-separated list of allowed drinks.",
        announce_msg="Optional: A message to post in the main channel.",
        max_capacity="Optional: Maximum number of attendees (including +1s). Leave empty for unlimited.",
        ping_role="Optional: A role to ping in deadline reminders (filtered to roles containing 'meetups').",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def create_offkai(
        self,
        interaction: discord.Interaction,
        event_name: str,
        venue: str,
        address: str,
        google_maps_link: str,
        date_time: str,
        deadline: str | None = None,
        drinks: str | None = None,
        announce_msg: str | None = None,
        max_capacity: int | None = None,
        ping_role: str | None = None,
    ):
        # 1. Business Logic Validation
        with contextlib.suppress(EventNotFoundError):
            if get_event(event_name):
                raise DuplicateEventError(event_name)

        # 2. Input Parsing/Transformation
        event_datetime = parse_event_datetime(date_time)
        event_deadline = parse_event_datetime(deadline) if deadline else None
        drinks_list = parse_drinks(drinks)

        ping_role_id: int | None = None
        if ping_role is not None:
            try:
                ping_role_id = int(ping_role)
            except ValueError:
                _log.warning(f"Invalid ping_role value '{ping_role}', ignoring.")

        # 3. Context Validation
        validate_interaction_context(interaction)
        validate_event_datetime(event_datetime)
        validate_event_deadline(event_datetime, event_deadline)

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

        # Call the new function in the data layer
        # Note: We use self.bot instead of client if needed, but functions often take client.
        # register_deadline_reminders takes 'client'.
        new_event = add_event(
            event_name=event_name,
            venue=venue,
            address=address,
            google_maps_link=google_maps_link,
            event_datetime=event_datetime,
            event_deadline=event_deadline,
            channel_id=interaction.channel.id,
            thread_id=thread.id,
            drinks_list=drinks_list,
            announce_msg=announce_msg,
            max_capacity=max_capacity,
            creator_id=interaction.user.id,
            ping_role_id=ping_role_id,
        )

        register_deadline_reminders(self.bot, new_event, thread)

        # 6. Further Discord Interaction
        await send_event_message(thread, new_event)  # Handles saving after message send

        # 7. User Feedback
        announce_text = f"# Offkai Created: {event_name}\n\n"
        if announce_msg:
            announce_text += f"{announce_msg}\n\n"
        announce_text += f"Join the discussion and RSVP here: {thread.mention}"
        await interaction.response.send_message(announce_text)

        message = await interaction.original_response()
        try:
            await message.pin()
        except discord.Forbidden as e:
            if message:
                _log.warning("Failed to pin message: Missing 'Pins' permission.")
                raise PinPermissionError(message.channel, e) from e
        except discord.HTTPException as e:
            _log.error(f"Failed to pin message due to HTTP error: {e}")

    @app_commands.command(
        name="modify_offkai",
        description="Modifies an existing offkai event.",
    )
    @app_commands.describe(
        event_name="The name of the event to modify.",
        venue="Optional: The new venue.",
        address="Optional: The new address.",
        google_maps_link="Optional: The new Google Maps link.",
        date_time="Optional: The new date and time (YYYY-MM-DD HH:MM).",
        deadline="Optional: The new registration deadline (YYYY-MM-DD HH:MM).",
        drinks="Optional: New comma-separated list of allowed drinks. Overwrites existing.",
        max_capacity="Optional: The new maximum capacity for the event.",
        update_msg="Message to post in the event thread announcing the update.",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def modify_offkai(
        self,
        interaction: discord.Interaction,
        event_name: str,
        update_msg: str,
        venue: str | None = None,
        address: str | None = None,
        google_maps_link: str | None = None,
        date_time: str | None = None,
        deadline: str | None = None,
        drinks: str | None = None,
        max_capacity: int | None = None,
    ):
        validate_interaction_context(interaction)

        old_event = get_event(event_name)
        old_capacity = old_event.max_capacity

        modified_event = update_event_details(
            event_name=event_name,
            venue=venue,
            address=address,
            google_maps_link=google_maps_link,
            date_time_str=date_time,
            deadline_str=deadline,
            drinks_str=drinks,
            max_capacity=max_capacity,
        )

        if modified_event.channel_id is None:
            assert isinstance(interaction.channel, discord.TextChannel)
            current_channel_id = interaction.channel.id
            modified_event.channel_id = current_channel_id
            _log.info(
                f"Assigned current channel ID ({current_channel_id}) "
                f"to event '{modified_event.event_name}' as it was missing."
            )

        save_event_data()

        capacity_increased = False
        if max_capacity is not None and (old_capacity is None or max_capacity > old_capacity):
            capacity_increased = True

        if capacity_increased:
            from offkai_bot.interactions import promote_waitlist_batch

            promoted_user_ids = await promote_waitlist_batch(modified_event, self.bot)
            if promoted_user_ids:
                from offkai_bot.data.response import save_responses

                save_responses()
                _log.info(
                    f"Promoted {len(promoted_user_ids)} user(s) from waitlist "
                    f"after capacity increase for event '{event_name}'."
                )

        await update_event_message(self.bot, modified_event)

        try:
            thread = await fetch_thread_for_event(self.bot, modified_event)
            try:
                await thread.send(f"**Event Updated:**\n{update_msg}")
            except discord.HTTPException as e:
                _log.warning(f"Could not send update message to thread {thread.id} for event '{event_name}': {e}")

        except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"Could not send update message for event '{event_name}': {e}")
        except Exception as e:
            _log.exception(f"Unexpected error sending update message for event '{event_name}': {e}")

        await interaction.response.send_message(
            f"✅ Event '{event_name}' modified successfully. Announcement posted in thread (if possible)."
        )

    @app_commands.command(
        name="close_offkai",
        description="Close responses for an offkai.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
        close_msg="Optional: Message for the event thread.",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def close_offkai(self, interaction: discord.Interaction, event_name: str, close_msg: str | None = None):
        try:
            await perform_close_event(self.bot, event_name, close_msg)
            await interaction.response.send_message(f"✅ Responses for '{event_name}' have been closed.")
        except Exception as e:
            _log.error(f"Error during /close_offkai command for '{event_name}': {e}", exc_info=e)
            raise e

    @app_commands.command(
        name="reopen_offkai",
        description="Reopen responses for an offkai.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
        reopen_msg="Optional: Message for the event thread.",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def reopen_offkai(self, interaction: discord.Interaction, event_name: str, reopen_msg: str | None = None):
        reopened_event = set_event_open_status(event_name, target_open_status=True)
        save_event_data()
        await update_event_message(self.bot, reopened_event)

        if reopen_msg:
            try:
                thread = await fetch_thread_for_event(self.bot, reopened_event)
                try:
                    await thread.send(f"**Responses Reopened:**\n{reopen_msg}")
                except discord.HTTPException as e:
                    _log.warning(
                        f"Could not send reopening message to thread {thread.id} for event '{event_name}': {e}"
                    )
            except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
                log_level = getattr(e, "log_level", logging.WARNING)
                _log.log(log_level, f"Could not send reopening message for event '{event_name}': {e}")
            except Exception as e:
                _log.exception(f"Unexpected error sending reopening message for event '{event_name}': {e}")

        await interaction.response.send_message(f"✅ Responses for '{event_name}' have been reopened.")

    @app_commands.command(
        name="archive_offkai",
        description="Archive an offkai.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def archive_offkai(self, interaction: discord.Interaction, event_name: str):
        archived_event = archive_event(event_name)
        save_event_data()
        await update_event_message(self.bot, archived_event)

        try:
            thread = await fetch_thread_for_event(self.bot, archived_event)
            if not thread.archived:
                try:
                    await thread.edit(archived=True, locked=True)
                    _log.info(f"Archived thread {thread.id} for event '{event_name}'.")
                except discord.HTTPException as e:
                    _log.warning(f"Could not archive thread {thread.id}: {e}")
        except (MissingChannelIDError, ThreadNotFoundError, ThreadAccessError) as e:
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"Could not archive thread for event '{event_name}': {e}")
        except Exception as e:
            _log.exception(f"Unexpected error archiving thread for event '{event_name}': {e}")

        await interaction.response.send_message(f"✅ Event '{event_name}' has been archived.")

    @app_commands.command(
        name="broadcast",
        description="Sends a message to the offkai channel.",
    )
    @app_commands.describe(event_name="The name of the event.", message="Message to broadcast.")
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def broadcast(self, interaction: discord.Interaction, event_name: str, message: str):
        event = get_event(event_name)
        thread = await fetch_thread_for_event(self.bot, event)

        try:
            await thread.send(f"{message}")
            await interaction.response.send_message(f"📣 Sent broadcast to channel {thread.mention}.", ephemeral=True)
        except discord.Forbidden as e:
            raise BroadcastPermissionError(thread, e)
        except discord.HTTPException as e:
            raise BroadcastSendError(thread, e)

    @app_commands.command(
        name="delete_response",
        description="Deletes a specific user's response to an offkai.",
    )
    @app_commands.describe(event_name="The name of the event.", member="The member whose response to remove.")
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def delete_response(self, interaction: discord.Interaction, event_name: str, member: discord.Member):
        event = get_event(event_name)
        remove_response(event_name, member.id)

        await interaction.response.send_message(
            f"🚮 Deleted response from user {member.mention} for '{event_name}'.",
            ephemeral=True,
        )

        if event.thread_id:
            thread = self.bot.get_channel(event.thread_id)
            if isinstance(thread, discord.Thread):
                try:
                    await thread.remove_user(member)
                    _log.info(f"Removed user {member.id} from thread {thread.id} for event '{event_name}'.")
                except discord.HTTPException as e:
                    _log.error(f"Failed to remove user {member.id} from thread {thread.id}: {e}")
            else:
                _log.warning(f"Could not find thread {event.thread_id} to remove user for event '{event_name}'.")
        else:
            _log.warning(f"Event '{event_name}' is missing thread_id, cannot remove user from thread.")

    @app_commands.command(
        name="promote",
        description="Manually promote a user from the waitlist, bypassing capacity limits.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
        username="The waitlisted user to promote (select from autocomplete).",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def promote(self, interaction: discord.Interaction, event_name: str, username: str):
        event = get_event(event_name)

        try:
            user_id = int(username)
        except ValueError:
            await interaction.response.send_message(
                "Invalid user selection. Please use the autocomplete dropdown.", ephemeral=True
            )
            return

        promoted_entry = promote_specific_from_waitlist(event_name, user_id)

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
        add_response(event_name, promoted_response)

        await interaction.response.send_message(
            f"Promoted user <@{user_id}> from the waitlist for '{event_name}'.",
            ephemeral=True,
        )

        try:
            promoted_user = await self.bot.fetch_user(user_id)
            await promoted_user.send(
                f"Great news! You've been manually promoted from the waitlist "
                f"for **{event_name}**!\n"
                f"You are now a confirmed attendee.\n\n"
                f"朗報です！**{event_name}**のウェイトリストから手動で昇格されました！\n"
                f"参加が確定しました。\n\n"
                f"**Important:** Withdrawing after the deadline is strongly discouraged. "
                f"If you withdraw late, you are fully responsible for any consequences, including "
                f"payment requests from the event organizer and potential server moderation action.\n\n"
                f"**重要:** 締め切り後の辞退は強くお勧めしません。"
                f"遅れて辞退した場合、主催者からの支払い請求やサーバーのモデレーション措置を含む"
                f"すべての結果に対して、全責任を負います。"
            )
        except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            _log.warning(f"Could not DM promoted user {user_id} for event '{event_name}': {e}")

        await update_event_message(self.bot, event)

    @app_commands.command(
        name="attendance",
        description="Gets the list of attendees and count for an event.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
        sort="Whether to sort the attendance list. (default: False)",
        nicknames="Whether to show display names alongside usernames. (default: False)",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def attendance(
        self, interaction: discord.Interaction, event_name: str, sort: bool = False, nicknames: bool = False
    ):
        get_event(event_name)
        total_count, attendee_list = calculate_attendance(event_name, nicknames=nicknames)
        if sort:
            attendee_list.sort(key=str.lower)

        output = f"**Attendance for {event_name}**\n\n"
        output += f"Total Attendees: **{total_count}**\n\n"
        lines = [f"{i + 1}. {name}" for i, name in enumerate(attendee_list)]
        output += "\n".join(lines)

        if len(output) > 1900:
            output = output[:1900] + "\n... (list truncated)"

        await interaction.response.send_message(output, ephemeral=True)

    @app_commands.command(
        name="waitlist",
        description="Gets the list of waitlisted people and count for an event.",
    )
    @app_commands.describe(
        event_name="The name of the event.",
        sort="Whether to sort the waitlist. (default: False)",
        nicknames="Whether to show display names alongside usernames. (default: False)",
    )
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def waitlist(
        self, interaction: discord.Interaction, event_name: str, sort: bool = False, nicknames: bool = False
    ):
        get_event(event_name)
        total_count, waitlisted_list = calculate_waitlist(event_name, nicknames=nicknames)
        if sort:
            waitlisted_list.sort(key=str.lower)

        output = f"**Waitlist for {event_name}**\n\n"
        output += f"Total Waitlisted: **{total_count}**\n\n"
        lines = [f"{i + 1}. {name}" for i, name in enumerate(waitlisted_list)]
        output += "\n".join(lines)

        if len(output) > 1900:
            output = output[:1900] + "\n... (list truncated)"

        await interaction.response.send_message(output, ephemeral=True)

    @app_commands.command(
        name="drinks",
        description="Gets the list of drinks and count for an event, if any.",
    )
    @app_commands.describe(event_name="The name of the event.")
    @app_commands.checks.has_role("Offkai Organizer")
    @log_command_usage
    async def drinks(self, interaction: discord.Interaction, event_name: str):
        get_event(event_name)
        total_count, drinks_count = calculate_drinks(event_name)

        output = f"**Drinks for {event_name}**\n\n"
        output += f"Total Drinks: **{total_count}**\n\n"

        lines = []
        if total_count > 0:
            lines.append("**Drinks:**")
            lines.extend(f"{drink}: {count}" for drink, count in drinks_count.items())

        output += "\n".join(lines)

        if len(output) > 1900:
            output = output[:1900] + "\n... (list truncated)"

        await interaction.response.send_message(output, ephemeral=True)

    # --- Autocomplete Functions ---
    async def event_autocomplete_base(
        self, interaction: discord.Interaction, current: str, *, open_status: bool | None = None
    ) -> list[app_commands.Choice[str]]:
        events = load_event_data()
        choices = []
        for event in events:
            if event.archived:
                continue
            if open_status is not None and event.open != open_status:
                continue
            if current.lower() in event.event_name.lower():
                choices.append(app_commands.Choice(name=event.event_name, value=event.event_name))
        return choices[:25]

    async def offkai_autocomplete_active(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self.event_autocomplete_base(interaction, current, open_status=None)

    async def offkai_autocomplete_closed_only(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self.event_autocomplete_base(interaction, current, open_status=False)

    async def offkai_autocomplete_all_non_archived(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self.event_autocomplete_base(interaction, current, open_status=None)

    async def meetup_role_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []

        choices = []
        for role in interaction.guild.roles:
            if "meetups" not in role.name.lower():
                continue
            if current.lower() in role.name.lower():
                choices.append(app_commands.Choice(name=role.name, value=str(role.id)))
        return choices[:25]

    async def waitlist_user_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        event_name = getattr(interaction.namespace, "event_name", "")
        if not event_name:
            return []

        try:
            waitlist = get_waitlist(event_name)
        except Exception:
            return []

        choices = []
        for entry in waitlist:
            display = entry.display_name or entry.username
            label = f"{display} (@{entry.username})"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(entry.user_id)))
        return choices[:25]

    # Apply autocompletes
    create_offkai.autocomplete("ping_role")(meetup_role_autocomplete)
    modify_offkai.autocomplete("event_name")(offkai_autocomplete_active)
    close_offkai.autocomplete("event_name")(offkai_autocomplete_active)
    broadcast.autocomplete("event_name")(offkai_autocomplete_active)
    delete_response.autocomplete("event_name")(offkai_autocomplete_active)
    promote.autocomplete("event_name")(offkai_autocomplete_active)
    promote.autocomplete("username")(waitlist_user_autocomplete)
    attendance.autocomplete("event_name")(offkai_autocomplete_active)
    waitlist.autocomplete("event_name")(offkai_autocomplete_active)
    drinks.autocomplete("event_name")(offkai_autocomplete_active)

    reopen_offkai.autocomplete("event_name")(offkai_autocomplete_closed_only)
    archive_offkai.autocomplete("event_name")(offkai_autocomplete_all_non_archived)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
