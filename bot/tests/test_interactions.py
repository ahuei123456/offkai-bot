"""Tests for interactions.py: GatheringModal construction."""

from datetime import UTC, datetime, timedelta

import pytest
from offkai_bot.data.event import Event
from offkai_bot.interactions import MODAL_TITLE_MAX_LENGTH, GatheringModal
from offkai_bot.util import MAX_EVENT_NAME_LENGTH

pytestmark = pytest.mark.asyncio


def _make_event(event_name: str) -> Event:
    now = datetime.now(UTC)
    return Event(
        event_name=event_name,
        venue="Test Venue",
        address="123 Test St",
        google_maps_link="https://maps.google.com/test",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=789,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=None,
    )


async def test_gathering_modal_title_truncated_for_long_event_name():
    """An event name valid for the custom_id (<= MAX_EVENT_NAME_LENGTH) can still exceed
    Discord's 45-character modal title limit; the modal must truncate the title rather
    than pass the raw name through, or sending the modal fails."""
    event_name = "a" * MAX_EVENT_NAME_LENGTH
    assert len(event_name) > MODAL_TITLE_MAX_LENGTH  # sanity check for the scenario under test

    modal = GatheringModal(event=_make_event(event_name))

    assert len(modal.title) <= MODAL_TITLE_MAX_LENGTH
    assert modal.custom_id == f"modal_{event_name}"


async def test_gathering_modal_title_unchanged_for_short_event_name():
    event_name = "Short Event"

    modal = GatheringModal(event=_make_event(event_name))

    assert modal.title == event_name
