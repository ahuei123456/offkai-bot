"""Tests for capacity limits and waitlist functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event
from offkai_bot.data.response import Response, WaitlistEntry, add_response, add_to_waitlist, get_responses, get_waitlist
from offkai_bot.interactions import (
    GatheringModal,
    get_current_attendance_count,
    get_remaining_capacity,
    is_event_at_capacity,
    would_exceed_capacity,
)

# --- Fixtures ---


@pytest.fixture(autouse=True)
def clear_test_caches(mock_paths):
    """Clear caches and files before each test in this module."""
    import json
    import os

    # Clear caches
    response_data.RESPONSE_DATA_CACHE = None

    # Initialize the temp files with empty dicts
    for file_path in [mock_paths["responses"]]:
        if file_path:
            # Create parent directory if needed
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            # Write empty dict to file
            with open(file_path, "w") as f:
                json.dump({}, f)

    yield

    # Clean up after test
    response_data.RESPONSE_DATA_CACHE = None


@pytest.fixture
def mock_interaction():
    """Fixture to create a mock discord.Interaction."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.name = "TestUser"
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.channel.id = 456
    interaction.channel.send = AsyncMock()
    interaction.channel.add_user = AsyncMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.client = MagicMock()
    interaction.client.fetch_user = AsyncMock()
    return interaction


@pytest.fixture
def event_with_capacity():
    """Event with max capacity of 3."""
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
        max_capacity=3,
    )


@pytest.fixture
def event_past_deadline():
    """Event with deadline in the past."""
    now = datetime.now(UTC)
    event_dt = now + timedelta(days=30)
    deadline_dt = now - timedelta(days=1)  # Deadline in the past
    return Event(
        event_name="Past Deadline Event",
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
        max_capacity=5,
    )


# --- Tests for Capacity Checking ---


def test_get_current_attendance_count_empty(event_with_capacity):
    """Test attendance count with no responses."""
    count = get_current_attendance_count(event_with_capacity.event_name)
    assert count == 0


def test_get_current_attendance_count_with_responses(event_with_capacity):
    """Test attendance count with responses."""
    # Add 2 responses: one with 0 extra people, one with 1 extra person
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=2,
            username="User2",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    count = get_current_attendance_count(event_with_capacity.event_name)
    assert count == 3  # 1 + 2 (1 person + 1 person with 1 extra)


def test_is_event_at_capacity_unlimited(event_with_capacity):
    """Test that unlimited capacity events are never at capacity."""
    event_with_capacity.max_capacity = None
    assert is_event_at_capacity(event_with_capacity) is False


def test_is_event_at_capacity_not_full(event_with_capacity):
    """Test event with capacity not yet reached."""
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    assert is_event_at_capacity(event_with_capacity) is False


def test_is_event_at_capacity_exactly_full(event_with_capacity):
    """Test event at exactly max capacity."""
    # Add 3 people total (capacity is 3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=2,  # 1 + 2 = 3 total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    assert is_event_at_capacity(event_with_capacity) is True


def test_is_event_at_capacity_over_full(event_with_capacity):
    """Test event over max capacity (shouldn't happen but test anyway)."""
    # Add 4 people total (capacity is 3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=3,  # 1 + 3 = 4 total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    assert is_event_at_capacity(event_with_capacity) is True


# --- Tests for Waitlist Logic in Modal ---


@pytest.mark.asyncio
@patch("offkai_bot.interactions.add_to_waitlist")
@patch("offkai_bot.interactions.add_response")
async def test_modal_adds_to_responses_when_not_at_capacity(
    mock_add_response, mock_add_to_waitlist, event_with_capacity, mock_interaction
):
    """Test that modal adds to responses when event is not at capacity."""
    modal = GatheringModal(event=event_with_capacity)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "0"
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Should add to responses, not waitlist
    mock_add_response.assert_called_once()
    mock_add_to_waitlist.assert_not_called()


@pytest.mark.asyncio
@patch("offkai_bot.interactions.add_to_waitlist")
@patch("offkai_bot.interactions.add_response")
async def test_modal_adds_to_waitlist_when_at_capacity(
    mock_add_response, mock_add_to_waitlist, event_with_capacity, mock_interaction
):
    """Test that modal adds to waitlist when event is at capacity."""
    # Fill the event to capacity
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=999,
            username="ExistingUser",
            extra_people=2,  # 3 total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    modal = GatheringModal(event=event_with_capacity)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "0"
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Should add to waitlist, not responses
    mock_add_to_waitlist.assert_called_once()
    mock_add_response.assert_not_called()


