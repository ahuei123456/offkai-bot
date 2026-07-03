# tests/data/test_promote_rollback.py
"""Tests for issue #105: a failed promotion must not drop a user from both the waitlist and attendees."""

from datetime import UTC, datetime

import pytest
from offkai_bot.data.response import (
    EventData,
    Response,
    WaitlistEntry,
    add_to_waitlist,
    get_waitlist,
    load_responses,
    promote_from_waitlist,
    promote_specific_from_waitlist,
    restore_waitlist_entry,
)
from offkai_bot.errors import DuplicateResponseError


def _make_response(event_name: str, user_id: int) -> Response:
    return Response(
        user_id=user_id,
        username=f"user{user_id}",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event_name,
        timestamp=datetime.now(UTC),
        drinks=[],
    )


def _make_entry(event_name: str, user_id: int) -> WaitlistEntry:
    return WaitlistEntry(
        user_id=user_id,
        username=f"user{user_id}",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event_name,
        timestamp=datetime.now(UTC),
        drinks=[],
    )


def test_promote_specific_removes_from_waitlist():
    """Happy path: the entry is removed from the waitlist and returned with its original index."""
    event_name = "Rollback Happy Path Event"
    load_responses()
    add_to_waitlist(event_name, _make_entry(event_name, 101))
    add_to_waitlist(event_name, _make_entry(event_name, 102))

    promoted, original_index = promote_specific_from_waitlist(event_name, 102)

    assert promoted.user_id == 102
    assert original_index == 1
    assert [e.user_id for e in get_waitlist(event_name)] == [101]


def test_promote_specific_refuses_when_already_attendee():
    """A stale attendee record must not cause the waitlist entry to be dropped."""
    event_name = "Rollback Stale Attendee Event"
    # Seed inconsistent state directly: user is both an attendee and on the waitlist.
    all_data = load_responses()
    all_data[event_name] = EventData(
        attendees=[_make_response(event_name, 111)],
        waitlist=[_make_entry(event_name, 111)],
    )

    with pytest.raises(DuplicateResponseError):
        promote_specific_from_waitlist(event_name, 111)

    # The waitlist entry must be untouched.
    assert [e.user_id for e in get_waitlist(event_name)] == [111]


def test_restore_waitlist_entry_reinserts_at_front():
    event_name = "Rollback Restore Event"
    load_responses()
    add_to_waitlist(event_name, _make_entry(event_name, 201))
    add_to_waitlist(event_name, _make_entry(event_name, 202))

    popped = promote_from_waitlist(event_name)
    assert popped is not None
    assert popped.user_id == 201

    restore_waitlist_entry(event_name, popped)

    assert [e.user_id for e in get_waitlist(event_name)] == [201, 202]


def test_restore_waitlist_entry_at_original_position_preserves_order():
    """Rolling back a promotion from the middle of the waitlist must not reorder the queue."""
    event_name = "Rollback Middle Position Event"
    load_responses()
    add_to_waitlist(event_name, _make_entry(event_name, 401))
    add_to_waitlist(event_name, _make_entry(event_name, 402))
    add_to_waitlist(event_name, _make_entry(event_name, 403))

    popped, original_index = promote_specific_from_waitlist(event_name, 402)
    assert original_index == 1
    assert [e.user_id for e in get_waitlist(event_name)] == [401, 403]

    restore_waitlist_entry(event_name, popped, position=original_index)

    assert [e.user_id for e in get_waitlist(event_name)] == [401, 402, 403]


def test_restore_waitlist_entry_noop_when_already_on_waitlist():
    event_name = "Rollback Noop Event"
    load_responses()
    add_to_waitlist(event_name, _make_entry(event_name, 301))

    restore_waitlist_entry(event_name, _make_entry(event_name, 301))

    assert [e.user_id for e in get_waitlist(event_name)] == [301]
