from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.role_management import (
    assign_event_role,
    create_event_role,
    generate_role_name,
    remove_event_role,
)

pytestmark = pytest.mark.asyncio


# --- Tests for generate_role_name ---


def test_generate_role_name_strips_meetups_suffix():
    assert generate_role_name("liella-7l-meetups") == "liella-7l-offkai-participant"


def test_generate_role_name_strips_meetup_suffix():
    assert generate_role_name("liella-7l-meetup") == "liella-7l-offkai-participant"


def test_generate_role_name_no_suffix_to_strip():
    assert generate_role_name("summer-events") == "summer-events-offkai-participant"


def test_generate_role_name_only_strips_first_matching_suffix():
    assert generate_role_name("meetups-meetup") == "meetups-offkai-participant"


def test_generate_role_name_no_hyphen_prefix():
    """Channel name 'meetups' doesn't end with '-meetups', so no stripping."""
    assert generate_role_name("meetups") == "meetups-offkai-participant"


# --- Tests for create_event_role ---


async def test_create_event_role_success():
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.create_role = AsyncMock(return_value=mock_role)

    result = await create_event_role(guild, "liella-7l-meetups")

    assert result is mock_role
    guild.create_role.assert_awaited_once_with(
        name="liella-7l-offkai-participant",
        mentionable=True,
        reason="Offkai participant role for 'liella-7l-meetups'",
    )


# --- Tests for assign_event_role ---


async def test_assign_event_role_success():
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = []
    mock_member.add_roles = AsyncMock()
    guild.get_member.return_value = mock_member

    await assign_event_role(guild, 12345, 99999)

    guild.get_role.assert_called_once_with(99999)
    guild.get_member.assert_called_once_with(12345)
    mock_member.add_roles.assert_awaited_once_with(mock_role, reason="Offkai attendance confirmed")


async def test_assign_event_role_already_has_role():
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = [mock_role]
    mock_member.add_roles = AsyncMock()
    guild.get_member.return_value = mock_member

    await assign_event_role(guild, 12345, 99999)

    mock_member.add_roles.assert_not_awaited()


async def test_assign_event_role_role_not_found():
    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = None
    guild.id = 1

    await assign_event_role(guild, 12345, 99999)

    guild.get_member.assert_not_called()


async def test_assign_event_role_fetches_member_if_not_cached():
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role
    guild.get_member.return_value = None

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = []
    mock_member.add_roles = AsyncMock()
    guild.fetch_member = AsyncMock(return_value=mock_member)

    await assign_event_role(guild, 12345, 99999)

    guild.fetch_member.assert_awaited_once_with(12345)
    mock_member.add_roles.assert_awaited_once()


@patch("offkai_bot.role_management._log")
async def test_assign_event_role_handles_forbidden(mock_log):
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role
    guild.id = 1

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = []
    mock_member.add_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No perms"))
    guild.get_member.return_value = mock_member

    await assign_event_role(guild, 12345, 99999)

    mock_log.warning.assert_called_once()


# --- Tests for remove_event_role ---


async def test_remove_event_role_success():
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = [mock_role]
    mock_member.remove_roles = AsyncMock()
    guild.get_member.return_value = mock_member

    await remove_event_role(guild, 12345, 99999)

    guild.get_role.assert_called_once_with(99999)
    mock_member.remove_roles.assert_awaited_once_with(mock_role, reason="Offkai attendance withdrawn")


async def test_remove_event_role_doesnt_have_role():
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = []
    mock_member.remove_roles = AsyncMock()
    guild.get_member.return_value = mock_member

    await remove_event_role(guild, 12345, 99999)

    mock_member.remove_roles.assert_not_awaited()


async def test_remove_event_role_role_not_found():
    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = None
    guild.id = 1

    await remove_event_role(guild, 12345, 99999)

    guild.get_member.assert_not_called()


@patch("offkai_bot.role_management._log")
async def test_remove_event_role_handles_forbidden(mock_log):
    guild = MagicMock(spec=discord.Guild)
    mock_role = MagicMock(spec=discord.Role)
    guild.get_role.return_value = mock_role
    guild.id = 1

    mock_member = MagicMock(spec=discord.Member)
    mock_member.roles = [mock_role]
    mock_member.remove_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No perms"))
    guild.get_member.return_value = mock_member

    await remove_event_role(guild, 12345, 99999)

    mock_log.warning.assert_called_once()
