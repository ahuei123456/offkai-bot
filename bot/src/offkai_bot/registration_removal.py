"""Organizer removal shared by the Discord command and private admin interface."""

import logging
from datetime import UTC, datetime

import discord

from offkai_bot.data.event import Event
from offkai_bot.data.ranking import decrease_rank
from offkai_bot.data.response import get_responses, get_waitlist, remove_from_waitlist, remove_response
from offkai_bot.errors import RegistrationChangedError, ResponseNotFoundError
from offkai_bot.event_actions import update_event_message
from offkai_bot.interactions import promote_waitlist_batch
from offkai_bot.role_management import remove_event_role

_log = logging.getLogger(__name__)


async def remove_registration(
    client: discord.Client,
    event: Event,
    member: discord.Member | discord.User,
    guild: discord.Guild | None,
    *,
    allow_waitlist: bool = False,
    thread: discord.Thread | None = None,
    expected_timestamp: datetime | None = None,
) -> dict:
    """Persist removal first; report failed Discord cleanup without undoing it."""
    if expected_timestamp is not None:
        entries = get_responses(event.event_name) + get_waitlist(event.event_name)
        entry = next((entry for entry in entries if entry.user_id == member.id), None)
        if entry is None:
            raise ResponseNotFoundError(event.event_name, member.id)
        # The frontend displays ISO timestamps at millisecond precision.
        current = entry.timestamp.replace(tzinfo=UTC) if entry.timestamp.tzinfo is None else entry.timestamp
        current = current.astimezone(UTC)
        expected = expected_timestamp.astimezone(UTC)
        if current.replace(microsecond=current.microsecond // 1000 * 1000) != expected:
            raise RegistrationChangedError()
    # No await between the identity check and the persisted removal.
    warnings = []
    freed_spots = 0
    try:
        response = remove_response(event.event_name, member.id)
        freed_spots = 1 + response.extra_people
    except ResponseNotFoundError:
        if not allow_waitlist:
            raise
        remove_from_waitlist(event.event_name, member.id)

    if freed_spots and not event.interest_check:
        decrease_rank(member.id, member.name)

    if freed_spots and event.role_id and guild:
        try:
            await remove_event_role(guild, member.id, event.role_id)
        except Exception:
            _log.exception("Role removal failed for user %s in event %r", member.id, event.event_name)
            warnings.append("The registration was removed, but the participant role could not be removed.")

    promoted = []
    if freed_spots and not event.interest_check:
        try:
            promoted = await promote_waitlist_batch(event, client, freed_spots=freed_spots)
        except Exception as exc:
            _log.error(
                "Waitlist promotion failed after deleting response from user %s for event '%s': %s",
                member.id,
                event.event_name,
                exc,
                exc_info=True,
            )
            warnings.append("Waitlist promotion failed; check the logs and promote manually if needed.")

    if event.interest_check:
        try:
            await update_event_message(client, event)
        except Exception:
            _log.exception("Announcement update failed after removing registration")
            warnings.append("The registration was removed, but the announcement could not be updated.")

    if event.thread_id:
        channel = thread or client.get_channel(event.thread_id)
        if isinstance(channel, discord.Thread):
            try:
                await channel.remove_user(member)
                _log.info("Removed user %s from thread %s for event '%s'.", member.id, channel.id, event.event_name)
            except discord.HTTPException as exc:
                _log.error("Failed to remove user %s from thread %s: %s", member.id, channel.id, exc)
                warnings.append("The registration was removed, but the user could not be removed from the thread.")
        else:
            _log.warning("Could not find thread %s to remove user for event '%s'.", event.thread_id, event.event_name)
            warnings.append("The registration was removed, but the Discord thread was unavailable.")
    else:
        _log.warning("Event '%s' is missing thread_id, cannot remove user from thread.", event.event_name)
        warnings.append("The registration was removed, but the event has no Discord thread.")

    return {"removed": True, "freed_spots": freed_spots, "promoted": promoted, "warnings": warnings}