@pytest.mark.asyncio
@patch("offkai_bot.interactions.add_to_waitlist")
@patch("offkai_bot.interactions.add_response")
async def test_modal_adds_to_waitlist_when_past_deadline(
    mock_add_response, mock_add_to_waitlist, event_past_deadline, mock_interaction
):
    """Test that modal adds to waitlist when deadline has passed."""
    modal = GatheringModal(event=event_past_deadline)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "0"
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Should add to waitlist because deadline has passed
    mock_add_to_waitlist.assert_called_once()
    mock_add_response.assert_not_called()


# --- Tests for Waitlist Functionality ---


def test_add_to_waitlist(event_with_capacity):
    """Test adding an entry to the waitlist."""
    from offkai_bot.data.response import add_to_waitlist

    entry = WaitlistEntry(
        user_id=123,
        username="WaitlistUser",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event_with_capacity.event_name,
        timestamp=datetime.now(UTC),
        drinks=[],
    )

    add_to_waitlist(event_with_capacity.event_name, entry)

    waitlist = get_waitlist(event_with_capacity.event_name)
    assert len(waitlist) == 1
    assert waitlist[0].user_id == 123


def test_promote_from_waitlist_fifo(event_with_capacity):
    """Test that promote_from_waitlist follows FIFO order."""
    from offkai_bot.data.response import add_to_waitlist, promote_from_waitlist

    # Add 3 entries to waitlist
    for i in range(3):
        entry = WaitlistEntry(
            user_id=100 + i,
            username=f"User{i}",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        )
        add_to_waitlist(event_with_capacity.event_name, entry)

    # Promote first entry
    promoted = promote_from_waitlist(event_with_capacity.event_name)

    assert promoted is not None
    assert promoted.user_id == 100  # First added should be first promoted

    # Check remaining waitlist
    waitlist = get_waitlist(event_with_capacity.event_name)
    assert len(waitlist) == 2
    assert waitlist[0].user_id == 101
    assert waitlist[1].user_id == 102


def test_promote_from_empty_waitlist(event_with_capacity):
    """Test that promote_from_waitlist returns None for empty waitlist."""
    from offkai_bot.data.response import promote_from_waitlist

    promoted = promote_from_waitlist(event_with_capacity.event_name)
    assert promoted is None


# --- Tests for Withdraw with Promotion ---


@pytest.mark.asyncio
async def test_withdraw_promotes_from_waitlist(event_with_capacity, mock_interaction):
    """Test that withdrawing promotes someone from the waitlist."""
    from offkai_bot.data.response import add_to_waitlist
    from offkai_bot.interactions import OpenEvent

    # Add a response (at capacity)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=123,
            username="AttendingUser",
            extra_people=2,  # 3 total - at capacity
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Add someone to waitlist
    waitlist_entry = WaitlistEntry(
        user_id=456,
        username="WaitlistUser",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event_with_capacity.event_name,
        timestamp=datetime.now(UTC),
        drinks=[],
    )
    add_to_waitlist(event_with_capacity.event_name, waitlist_entry)

    # Verify initial state
    assert len(get_responses(event_with_capacity.event_name)) == 1
    assert len(get_waitlist(event_with_capacity.event_name)) == 1

    # Simulate withdraw
    view = OpenEvent(event=event_with_capacity)
    mock_interaction.user.id = 123  # User who is withdrawing
    mock_interaction.user.send = AsyncMock()

    # Call the callback directly (withdraw is a Button, not a method)
    await view.withdraw.callback(mock_interaction)

    # Check that waitlist user was promoted
    responses = get_responses(event_with_capacity.event_name)
    waitlist = get_waitlist(event_with_capacity.event_name)

    # Original user removed, waitlist user promoted
    assert len(responses) == 1
    assert responses[0].user_id == 456  # Promoted user
    assert len(waitlist) == 0  # Waitlist is now empty


@pytest.mark.asyncio
async def test_withdraw_no_promotion_when_waitlist_empty(event_with_capacity, mock_interaction):
    """Test that withdrawing works normally when waitlist is empty."""
    from offkai_bot.interactions import OpenEvent

    # Add a response
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=123,
            username="AttendingUser",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Verify initial state
    assert len(get_responses(event_with_capacity.event_name)) == 1
    assert len(get_waitlist(event_with_capacity.event_name)) == 0

    # Simulate withdraw
    view = OpenEvent(event=event_with_capacity)
    mock_interaction.user.id = 123
    mock_interaction.user.send = AsyncMock()

    # Call the callback directly (withdraw is a Button, not a method)
    await view.withdraw.callback(mock_interaction)

    # Check that user was removed and no one was promoted
    responses = get_responses(event_with_capacity.event_name)
    assert len(responses) == 0


