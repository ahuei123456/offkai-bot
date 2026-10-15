"""Discord archive/permission failures must not lose saved signup membership work."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from aiohttp import ClientConnectionError

from offkai_bot.data import response as responses
from offkai_bot.interactions import SignupContext, _add_user_to_event_thread


@pytest.fixture(autouse=True)
def registered_user(sample_event_list):
    # Membership helpers operate only on a saved registration.
    responses.RESPONSE_DATA_CACHE = {
        event.event_name: {
            "attendees": [responses.Response(123, "Synthetic", 0, True, True, event.event_name, datetime.now(UTC))],
            "waitlist": [],
        }
        for event in sample_event_list
    }


def thread_mock(thread_id=1501, *, archived=False, locked=False):
    thread = MagicMock(spec=discord.Thread, id=thread_id, archived=archived, locked=locked)
    thread.add_user = AsyncMock()
    thread.edit = AsyncMock(return_value=thread)
    return thread


def http_error(code, *, status=400):
    return discord.HTTPException(MagicMock(status=status), {"code": code, "message": "Synthetic Discord error"})


@pytest.mark.parametrize("channel_type", [discord.DMChannel, discord.TextChannel, type(None)])
async def test_membership_uses_saved_event_thread_when_context_is_not_a_thread(sample_event_list, channel_type):
    event = sample_event_list[0]
    thread = thread_mock(event.thread_id)
    client = MagicMock(spec=discord.Client)
    client.get_channel.return_value = None
    client.fetch_channel = AsyncMock(return_value=thread)
    channel = None if channel_type is type(None) else MagicMock(spec=channel_type)
    user = discord.Object(id=123)

    await _add_user_to_event_thread(event, SignupContext(channel, None, user), client)

    client.fetch_channel.assert_awaited_once_with(event.thread_id)
    thread.add_user.assert_awaited_once_with(user)
    thread.edit.assert_not_awaited()


async def test_membership_does_not_join_another_events_thread(sample_event_list):
    event = sample_event_list[0]
    wrong_thread = thread_mock(999)
    event_thread = thread_mock(event.thread_id)
    client = MagicMock(spec=discord.Client)
    client.get_channel.return_value = event_thread
    user = discord.Object(id=123)

    await _add_user_to_event_thread(event, SignupContext(wrong_thread, None, user), client)

    wrong_thread.add_user.assert_not_awaited()
    event_thread.add_user.assert_awaited_once_with(user)


@pytest.mark.parametrize("locked", [False, True])
async def test_archived_error_refreshes_stale_gateway_state_once(sample_event_list, locked):
    event = sample_event_list[0]
    cached = thread_mock(event.thread_id)
    cached.add_user.side_effect = http_error(50083)
    refreshed = thread_mock(event.thread_id, archived=True, locked=locked)
    active = thread_mock(event.thread_id)
    refreshed.edit.return_value = active
    client = MagicMock(spec=discord.Client, fetch_channel=AsyncMock(return_value=refreshed))
    user = discord.Object(id=123)

    await _add_user_to_event_thread(event, SignupContext(cached, None, user), client)

    cached.add_user.assert_awaited_once_with(user)
    client.fetch_channel.assert_awaited_once_with(event.thread_id)
    if locked:
        refreshed.edit.assert_not_awaited()
        active.add_user.assert_not_awaited()
    else:
        refreshed.edit.assert_awaited_once_with(archived=False)
        active.add_user.assert_awaited_once_with(user)


@pytest.mark.parametrize("event_archived", [False, True])
async def test_membership_preserves_explicit_archive_and_lock(sample_event_list, event_archived, caplog):
    event = sample_event_list[0]
    event.archived = event_archived
    thread = thread_mock(event.thread_id, archived=True, locked=not event_archived)
    client = MagicMock(spec=discord.Client)

    await _add_user_to_event_thread(event, SignupContext(thread, None, discord.Object(id=123)), client)

    thread.edit.assert_not_awaited()
    thread.add_user.assert_not_awaited()
    assert "Not adding user" in caplog.text


@pytest.mark.parametrize("code", [50013, 50001, 10003, 50083])
async def test_membership_failure_is_logged_without_unbounded_retries(sample_event_list, code, caplog):
    event = sample_event_list[0]
    thread = thread_mock(event.thread_id)
    thread.add_user.side_effect = http_error(code)
    client = MagicMock(spec=discord.Client, fetch_channel=AsyncMock(return_value=thread))

    await _add_user_to_event_thread(event, SignupContext(thread, None, discord.Object(id=123)), client)

    assert thread.add_user.await_count == (2 if code == 50083 else 1)
    assert client.fetch_channel.await_count == (1 if code == 50083 else 0)
    assert "Failed to add user 123" in caplog.text
    assert str(event.thread_id) in caplog.text
    assert f"error code: {code}" in caplog.text


async def test_unarchive_permission_failure_does_not_attempt_membership(sample_event_list, caplog):
    event = sample_event_list[0]
    thread = thread_mock(event.thread_id, archived=True)
    thread.edit.side_effect = discord.Forbidden(MagicMock(status=403), "Cannot unarchive")

    await _add_user_to_event_thread(
        event, SignupContext(thread, None, discord.Object(id=123)), MagicMock(spec=discord.Client)
    )

    thread.add_user.assert_not_awaited()
    assert "Cannot unarchive" in caplog.text


async def test_deleted_event_thread_lookup_is_logged(sample_event_list, caplog):
    event = sample_event_list[0]
    client = MagicMock(spec=discord.Client)
    client.get_channel.return_value = None
    client.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Deleted thread"))

    await _add_user_to_event_thread(event, SignupContext(None, None, discord.Object(id=123)), client)

    assert "Failed to add user 123" in caplog.text
    assert event.event_name in caplog.text


async def test_unexpected_thread_transport_failure_stays_best_effort(sample_event_list, caplog):
    event = sample_event_list[0]
    client = MagicMock(spec=discord.Client)
    client.get_channel.return_value = None
    client.fetch_channel = AsyncMock(side_effect=ClientConnectionError("Synthetic connection failure"))

    await _add_user_to_event_thread(event, SignupContext(None, None, discord.Object(id=123)), client)

    assert "Failed to add user 123" in caplog.text
    assert "Synthetic connection failure" in caplog.text
