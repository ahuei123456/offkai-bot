"""Tests for interactions.py: GatheringModal construction."""

from datetime import UTC, datetime, timedelta

import pytest

from offkai_bot.data.event import Event
from offkai_bot.interactions import (
    MODAL_TITLE_MAX_LENGTH,
    SIGNUP_MODAL_TIMEOUT_SECONDS,
    GatheringModal,
    ValidationError,
    resolve_submitted_display_name,
)
from offkai_bot.util import MAX_EVENT_NAME_LENGTH

pytestmark = pytest.mark.asyncio


def _make_event(event_name: str, *, drinks: list[str] | None = None) -> Event:
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
        drinks=drinks or [],
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


async def test_gathering_modal_custom_id_is_unique_per_instance():
    """discord.py routes modal submissions by custom_id alone, so ids must not be shared per event."""
    event = _make_event("Shared Event")
    first, second = GatheringModal(event=event), GatheringModal(event=event)
    assert first.custom_id != second.custom_id
    assert len(first.custom_id) <= 100


async def test_gathering_modal_times_out_so_dismissed_modals_are_released():
    """With unique custom_ids, only a timeout removes a modal the user closed without submitting."""
    modal = GatheringModal(event=_make_event("Shared Event"))
    assert modal.timeout == SIGNUP_MODAL_TIMEOUT_SECONDS


async def test_gathering_modal_title_unchanged_for_short_event_name():
    event_name = "Short Event"

    modal = GatheringModal(event=_make_event(event_name))

    assert modal.title == event_name


async def test_gathering_modal_has_preferred_name_and_discord_field_limits():
    no_drinks = GatheringModal(event=_make_event("No Drinks"))
    with_drinks = GatheringModal(event=_make_event("With Drinks", drinks=["Beer"]))

    assert [field.custom_id for field in no_drinks.children] == [
        "preferred_name",
        "extra_people",
        "behavior_arrival_confirm",
        "extras_names",
    ]
    assert len(no_drinks.children) == 4
    assert len(with_drinks.children) == 5
    assert no_drinks.preferred_name_input.required is False
    assert no_drinks.preferred_name_input.max_length == 32


async def test_combined_confirmation_accepts_case_and_surrounding_whitespace():
    modal = GatheringModal(event=_make_event("Confirmation"))

    modal._validate_confirmations("  YES ")

    with pytest.raises(ValidationError, match="confirm behavior and arrival"):
        modal._validate_confirmations("yep")


@pytest.mark.parametrize(
    ("submitted", "discord_name", "username", "expected"),
    [
        ("  Preferred 名  ", "Discord Nick", "username", "Preferred 名"),
        ("   ", "Discord Nick", "username", "Discord Nick"),
        ("", "  ", "username", "username"),
    ],
)
async def test_resolve_submitted_display_name(submitted, discord_name, username, expected):
    assert resolve_submitted_display_name(submitted, discord_name, username) == expected