# --- Tests for Capacity Overflow Prevention ---


def test_would_exceed_capacity_unlimited(event_with_capacity):
    """Test that unlimited capacity never exceeds."""
    event_with_capacity.max_capacity = None
    assert would_exceed_capacity(event_with_capacity, 1000) is False


def test_would_exceed_capacity_fits(event_with_capacity):
    """Test group that fits within remaining capacity."""
    # Add 1 person (capacity is 3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Try to add 2 more (should fit)
    assert would_exceed_capacity(event_with_capacity, 2) is False


def test_would_exceed_capacity_exceeds(event_with_capacity):
    """Test group that would exceed capacity."""
    # Current: 1 person (capacity is 3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Try to add 3 more (would exceed: 1 + 3 = 4 > 3)
    assert would_exceed_capacity(event_with_capacity, 3) is True


def test_get_remaining_capacity_unlimited(event_with_capacity):
    """Test remaining capacity for unlimited events."""
    event_with_capacity.max_capacity = None
    assert get_remaining_capacity(event_with_capacity) is None


def test_get_remaining_capacity_empty(event_with_capacity):
    """Test remaining capacity for empty event."""
    remaining = get_remaining_capacity(event_with_capacity)
    assert remaining == 3


def test_get_remaining_capacity_partial(event_with_capacity):
    """Test remaining capacity with some attendees."""
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=1,  # 2 people total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    remaining = get_remaining_capacity(event_with_capacity)
    assert remaining == 1


def test_get_remaining_capacity_full(event_with_capacity):
    """Test remaining capacity for full event."""
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=1,
            username="User1",
            extra_people=2,  # 3 people total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    remaining = get_remaining_capacity(event_with_capacity)
    assert remaining == 0


@pytest.mark.asyncio
async def test_modal_adds_to_waitlist_when_group_exceeds_capacity(event_with_capacity, mock_interaction):
    """Test that modal adds to waitlist when registration would exceed capacity."""
    # Fill to 1 spot remaining (2/3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=999,
            username="ExistingUser",
            extra_people=1,  # 2 people total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Try to register with +1 (2 people total, would exceed)
    modal = GatheringModal(event=event_with_capacity)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "1"  # +1 person
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Should be added to waitlist, not responses
    assert len(get_responses(event_with_capacity.event_name)) == 1  # Still just the original
    assert len(get_waitlist(event_with_capacity.event_name)) == 1  # New user added to waitlist

    # Verify the waitlist entry
    waitlist = get_waitlist(event_with_capacity.event_name)
    assert waitlist[0].user_id == 123
    assert waitlist[0].extra_people == 1


@pytest.mark.asyncio
async def test_modal_capacity_exceeded_message_content(event_with_capacity, mock_interaction):
    """Test that the capacity exceeded message has the correct content."""
    # Fill to 1 spot remaining (2/3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=999,
            username="ExistingUser",
            extra_people=1,  # 2 people total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Try to register with +1 (2 people total, would exceed)
    modal = GatheringModal(event=event_with_capacity)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "1"  # +1 person
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Check that the message was sent
    assert mock_interaction.response.send_message.called or mock_interaction.user.send.called

    # Try DM first (user.send)
    if mock_interaction.user.send.called:
        message = mock_interaction.user.send.call_args[0][0]
        # Verify message content
        assert "your group of 2 people would exceed the capacity" in message
        assert "Only 1 spot(s) remaining out of 3 total" in message
        assert "For now you will be added to the waiting list" in message
        assert "leave the offkai and re-apply with fewer people" in message
    else:
        # Fall back to ephemeral message
        message = mock_interaction.response.send_message.call_args[1]["content"]
        assert "your group of 2 people would exceed the capacity" in message
        assert "Only 1 spot(s) remaining out of 3 total" in message
        assert "For now you will be added to the waiting list" in message
        assert "leave the offkai and re-apply with fewer people" in message


