"""Test to verify event data isolation and duplicate prevention across responses and waitlist."""

from datetime import UTC, datetime

import pytest

from offkai_bot.data.response import (
    Response,
    WaitlistEntry,
    add_response,
    add_to_waitlist,
    get_responses,
    get_waitlist,
    promote_from_waitlist,
    remove_response,
)
from offkai_bot.errors import DuplicateResponseError


def test_event_isolation_across_multiple_events():
    """
    Verify that event data is properly isolated between different events.

    Scenario:
    1. Create test1, user A joins, user B joins waitlist, user A withdraws, user B promoted
    2. Verify test2 is completely independent - no users registered
    """
    now = datetime.now(UTC)

    # Initialize cache
    from offkai_bot.data.response import load_responses, load_waitlist

    load_responses()
    load_waitlist()

    # User A joins test1 with +1 (2 people)
    response_a_test1 = Response(
        user_id=111,  # User A
        username="UserA",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test1",
        timestamp=now,
        drinks=[],
    )
    add_response("test1", response_a_test1)

    # User B tries to join test1 with +1 (would be 4 total, goes to waitlist)
    waitlist_b_test1 = WaitlistEntry(
        user_id=222,  # User B
        username="UserB",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test1",
        timestamp=now,
        drinks=[],
    )
    add_to_waitlist("test1", waitlist_b_test1)

    # User A withdraws from test1
    remove_response("test1", 111)

    # User B gets promoted
    promoted = promote_from_waitlist("test1")
    assert promoted.user_id == 222

    # Add promoted user to responses
    response_b_test1 = Response(
        user_id=promoted.user_id,
        username=promoted.username,
        extra_people=promoted.extra_people,
        behavior_confirmed=promoted.behavior_confirmed,
        arrival_confirmed=promoted.arrival_confirmed,
        event_name=promoted.event_name,
        timestamp=promoted.timestamp,
        drinks=promoted.drinks,
    )
    add_response("test1", response_b_test1)

    # Verify test1 state
    test1_responses = get_responses("test1")
    assert len(test1_responses) == 1
    assert test1_responses[0].user_id == 222

    test1_waitlist = get_waitlist("test1")
    assert len(test1_waitlist) == 0

    # Verify test2 is completely independent
    test2_responses = get_responses("test2")
    assert len(test2_responses) == 0, "test2 should have no responses"

    test2_waitlist = get_waitlist("test2")
    assert len(test2_waitlist) == 0, "test2 should have no waitlist"

    # Verify users can register for test2 without being prevented
    # (DuplicateResponseError would only trigger if they try to register twice for the SAME event)
    response_a_test2 = Response(
        user_id=111,
        username="UserA",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test2",
        timestamp=now,
        drinks=[],
    )
    add_response("test2", response_a_test2)  # Should succeed without error

    response_b_test2 = Response(
        user_id=222,
        username="UserB",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test2",
        timestamp=now,
        drinks=[],
    )
    add_response("test2", response_b_test2)  # Should succeed without error

    # Verify both users are now in test2
    test2_responses = get_responses("test2")
    assert len(test2_responses) == 2
    assert any(r.user_id == 111 for r in test2_responses)
    assert any(r.user_id == 222 for r in test2_responses)


def test_cannot_add_to_waitlist_if_in_responses():
    """Test that a user in responses cannot be added to waitlist."""
    now = datetime.now(UTC)

    # Initialize cache
    from offkai_bot.data.response import load_responses, load_waitlist

    load_responses()
    load_waitlist()

    # User joins responses
    response = Response(
        user_id=111,
        username="TestUser",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test_event",
        timestamp=now,
        drinks=[],
    )
    add_response("test_event", response)

    # Try to add same user to waitlist - should fail
    waitlist_entry = WaitlistEntry(
        user_id=111,
        username="TestUser",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test_event",
        timestamp=now,
        drinks=[],
    )

    with pytest.raises(DuplicateResponseError) as exc_info:
        add_to_waitlist("test_event", waitlist_entry)

    assert "test_event" in str(exc_info.value)

    # Verify user is only in responses, not waitlist
    responses = get_responses("test_event")
    waitlist = get_waitlist("test_event")
    assert len(responses) == 1
    assert len(waitlist) == 0


def test_cannot_add_to_responses_if_in_waitlist():
    """Test that a user in waitlist cannot be added to responses."""
    now = datetime.now(UTC)

    # Initialize cache
    from offkai_bot.data.response import load_responses, load_waitlist

    load_responses()
    load_waitlist()

    # User joins waitlist
    waitlist_entry = WaitlistEntry(
        user_id=222,
        username="TestUser2",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test_event2",
        timestamp=now,
        drinks=[],
    )
    add_to_waitlist("test_event2", waitlist_entry)

    # Try to add same user to responses - should fail
    response = Response(
        user_id=222,
        username="TestUser2",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test_event2",
        timestamp=now,
        drinks=[],
    )

    with pytest.raises(DuplicateResponseError) as exc_info:
        add_response("test_event2", response)

    assert "test_event2" in str(exc_info.value)

    # Verify user is only in waitlist, not responses
    responses = get_responses("test_event2")
    waitlist = get_waitlist("test_event2")
    assert len(responses) == 0
    assert len(waitlist) == 1


def test_promotion_removes_from_waitlist_before_adding_to_responses():
    """Test that promotion properly removes user from waitlist before adding to responses."""
    now = datetime.now(UTC)

    # Initialize cache
    from offkai_bot.data.response import load_responses, load_waitlist

    load_responses()
    load_waitlist()

    # User joins waitlist
    waitlist_entry = WaitlistEntry(
        user_id=333,
        username="TestUser3",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="test_event3",
        timestamp=now,
        drinks=[],
    )
    add_to_waitlist("test_event3", waitlist_entry)

    # Promote user
    promoted = promote_from_waitlist("test_event3")
    assert promoted is not None
    assert promoted.user_id == 333

    # User should be removed from waitlist
    waitlist = get_waitlist("test_event3")
    assert len(waitlist) == 0

    # Now add to responses - should succeed because user is no longer in waitlist
    response = Response(
        user_id=promoted.user_id,
        username=promoted.username,
        extra_people=promoted.extra_people,
        behavior_confirmed=promoted.behavior_confirmed,
        arrival_confirmed=promoted.arrival_confirmed,
        event_name=promoted.event_name,
        timestamp=promoted.timestamp,
        drinks=promoted.drinks,
    )
    add_response("test_event3", response)  # Should not raise

    # Verify user is in responses and not in waitlist
    responses = get_responses("test_event3")
    waitlist = get_waitlist("test_event3")
    assert len(responses) == 1
    assert len(waitlist) == 0
    assert responses[0].user_id == 333
