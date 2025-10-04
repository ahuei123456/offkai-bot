"""Tests for closed attendance count functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event, set_event_open_status
from offkai_bot.data.response import Response, WaitlistEntry, add_response, add_to_waitlist, get_responses, get_waitlist
from offkai_bot.interactions import ClosedEvent, get_current_attendance_count


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
def event_with_capacity():
    """Event with max capacity of 50."""
    now = datetime.now(UTC)
    event_dt = now + timedelta(days=30)
    deadline_dt = now + timedelta(days=7)
    return Event(
        event_name="Capacity Test Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=event_dt,
        event_deadline=deadline_dt,
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=50,
        creator_id=999,
    )


def test_closing_event_captures_attendance_count(event_with_capacity):
    """Test that closing an event saves the current attendance count."""
    # Add 30 people to the event
    for i in range(30):
        add_response(
            event_with_capacity.event_name,
            Response(
                user_id=100 + i,
                username=f"User{i}",
                extra_people=0,
                behavior_confirmed=True,
                arrival_confirmed=True,
                event_name=event_with_capacity.event_name,
                timestamp=datetime.now(UTC),
                drinks=[],
            ),
        )

    # Save event to cache
    event_data.EVENT_DATA_CACHE = [event_with_capacity]

    # Close the event
    closed_event = set_event_open_status(event_with_capacity.event_name, target_open_status=False)

    # Verify closed_attendance_count is set to 30
    assert closed_event.closed_attendance_count == 30
    assert closed_event.open is False


def test_closing_empty_event_captures_zero(event_with_capacity):
    """Test that closing an empty event saves 0 attendance count."""
    # Save event to cache
    event_data.EVENT_DATA_CACHE = [event_with_capacity]

    # Close the event (no attendees)
    closed_event = set_event_open_status(event_with_capacity.event_name, target_open_status=False)

    # Verify closed_attendance_count is 0
    assert closed_event.closed_attendance_count == 0
    assert closed_event.open is False


def test_reopening_event_clears_closed_attendance_count(event_with_capacity):
    """Test that reopening an event clears the closed_attendance_count."""
    # Add some people
    for i in range(30):
        add_response(
            event_with_capacity.event_name,
            Response(
                user_id=100 + i,
                username=f"User{i}",
                extra_people=0,
                behavior_confirmed=True,
                arrival_confirmed=True,
                event_name=event_with_capacity.event_name,
                timestamp=datetime.now(UTC),
                drinks=[],
            ),
        )

    # Save event to cache
    event_data.EVENT_DATA_CACHE = [event_with_capacity]

    # Close the event
    closed_event = set_event_open_status(event_with_capacity.event_name, target_open_status=False)
    assert closed_event.closed_attendance_count == 30

    # Reopen the event
    reopened_event = set_event_open_status(event_with_capacity.event_name, target_open_status=True)

    # Verify closed_attendance_count is cleared
    assert reopened_event.closed_attendance_count is None
    assert reopened_event.open is True


@pytest.mark.asyncio
async def test_withdrawal_from_closed_event_respects_closed_count():
    """
    Test that withdrawal from a closed event only promotes up to closed_attendance_count.

    Scenario:
    - Event has max_capacity=50
    - Only 30 people registered before closing
    - Event is closed with closed_attendance_count=30
    - Someone joins waitlist after closure
    - Original attendee withdraws
    - Waitlist user should be promoted (back to 30, not up to 50)
    """
    now = datetime.now(UTC)
    event = Event(
        event_name="Closed Count Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=False,  # Closed
        archived=False,
        drinks=[],
        max_capacity=50,
        creator_id=999,
        closed_attendance_count=30,  # Closed with 30 people
    )

    # Add 30 people (simulating they were added before closure)
    for i in range(30):
        add_response(
            event.event_name,
            Response(
                user_id=100 + i,
                username=f"User{i}",
                extra_people=0,
                behavior_confirmed=True,
                arrival_confirmed=True,
                event_name=event.event_name,
                timestamp=now,
                drinks=[],
            ),
        )

    # Add someone to waitlist (joined after closure)
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=200,
            username="WaitlistUser",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Verify initial state
    assert get_current_attendance_count(event.event_name) == 30
    assert len(get_waitlist(event.event_name)) == 1

    # User 100 withdraws
    mock_interaction = MagicMock()
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 100
    mock_interaction.user.name = "User0"
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    view = ClosedEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify waitlist user was promoted (back to 30)
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert len(responses) == 30  # 29 + 1 promoted = 30
    assert any(r.user_id == 200 for r in responses)  # Waitlist user promoted
    assert len(waitlist) == 0  # Waitlist empty
    assert get_current_attendance_count(event.event_name) == 30


@pytest.mark.asyncio
async def test_withdrawal_from_closed_event_stops_at_closed_count():
    """
    Test that multiple people on waitlist are not all promoted beyond closed_attendance_count.

    Scenario:
    - Event closed with 30/50 capacity (closed_attendance_count=30)
    - 5 people on waitlist
    - One person withdraws (frees 1 spot)
    - Only 1 person from waitlist should be promoted (to get back to 30)
    """
    now = datetime.now(UTC)
    event = Event(
        event_name="Closed Stop Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=False,
        archived=False,
        drinks=[],
        max_capacity=50,
        creator_id=999,
        closed_attendance_count=30,
    )

    # Add 30 people
    for i in range(30):
        add_response(
            event.event_name,
            Response(
                user_id=100 + i,
                username=f"User{i}",
                extra_people=0,
                behavior_confirmed=True,
                arrival_confirmed=True,
                event_name=event.event_name,
                timestamp=now,
                drinks=[],
            ),
        )

    # Add 5 people to waitlist
    for i in range(5):
        add_to_waitlist(
            event.event_name,
            WaitlistEntry(
                user_id=200 + i,
                username=f"WaitlistUser{i}",
                extra_people=0,
                behavior_confirmed=True,
                arrival_confirmed=True,
                event_name=event.event_name,
                timestamp=now,
                drinks=[],
            ),
        )

    # Verify initial state
    assert get_current_attendance_count(event.event_name) == 30
    assert len(get_waitlist(event.event_name)) == 5

    # User 100 withdraws
    mock_interaction = MagicMock()
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 100
    mock_interaction.user.name = "User0"
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    view = ClosedEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify only 1 person promoted (back to 30)
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert len(responses) == 30  # Back to closed count
    assert len(waitlist) == 4  # 4 still waiting
    assert get_current_attendance_count(event.event_name) == 30


@pytest.mark.asyncio
async def test_closed_count_is_min_of_closed_and_max_capacity():
    """
    Test that promotion respects min(closed_attendance_count, max_capacity).

    Scenario:
    - Event has max_capacity=50
    - Event closed with 60 people (somehow exceeded, maybe capacity was reduced)
    - Should not promote beyond max_capacity=50
    """
    now = datetime.now(UTC)
    event = Event(
        event_name="Min Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=False,
        archived=False,
        drinks=[],
        max_capacity=50,
        creator_id=999,
        closed_attendance_count=60,  # Somehow closed with 60 (higher than max)
    )

    # Add 49 people (1 below max capacity)
    for i in range(49):
        add_response(
            event.event_name,
            Response(
                user_id=100 + i,
                username=f"User{i}",
                extra_people=0,
                behavior_confirmed=True,
                arrival_confirmed=True,
                event_name=event.event_name,
                timestamp=now,
                drinks=[],
            ),
        )

    # Add someone to waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=200,
            username="WaitlistUser",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Add another person to waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=201,
            username="WaitlistUser2",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Verify initial state
    assert get_current_attendance_count(event.event_name) == 49
    assert len(get_waitlist(event.event_name)) == 2

    # User 100 withdraws (frees 1 spot)
    mock_interaction = MagicMock()
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 100
    mock_interaction.user.name = "User0"
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    view = ClosedEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify both people promoted (up to max_capacity=50, not closed_count=60)
    # After withdrawal from 49, we're at 48. Target is min(60, 50) = 50.
    # So we promote 2 people to reach 50.
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert len(responses) == 50  # 48 + 2 promoted = 50 (at max capacity)
    assert len(waitlist) == 0  # Both waitlist users promoted
    assert get_current_attendance_count(event.event_name) == 50