@pytest.mark.asyncio
async def test_capacity_reached_message_sent_when_filling_event(event_with_capacity, mock_interaction):
    """Test that capacity reached message is sent when a registration fills the event."""
    # Start with empty event (capacity is 3)
    # User joins with +1 (2 people total) - not at capacity yet
    modal = GatheringModal(event=event_with_capacity)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "1"  # +1 person (2 total)
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Should have sent to channel (not at capacity yet, so no message)
    assert not mock_interaction.channel.send.called

    # Now another user joins with 0 extra (1 person) - this fills to capacity
    mock_interaction2 = MagicMock(spec=discord.Interaction)
    mock_interaction2.user = MagicMock(spec=discord.Member)
    mock_interaction2.user.id = 456  # Different user
    mock_interaction2.user.name = "TestUser2"
    mock_interaction2.channel = MagicMock(spec=discord.Thread)
    mock_interaction2.channel.id = 456
    mock_interaction2.channel.send = AsyncMock()
    mock_interaction2.channel.add_user = AsyncMock()
    mock_interaction2.response = MagicMock()
    mock_interaction2.response.send_message = AsyncMock()
    mock_interaction2.user.send = AsyncMock()

    modal2 = GatheringModal(event=event_with_capacity)
    modal2.extra_people_input = MagicMock()
    modal2.extra_people_input.value = "0"  # 0 extra (1 total, bringing total to 3)
    modal2.behave_checkbox_input = MagicMock()
    modal2.behave_checkbox_input.value = "Yes"
    modal2.arrival_checkbox_input = MagicMock()
    modal2.arrival_checkbox_input.value = "Yes"
    modal2.drink_choice_input = None

    await modal2.on_submit(mock_interaction2)

    # Now we should have sent the capacity reached message
    assert mock_interaction2.channel.send.called
    message = mock_interaction2.channel.send.call_args[0][0]
    assert "Maximum capacity has been reached" in message
    assert "waitlist" in message.lower()


@pytest.mark.asyncio
async def test_closed_event_adds_to_waitlist(event_with_capacity, mock_interaction):
    """Test that joining a closed event adds user to waitlist."""
    # Close the event
    event_with_capacity.open = False

    # User tries to join
    modal = GatheringModal(event=event_with_capacity)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "0"
    modal.behave_checkbox_input = MagicMock()
    modal.behave_checkbox_input.value = "Yes"
    modal.arrival_checkbox_input = MagicMock()
    modal.arrival_checkbox_input.value = "Yes"
    modal.drink_choice_input = None

    await modal.on_submit(mock_interaction)

    # Should be added to waitlist, not responses
    assert len(get_responses(event_with_capacity.event_name)) == 0
    assert len(get_waitlist(event_with_capacity.event_name)) == 1


@pytest.mark.asyncio
async def test_closed_event_view_has_waitlist_button():
    """Test that ClosedEvent view has a Join Waitlist button."""
    from offkai_bot.interactions import ClosedEvent

    now = datetime.now(UTC)
    event = Event(
        event_name="Closed Test Event",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=False,  # Closed event
        archived=False,
        drinks=[],
        max_capacity=5,
    )

    view = ClosedEvent(event)

    # Check that view has all buttons
    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]
    assert len(buttons) == 4  # Responses Closed + Join Waitlist + Withdraw Attendance + Attendance Count
    labels = [button.label for button in buttons]
    assert "Responses Closed" in labels
    assert "Join Waitlist" in labels
    assert "Withdraw Attendance" in labels


