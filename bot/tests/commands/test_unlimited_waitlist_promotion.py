"""Tests for waitlist promotion on unlimited-capacity events (issue #108)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from offkai_bot.data.event import Event
from offkai_bot.data.response import Response, WaitlistEntry, add_response, add_to_waitlist, get_responses, get_waitlist
from offkai_bot.interactions import PostDeadlineEvent, get_current_attendance_count, promote_waitlist_batch

from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data


@pytest.fixture(autouse=True)
def clear_test_caches(mock_paths):
    """Clear caches and files before each test in this module."""
    import json
    import os

    # Clear caches
    event_data.EVENT_DATA_CACHE = None
    response_data.RESPONSE_DATA_CACHE = None

    # Initialize the temp files
    for file_path in [mock_paths["events"], mock_paths["responses"]]:
        if file_path:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            if "events" in file_path:
                with open(file_path, "w") as f:
                    json.dump([], f)
            else:
                with open(file_path, "w") as f:
                    json.dump({}, f)

    yield

    # Clean up after test
    event_data.EVENT_DATA_CACHE = None
    response_data.RESPONSE_DATA_CACHE = None


@pytest.fixture
def unlimited_event_past_deadline():
    """Unlimited-capacity event whose deadline has passed but is still open."""
    now = datetime.now(UTC)
    return Event(
        event_name="Unlimited Test Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now - timedelta(days=1),  # Deadline in the past
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=None,  # Unlimited
        creator_id=999,
    )


def _add_attendee(event_name: str, user_id: int, extra_people: int = 0):
    add_response(
        event_name,
        Response(
            user_id=user_id,
            username=f"User{user_id}",
            extra_people=extra_people,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )


def _add_waitlisted(event_name: str, user_id: int, extra_people: int = 0):
    add_to_waitlist(
        event_name,
        WaitlistEntry(
            user_id=user_id,
            username=f"WaitlistUser{user_id}",
            extra_people=extra_people,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )


def _make_withdraw_interaction(user_id: int):
    mock_interaction = MagicMock()
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = user_id
    mock_interaction.user.name = f"User{user_id}"
    mock_interaction.user.send = AsyncMock()
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))
    return mock_interaction


def _make_mock_client():
    client = MagicMock()
    client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))
    return client


@pytest.mark.asyncio
async def test_group_withdrawal_promotes_matching_headcount(unlimited_event_past_deadline):
    """
    A party of 6 withdrawing from an unlimited event frees 6 spots,
    so 6 waitlisted people (not just 1 group) are promoted.
    """
    event = unlimited_event_past_deadline

    # Party of 6 (1 + 5 extras) plus 4 solo attendees
    _add_attendee(event.event_name, 100, extra_people=5)
    for i in range(4):
        _add_attendee(event.event_name, 101 + i)

    # 8 solo people join the waitlist after the deadline
    for i in range(8):
        _add_waitlisted(event.event_name, 200 + i)

    assert get_current_attendance_count(event.event_name) == 10

    view = PostDeadlineEvent(event)
    await view.withdraw.callback(_make_withdraw_interaction(100))

    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    # 6 spots freed -> 6 promoted, headcount back to 10, 2 still waiting
    assert get_current_attendance_count(event.event_name) == 10
    assert len(responses) == 10  # 4 original + 6 promoted
    assert len(waitlist) == 2
    promoted_ids = {r.user_id for r in responses if r.user_id >= 200}
    assert promoted_ids == {200, 201, 202, 203, 204, 205}  # FIFO order


@pytest.mark.asyncio
async def test_solo_withdrawal_promotes_single_group(unlimited_event_past_deadline):
    """A solo withdrawal from an unlimited event still promotes exactly one solo group."""
    event = unlimited_event_past_deadline

    for i in range(3):
        _add_attendee(event.event_name, 100 + i)
    for i in range(3):
        _add_waitlisted(event.event_name, 200 + i)

    view = PostDeadlineEvent(event)
    await view.withdraw.callback(_make_withdraw_interaction(100))

    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert get_current_attendance_count(event.event_name) == 3
    assert any(r.user_id == 200 for r in responses)  # First in line promoted
    assert len(waitlist) == 2


@pytest.mark.asyncio
async def test_group_withdrawal_promotes_whole_waitlist_when_smaller(unlimited_event_past_deadline):
    """If fewer people are waitlisted than spots freed, the whole waitlist is promoted."""
    event = unlimited_event_past_deadline

    _add_attendee(event.event_name, 100, extra_people=5)  # Party of 6
    _add_waitlisted(event.event_name, 200)
    _add_waitlisted(event.event_name, 201)

    view = PostDeadlineEvent(event)
    await view.withdraw.callback(_make_withdraw_interaction(100))

    responses = get_responses(event.event_name)
    assert {r.user_id for r in responses} == {200, 201}
    assert len(get_waitlist(event.event_name)) == 0


@pytest.mark.asyncio
async def test_promotion_stops_when_next_group_exceeds_freed_spots(unlimited_event_past_deadline):
    """A group larger than the freed headcount is not promoted (FIFO order preserved)."""
    event = unlimited_event_past_deadline

    _add_attendee(event.event_name, 100)  # Solo attendee
    _add_waitlisted(event.event_name, 200, extra_people=2)  # Party of 3, first in line
    _add_waitlisted(event.event_name, 201)  # Solo, second in line

    view = PostDeadlineEvent(event)
    await view.withdraw.callback(_make_withdraw_interaction(100))

    # Only 1 spot freed; the party of 3 doesn't fit and promotion stops rather
    # than skipping ahead to the solo entry behind it.
    assert get_responses(event.event_name) == []
    assert len(get_waitlist(event.event_name)) == 2


@pytest.mark.asyncio
async def test_promote_batch_without_freed_spots_drains_waitlist(unlimited_event_past_deadline):
    """With no capacity target and no freed-spot bound, the whole waitlist is promoted."""
    event = unlimited_event_past_deadline

    for i in range(5):
        _add_waitlisted(event.event_name, 200 + i, extra_people=i % 3)

    promoted = await promote_waitlist_batch(event, _make_mock_client())

    assert len(promoted) == 5
    assert len(get_waitlist(event.event_name)) == 0
    assert len(get_responses(event.event_name)) == 5
