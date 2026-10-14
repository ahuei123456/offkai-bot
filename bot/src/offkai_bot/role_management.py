import asyncio
import logging
import secrets
from weakref import WeakValueDictionary

import discord

from offkai_bot.data.event import Event
from offkai_bot.data.response import get_responses

_log = logging.getLogger(__name__)

STRIP_SUFFIXES = ("-meetups", "-meetup")
_role_locks: WeakValueDictionary[tuple[int, int, int], asyncio.Lock] = WeakValueDictionary()


async def _sync_registered_role(guild: discord.Guild, user_id: int, role_id: int, event: Event) -> None:
    """Serialize role work and reconcile changes made while a Discord request was in flight."""
    key = guild.id, user_id, role_id
    lock = _role_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _role_locks[key] = lock
    async with lock:
        role = guild.get_role(role_id)
        if role is None:
            return
        try:
            # Gateway role caches can lag behind a preceding add/remove request.
            member = await guild.fetch_member(user_id)
            has_role = role in member.roles
            while True:
                wanted = not event.archived and any(r.user_id == user_id for r in get_responses(event.event_name))
                if has_role == wanted:
                    return
                if wanted:
                    await member.add_roles(role, reason="Offkai attendance confirmed")
                else:
                    await member.remove_roles(role, reason="Offkai attendance no longer confirmed")
                has_role = wanted
                # Re-read saved attendance after the network request, including re-registration.
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            _log.exception("Could not reconcile participant role for user %s in event %r", user_id, event.event_name)


def generate_role_name(channel_name: str) -> str:
    """Derive role name from parent channel name with a random suffix for uniqueness.

    'liella-7l-meetups' -> 'liella-7l-offkai-participant-a3f2'
    'summer-events'     -> 'summer-events-offkai-participant-b1c4'
    """
    name = channel_name
    for suffix in STRIP_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return f"{name}-offkai-participant-{secrets.token_hex(2)}"


async def create_event_role(guild: discord.Guild, channel_name: str) -> discord.Role:
    """Create a mentionable Discord role for event participants."""
    role_name = generate_role_name(channel_name)
    role = await guild.create_role(
        name=role_name,
        mentionable=True,
        reason=f"Offkai participant role for '{channel_name}'",
    )
    return role


async def assign_event_role(guild: discord.Guild, user_id: int, role_id: int, *, event: Event | None = None) -> None:
    """Assign the event participant role to a user."""
    if event is not None:
        await _sync_registered_role(guild, user_id, role_id, event)
        return
    role = guild.get_role(role_id)
    if not role:
        _log.warning("Role %s not found in guild %s, skipping assignment.", role_id, guild.id)
        return
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if role not in member.roles:
            await member.add_roles(role, reason="Offkai attendance confirmed")
    except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        _log.warning("Failed to assign role %s to user %s: %s", role_id, user_id, e)


async def remove_event_role(guild: discord.Guild, user_id: int, role_id: int, *, event: Event | None = None) -> None:
    """Remove the event participant role from a user."""
    if event is not None:
        await _sync_registered_role(guild, user_id, role_id, event)
        return
    role = guild.get_role(role_id)
    if not role:
        _log.warning("Role %s not found in guild %s, skipping removal.", role_id, guild.id)
        return
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if role in member.roles:
            await member.remove_roles(role, reason="Offkai attendance withdrawn")
    except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        _log.warning("Failed to remove role %s from user %s: %s", role_id, user_id, e)