@pytest.mark.asyncio
async def test_batch_promotion_fills_all_available_capacity():
    """Test that multiple users are promoted when large group withdraws."""
    from offkai_bot.interactions import OpenEvent

    now = datetime.now(UTC)
    event = Event(
        event_name="Batch Promo Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=4,
    )

    # User A joins with +3 (4 people total) - fills to capacity
    add_response(
        event.event_name,
        Response(
            user_id=100,
            username="UserA",
            extra_people=3,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User B joins alone - goes to waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=200,
            username="UserB",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User C joins alone - goes to waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=300,
            username="UserC",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User D joins with +1 (2 people) - goes to waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=400,
            username="UserD",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Verify initial state
    assert len(get_responses(event.event_name)) == 1  # User A
    assert len(get_waitlist(event.event_name)) == 3  # Users B, C, D
    assert get_current_attendance_count(event.event_name) == 4

    # Create mock interaction for withdrawal
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.id = 100  # User A
    mock_interaction.user.name = "UserA"
    mock_interaction.channel = MagicMock(spec=discord.Thread)
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    # User A withdraws using the button
    view = OpenEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify batch promotions
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    # All three waitlist users should be promoted (B=1, C=1, D=2 = 4 total)
    assert len(responses) == 3, f"Expected 3 responses, got {len(responses)}"
    assert len(waitlist) == 0, f"Expected empty waitlist, got {len(waitlist)}"

    # Verify correct users were promoted
    response_user_ids = [r.user_id for r in responses]
    assert 200 in response_user_ids  # User B
    assert 300 in response_user_ids  # User C
    assert 400 in response_user_ids  # User D

    # Verify capacity is exactly filled
    assert get_current_attendance_count(event.event_name) == 4


@pytest.mark.asyncio
async def test_batch_promotion_stops_at_capacity():
    """Test that promotions stop when capacity is reached."""
    from offkai_bot.interactions import OpenEvent

    now = datetime.now(UTC)
    event = Event(
        event_name="Batch Stop Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=4,
    )

    # User A joins with +1 (2 people)
    add_response(
        event.event_name,
        Response(
            user_id=100,
            username="UserA",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User B joins with +1 (2 people) - fills to capacity
    add_response(
        event.event_name,
        Response(
            user_id=200,
            username="UserB",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User C joins alone - waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=300,
            username="UserC",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User D joins with +1 (2 people) - waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=400,
            username="UserD",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Verify initial state: 4/4 capacity, 2 on waitlist
    assert get_current_attendance_count(event.event_name) == 4
    assert len(get_waitlist(event.event_name)) == 2

    # User A withdraws (frees 2 spots)
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.id = 100
    mock_interaction.user.name = "UserA"
    mock_interaction.channel = MagicMock(spec=discord.Thread)
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    view = OpenEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify: Only User C promoted (1 person), User D stays waitlisted (would exceed)
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert len(responses) == 2  # User B and User C
    assert len(waitlist) == 1  # User D
    assert waitlist[0].user_id == 400  # User D still waiting

    # Verify capacity
    assert get_current_attendance_count(event.event_name) == 3  # User B (2) + User C (1)


@pytest.mark.asyncio
async def test_withdrawal_from_closed_event_promotes_from_waitlist():
    """Test that users can withdraw from closed events and waitlist is promoted."""
    from offkai_bot.interactions import ClosedEvent

    now = datetime.now(UTC)
    event = Event(
        event_name="Closed Event Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=False,  # Closed event
        archived=False,
        drinks=[],
        max_capacity=2,
        closed_attendance_count=2,  # Event was closed with 2 people
    )

    # User A joins (2 spots - at capacity)
    add_response(
        event.event_name,
        Response(
            user_id=100,
            username="UserA",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User B joins waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=200,
            username="UserB",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Verify initial state
    assert len(get_responses(event.event_name)) == 1
    assert len(get_waitlist(event.event_name)) == 1
    assert get_current_attendance_count(event.event_name) == 2

    # User A withdraws from closed event
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.id = 100
    mock_interaction.user.name = "UserA"
    mock_interaction.channel = MagicMock(spec=discord.Thread)
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    view = ClosedEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify User B was promoted
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert len(responses) == 1
    assert responses[0].user_id == 200  # User B promoted
    assert len(waitlist) == 0
    assert get_current_attendance_count(event.event_name) == 1


@pytest.mark.asyncio
async def test_withdrawal_from_post_deadline_event_promotes_from_waitlist():
    """Test that users can withdraw from post-deadline events and waitlist is promoted."""
    from offkai_bot.interactions import PostDeadlineEvent

    now = datetime.now(UTC)
    event = Event(
        event_name="Post Deadline Test",
        venue="Test Venue",
        address="Test Address",
        google_maps_link="test_link",
        event_datetime=now + timedelta(days=30),
        event_deadline=now - timedelta(days=1),  # Deadline passed
        channel_id=456,
        thread_id=111,
        message_id=None,
        open=True,  # Open but deadline passed
        archived=False,
        drinks=[],
        max_capacity=3,
    )

    # User A joins with +1 (2 people)
    add_response(
        event.event_name,
        Response(
            user_id=100,
            username="UserA",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User B joins (1 person - now at capacity of 3)
    add_response(
        event.event_name,
        Response(
            user_id=200,
            username="UserB",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # User C joins waitlist
    add_to_waitlist(
        event.event_name,
        WaitlistEntry(
            user_id=300,
            username="UserC",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=now,
            drinks=[],
        ),
    )

    # Verify initial state
    assert get_current_attendance_count(event.event_name) == 3
    assert len(get_waitlist(event.event_name)) == 1

    # User A withdraws from post-deadline event
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.id = 100
    mock_interaction.user.name = "UserA"
    mock_interaction.channel = MagicMock(spec=discord.Thread)
    mock_interaction.channel.remove_user = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.user.send = AsyncMock()
    mock_interaction.client = MagicMock()
    mock_interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    view = PostDeadlineEvent(event)
    await view.withdraw.callback(mock_interaction)

    # Verify User C was promoted
    responses = get_responses(event.event_name)
    waitlist = get_waitlist(event.event_name)

    assert len(responses) == 2  # User B and User C
    assert any(r.user_id == 200 for r in responses)  # User B
    assert any(r.user_id == 300 for r in responses)  # User C promoted
    assert len(waitlist) == 0
    assert get_current_attendance_count(event.event_name) == 2


@pytest.mark.asyncio
async def test_withdraw_from_waitlist_when_capacity_exceeded(event_with_capacity, mock_interaction):
    """Test that user can withdraw from waitlist when added due to capacity exceeded."""
    from offkai_bot.interactions import OpenEvent

    # Fill event to 1 spot remaining (capacity is 3)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=999,
            username="ExistingUser",
            extra_people=1,  # 2 people
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # User joins with +1 (2 people total) - exceeds capacity, added to waitlist
    add_to_waitlist(
        event_with_capacity.event_name,
        WaitlistEntry(
            user_id=123,
            username="TestUser",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Verify initial state
    assert len(get_responses(event_with_capacity.event_name)) == 1
    assert len(get_waitlist(event_with_capacity.event_name)) == 1

    # User tries to withdraw
    view = OpenEvent(event=event_with_capacity)
    mock_interaction.user.id = 123
    mock_interaction.user.send = AsyncMock()

    await view.withdraw.callback(mock_interaction)

    # Verify user was removed from waitlist
    responses = get_responses(event_with_capacity.event_name)
    waitlist = get_waitlist(event_with_capacity.event_name)

    assert len(responses) == 1  # Original user still there
    assert len(waitlist) == 0  # User removed from waitlist
    assert mock_interaction.response.send_message.called or mock_interaction.user.send.called


@pytest.mark.asyncio
async def test_withdraw_from_waitlist_does_not_promote_others(event_with_capacity, mock_interaction):
    """Test that withdrawing from waitlist doesn't promote others (no capacity freed)."""
    from offkai_bot.interactions import OpenEvent

    # Fill event to capacity (3 people)
    add_response(
        event_with_capacity.event_name,
        Response(
            user_id=999,
            username="ExistingUser",
            extra_people=2,  # 3 people total
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # User A joins waitlist
    add_to_waitlist(
        event_with_capacity.event_name,
        WaitlistEntry(
            user_id=123,
            username="UserA",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # User B joins waitlist
    add_to_waitlist(
        event_with_capacity.event_name,
        WaitlistEntry(
            user_id=456,
            username="UserB",
            extra_people=0,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event_with_capacity.event_name,
            timestamp=datetime.now(UTC),
            drinks=[],
        ),
    )

    # Verify initial state
    assert len(get_responses(event_with_capacity.event_name)) == 1
    assert len(get_waitlist(event_with_capacity.event_name)) == 2

    # User A withdraws from waitlist
    view = OpenEvent(event=event_with_capacity)
    mock_interaction.user.id = 123
    mock_interaction.user.send = AsyncMock()

    await view.withdraw.callback(mock_interaction)

    # Verify User A removed, User B NOT promoted (no capacity freed)
    responses = get_responses(event_with_capacity.event_name)
    waitlist = get_waitlist(event_with_capacity.event_name)

    assert len(responses) == 1  # Still just original user
    assert responses[0].user_id == 999  # Original user
    assert len(waitlist) == 1  # User A removed, User B still waiting
    assert waitlist[0].user_id == 456  # User B still in waitlist


@pytest.mark.asyncio
async def test_withdraw_fails_when_user_not_registered(event_with_capacity, mock_interaction):
    """Test that withdrawal fails with proper error when user not registered."""
    from offkai_bot.interactions import OpenEvent

    # User tries to withdraw without being registered
    view = OpenEvent(event=event_with_capacity)
    mock_interaction.user.id = 123
    mock_interaction.user.send = AsyncMock()

    await view.withdraw.callback(mock_interaction)

    # Verify error message was sent
    assert mock_interaction.response.send_message.called
    error_call = mock_interaction.response.send_message.call_args
    assert "have not registered" in str(error_call).lower() or "cannot withdraw" in str(error_call).lower()
