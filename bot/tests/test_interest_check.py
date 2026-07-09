"""Tests for the interest-check mode: modal, views, dispatch, templates, tally, reminders."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from offkai_bot.alerts.reminders import register_checkin_reminder, register_deadline_reminders
from offkai_bot.alerts.task import CloseOffkaiTask
from offkai_bot.data.event import Event, create_event_message
from offkai_bot.data.response import Response
from offkai_bot.errors import DuplicateResponseError, ResponseNotFoundError
from offkai_bot.event_actions import build_interest_check_tally, get_event_view, perform_close_event
from offkai_bot.interactions import (
    ClosedEvent,
    InterestCheckClosedEvent,
    InterestCheckEvent,
    InterestCheckModal,
    OpenEvent,
    ValidationError,
    validate_extra_people_input,
)

from offkai_bot.alerts import alerts

# asyncio_mode = "auto" runs the async tests here without an explicit mark;
# a module-level asyncio pytestmark would warn on this file's sync tests.

# --- Fixtures ---


def make_interest_event(
    *,
    event_name: str = "Interest Test",
    open_: bool = True,
    deadline_offset: timedelta = timedelta(days=7),
) -> Event:
    now = datetime.now(UTC)
    return Event(
        event_name=event_name,
        venue="TBD",
        address="TBD",
        google_maps_link="",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + deadline_offset,
        channel_id=456,
        thread_id=789,
        message_id=None,
        open=open_,
        archived=False,
        drinks=[],
        max_capacity=None,
        interest_check=True,
    )


def make_response(user_id: int, username: str, extra_people: int = 0, display_name: str | None = None) -> Response:
    return Response(
        user_id=user_id,
        username=username,
        extra_people=extra_people,
        behavior_confirmed=False,
        arrival_confirmed=False,
        event_name="Interest Test",
        timestamp=datetime.now(UTC),
        drinks=[],
        extras_names=[],
        display_name=display_name,
    )


@pytest.fixture
def mock_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.name = "TestUser"
    interaction.user.display_name = "Test Display"
    interaction.user.send = AsyncMock()
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.channel.id = 789
    interaction.channel.add_user = AsyncMock()
    interaction.channel.remove_user = AsyncMock()
    interaction.channel_id = 789
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.client = MagicMock(spec=discord.Client)
    return interaction


# --- validate_extra_people_input ---


def test_validate_extra_people_input_accepts_range():
    assert validate_extra_people_input("0") == 0
    assert validate_extra_people_input("5") == 5


@pytest.mark.parametrize("bad_input", ["6", "-1", "x", "", "1.5"])
def test_validate_extra_people_input_rejects_invalid(bad_input):
    with pytest.raises(ValidationError):
        validate_extra_people_input(bad_input)


# --- InterestCheckModal construction ---


async def test_interest_modal_custom_id_uses_short_prefix():
    event = make_interest_event()
    modal = InterestCheckModal(event=event)
    assert modal.custom_id == f"imodal_{event.event_name}"


async def test_interest_modal_custom_id_fits_discord_limit_for_max_length_name():
    from offkai_bot.util import MAX_EVENT_NAME_LENGTH

    event = make_interest_event(event_name="a" * MAX_EVENT_NAME_LENGTH)
    modal = InterestCheckModal(event=event)
    assert len(modal.custom_id) <= 100
    assert len(modal.title) <= 45


# --- InterestCheckModal.on_submit ---


@patch("offkai_bot.interactions._refresh_interest_check_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.update_rank")
@patch("offkai_bot.interactions.add_response")
async def test_interest_modal_submit_records_noncommittal_response(
    mock_add_response, mock_update_rank, mock_refresh, mock_interaction
):
    event = make_interest_event()
    modal = InterestCheckModal(event=event)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "2"

    await modal.on_submit(mock_interaction)

    mock_add_response.assert_called_once()
    recorded = mock_add_response.call_args[0][1]
    assert recorded.extra_people == 2
    assert recorded.behavior_confirmed is False
    assert recorded.arrival_confirmed is False
    assert recorded.drinks == []
    assert recorded.extras_names == []

    # Non-binding: no rank/milestone machinery, no DM.
    mock_update_rank.assert_not_called()
    mock_interaction.user.send.assert_not_called()

    # Ephemeral confirmation, user added to thread, live count refreshed.
    mock_interaction.response.send_message.assert_awaited_once()
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    mock_interaction.channel.add_user.assert_awaited_once_with(mock_interaction.user)
    mock_refresh.assert_awaited_once_with(mock_interaction.client, event)


@patch("offkai_bot.interactions._refresh_interest_check_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.add_response")
async def test_interest_modal_submit_rejects_invalid_extra_people(mock_add_response, mock_refresh, mock_interaction):
    modal = InterestCheckModal(event=make_interest_event())
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "9"

    await modal.on_submit(mock_interaction)

    mock_add_response.assert_not_called()
    mock_refresh.assert_not_called()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "between 0 and 5" in mock_interaction.response.send_message.call_args[0][0]


@pytest.mark.parametrize(
    "event",
    [
        make_interest_event(open_=False),
        make_interest_event(deadline_offset=timedelta(days=-1)),
    ],
    ids=["manually_closed", "past_deadline"],
)
@patch("offkai_bot.interactions._refresh_interest_check_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.add_response")
async def test_interest_modal_submit_rejects_closed_interest_check(
    mock_add_response, mock_refresh, mock_interaction, event
):
    modal = InterestCheckModal(event=event)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "2"

    await modal.on_submit(mock_interaction)

    mock_add_response.assert_not_called()
    mock_refresh.assert_not_awaited()
    mock_interaction.channel.add_user.assert_not_awaited()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "no longer accepting responses" in mock_interaction.response.send_message.call_args[0][0]
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@patch("offkai_bot.interactions._refresh_interest_check_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.add_response")
async def test_interest_modal_submit_duplicate_is_ephemeral_error(mock_add_response, mock_refresh, mock_interaction):
    event = make_interest_event()
    mock_add_response.side_effect = DuplicateResponseError(event.event_name, 123)
    modal = InterestCheckModal(event=event)
    modal.extra_people_input = MagicMock()
    modal.extra_people_input.value = "0"

    await modal.on_submit(mock_interaction)

    mock_refresh.assert_not_called()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "already submitted" in mock_interaction.response.send_message.call_args[0][0]
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# --- InterestCheckEvent.withdraw_interest ---


@patch("offkai_bot.interactions._refresh_interest_check_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.decrease_rank")
@patch("offkai_bot.interactions.promote_waitlist_batch", new_callable=AsyncMock)
@patch("offkai_bot.interactions.remove_response")
async def test_interest_withdraw_success_skips_rank_and_promotion(
    mock_remove_response, mock_promote, mock_decrease_rank, mock_refresh, mock_interaction
):
    event = make_interest_event()
    view = InterestCheckEvent(event)

    await view.withdraw_interest.callback(mock_interaction)

    mock_remove_response.assert_called_once_with(event.event_name, mock_interaction.user.id)
    mock_decrease_rank.assert_not_called()
    mock_promote.assert_not_awaited()
    mock_interaction.response.send_message.assert_awaited_once()
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    mock_interaction.channel.remove_user.assert_awaited_once_with(mock_interaction.user)
    mock_refresh.assert_awaited_once_with(mock_interaction.client, event)


@patch("offkai_bot.interactions._refresh_interest_check_message", new_callable=AsyncMock)
@patch("offkai_bot.interactions.remove_response")
async def test_interest_withdraw_not_registered(mock_remove_response, mock_refresh, mock_interaction):
    event = make_interest_event()
    mock_remove_response.side_effect = ResponseNotFoundError(event.event_name, 123)
    view = InterestCheckEvent(event)

    await view.withdraw_interest.callback(mock_interaction)

    mock_refresh.assert_not_awaited()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "have not registered interest" in mock_interaction.response.send_message.call_args[0][0]


# --- get_event_view dispatch (restart-persistence path) ---


async def test_get_event_view_open_interest_check():
    view = get_event_view(make_interest_event())
    assert isinstance(view, InterestCheckEvent)


async def test_get_event_view_closed_interest_check():
    view = get_event_view(make_interest_event(open_=False))
    assert isinstance(view, InterestCheckClosedEvent)


async def test_get_event_view_past_deadline_interest_check():
    view = get_event_view(make_interest_event(deadline_offset=timedelta(days=-1)))
    assert isinstance(view, InterestCheckClosedEvent)


async def test_get_event_view_regular_events_unchanged():
    regular = make_interest_event()
    regular.interest_check = False
    assert isinstance(get_event_view(regular), OpenEvent)
    regular.open = False
    assert isinstance(get_event_view(regular), ClosedEvent)


# --- create_event_message interest template ---


@patch("offkai_bot.data.event.get_responses")
def test_create_event_message_interest_template_shows_live_count(mock_get_responses):
    event = make_interest_event()
    mock_get_responses.return_value = [
        make_response(1, "alice", extra_people=2),
        make_response(2, "bob", extra_people=0),
    ]

    content = create_event_message(event)

    assert "Interest Check" in content
    assert "Interested so far (現在の興味あり人数)**: 4" in content
    # No binding-signup boilerplate.
    assert "split the bill" not in content
    assert "confirm your attendance" not in content
    # Placeholder venue details are omitted.
    assert "TBD" not in content
    assert "Tentative Date" in content


@patch("offkai_bot.data.event.get_responses")
def test_create_event_message_interest_template_count_updates(mock_get_responses):
    event = make_interest_event()

    mock_get_responses.return_value = []
    assert "Interested so far (現在の興味あり人数)**: 0" in create_event_message(event)

    mock_get_responses.return_value = [make_response(1, "alice", extra_people=1)]
    assert "Interested so far (現在の興味あり人数)**: 2" in create_event_message(event)


@patch("offkai_bot.data.event.get_responses")
def test_create_event_message_regular_event_unchanged(mock_get_responses):
    event = make_interest_event()
    event.interest_check = False

    content = create_event_message(event)

    mock_get_responses.assert_not_called()
    assert "Click the button below to confirm your attendance!" in content


# --- build_interest_check_tally / perform_close_event ---


@patch("offkai_bot.event_actions.get_responses")
def test_build_interest_check_tally_lists_names_and_total(mock_get_responses):
    event = make_interest_event()
    mock_get_responses.return_value = [
        make_response(1, "alice", extra_people=2, display_name="Alice"),
        make_response(2, "bob", extra_people=0),
    ]

    tally = build_interest_check_tally(event)

    assert "Interest check closed" in tally
    assert "**Total interested (興味あり合計)**: 4" in tally
    assert "- Alice (+2)" in tally
    assert "- bob" in tally


@patch("offkai_bot.event_actions.get_responses")
def test_build_interest_check_tally_empty(mock_get_responses):
    mock_get_responses.return_value = []

    tally = build_interest_check_tally(make_interest_event())

    assert "**Total interested (興味あり合計)**: 0" in tally


@patch("offkai_bot.event_actions.get_responses")
def test_build_interest_check_tally_truncates_long_response_list(mock_get_responses):
    mock_get_responses.return_value = [make_response(index, "a" * 100) for index in range(30)]

    tally = build_interest_check_tally(make_interest_event())

    assert len(tally) <= 2000
    assert "**Total interested (興味あり合計)**: 30" in tally
    assert tally.endswith("... (list truncated)")


@patch("offkai_bot.event_actions.get_responses")
@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.save_responses")
@patch("offkai_bot.event_actions.assign_attendee_numbers")
@patch("offkai_bot.event_actions.set_event_open_status")
async def test_perform_close_event_posts_tally_for_interest_check(
    mock_set_status,
    mock_assign_numbers,
    mock_save_responses,
    mock_save_event_data,
    mock_update_message,
    mock_fetch_thread,
    mock_get_responses,
):
    event = make_interest_event(open_=False)
    mock_set_status.return_value = event
    mock_assign_numbers.return_value = None
    mock_get_responses.return_value = [make_response(1, "alice", extra_people=1)]
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.send = AsyncMock()
    mock_fetch_thread.return_value = mock_thread

    client = MagicMock(spec=discord.Client)
    await perform_close_event(client, event.event_name)

    mock_assign_numbers.assert_not_called()
    assert event.max_attendee_number is None
    mock_thread.send.assert_awaited_once()
    sent = mock_thread.send.call_args[0][0]
    assert "Interest check closed" in sent
    assert "**Total interested (興味あり合計)**: 2" in sent


@patch("offkai_bot.event_actions.get_responses")
@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.save_responses")
@patch("offkai_bot.event_actions.assign_attendee_numbers")
@patch("offkai_bot.event_actions.set_event_open_status")
async def test_perform_close_interest_check_truncates_long_close_message(
    mock_set_status,
    mock_assign_numbers,
    mock_save_responses,
    mock_save_event_data,
    mock_update_message,
    mock_fetch_thread,
    mock_get_responses,
):
    event = make_interest_event(open_=False)
    mock_set_status.return_value = event
    mock_get_responses.return_value = [make_response(1, "alice", extra_people=1)]
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.send = AsyncMock()
    mock_fetch_thread.return_value = mock_thread
    close_msg = "x" * 3000

    await perform_close_event(MagicMock(spec=discord.Client), event.event_name, close_msg)

    sent = mock_thread.send.call_args[0][0]
    tally = build_interest_check_tally(event)
    assert len(sent) <= 2000
    assert sent.startswith(tally)
    assert sent == f"{tally}\n\n{close_msg[: 2000 - len(tally) - 2]}"


@patch("offkai_bot.event_actions.fetch_thread_for_event", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock)
@patch("offkai_bot.event_actions.save_event_data")
@patch("offkai_bot.event_actions.save_responses")
@patch("offkai_bot.event_actions.assign_attendee_numbers")
@patch("offkai_bot.event_actions.set_event_open_status")
async def test_perform_close_event_regular_event_without_msg_sends_nothing(
    mock_set_status,
    mock_assign_numbers,
    mock_save_responses,
    mock_save_event_data,
    mock_update_message,
    mock_fetch_thread,
):
    event = make_interest_event(open_=False)
    event.interest_check = False
    mock_set_status.return_value = event

    client = MagicMock(spec=discord.Client)
    await perform_close_event(client, event.event_name)

    mock_fetch_thread.assert_not_awaited()


# --- Reminder registration ---


def test_register_deadline_reminders_interest_check_only_auto_close(mock_thread):
    client = MagicMock(spec=discord.Client)
    event = make_interest_event(deadline_offset=timedelta(days=10))

    register_deadline_reminders(client, event, mock_thread)

    registered = [task for tasks in alerts._scheduled_tasks.values() for task in tasks]
    assert len(registered) == 1
    assert isinstance(registered[0], CloseOffkaiTask)


def test_register_deadline_reminders_regular_event_registers_pings(mock_thread):
    client = MagicMock(spec=discord.Client)
    event = make_interest_event(deadline_offset=timedelta(days=10))
    event.interest_check = False

    register_deadline_reminders(client, event, mock_thread)

    registered = [task for tasks in alerts._scheduled_tasks.values() for task in tasks]
    # Auto-close + 24h/3d/7d pings
    assert len(registered) == 4


def test_register_checkin_reminder_skipped_for_interest_check():
    client = MagicMock(spec=discord.Client)
    event = make_interest_event()

    register_checkin_reminder(client, event)

    assert not any(tasks for tasks in alerts._scheduled_tasks.values())
