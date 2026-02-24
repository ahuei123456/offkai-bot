import logging

import discord

_log = logging.getLogger(__name__)

STRIP_SUFFIXES = ("-meetups", "-meetup")


def generate_role_name(channel_name: str) -> str:
    """Derive role name from parent channel name.

    'liella-7l-meetups' -> 'liella-7l-offkai-participant'
    'summer-events'     -> 'summer-events-offkai-participant'
    """
    name = channel_name
    for suffix in STRIP_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return f"{name}-offkai-participant"


async def create_event_role(guild: discord.Guild, channel_name: str) -> discord.Role:
    """Create a mentionable Discord role for event participants."""
    role_name = generate_role_name(channel_name)
    role = await guild.create_role(
        name=role_name,
        mentionable=True,
        reason=f"Offkai participant role for '{channel_name}'",
    )
    return role


async def assign_event_role(guild: discord.Guild, user_id: int, role_id: int) -> None:
    """Assign the event participant role to a user."""
    role = guild.get_role(role_id)
    if not role:
        _log.warning(f"Role {role_id} not found in guild {guild.id}, skipping assignment.")
        return
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if role not in member.roles:
            await member.add_roles(role, reason="Offkai attendance confirmed")
    except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        _log.warning(f"Failed to assign role {role_id} to user {user_id}: {e}")


async def remove_event_role(guild: discord.Guild, user_id: int, role_id: int) -> None:
    """Remove the event participant role from a user."""
    role = guild.get_role(role_id)
    if not role:
        _log.warning(f"Role {role_id} not found in guild {guild.id}, skipping removal.")
        return
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if role in member.roles:
            await member.remove_roles(role, reason="Offkai attendance withdrawn")
    except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        _log.warning(f"Failed to remove role {role_id} from user {user_id}: {e}")
