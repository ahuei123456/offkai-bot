"""Archiving freezes pending signup flows and replaces mutable event controls."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot import event_actions
from offkai_bot.data.response import get_responses, get_waitlist
from offkai_bot.interactions import (
    ArchivedEvent,
    GatheringModal,
    InterestCheckEvent,
    InterestCheckModal,
    PaymentModal,
    SignupContinuation,
    start_signup,
)

pytestmark = pytest.mark.asyncio


def interaction():
    value = MagicMock(spec=discord.Interaction)
    value.user = MagicMock(spec=discord.Member, id=123, name="Registrant")
    value.user.send = AsyncMock()
    value.response.is_done.return_value = False
    value.response.send_message = AsyncMock()
    value.response.send_modal = AsyncMock()
    value.response.defer = AsyncMock()
    value.followup.send = AsyncMock()
    return value


@pytest.mark.parametrize("final", [False, True])
async def test_pending_signup_rejects_archive_before_persisting(sample_event_list, final):
    event = sample_event_list[0]
    modal = GatheringModal(event=event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    if final:
        modal._submitted_answers = ("", "0", "Yes", "N/A", "")
        modal.reply_in_dm = True
    event.archived = True
    source = interaction()

    assert await modal._submit(source, final=final) is False

    assert get_responses(event.event_name) == []
    assert get_waitlist(event.event_name) == []
    assert source.response.send_message.await_count == 1


async def test_archived_event_rejects_new_signup(sample_event_list):
    event = sample_event_list[0]
    event.archived = True
    source = interaction()

    await start_signup(source, event)

    source.response.send_modal.assert_not_awaited()
    assert "archived" in source.response.send_message.call_args.args[0]


async def test_pending_payment_and_continuation_reject_archive(sample_event_list):
    event = sample_event_list[0]
    event.signup_form = {"fields": ["payment_method"], "payment_methods": {"Cash": "Bring cash"}}
    signup = GatheringModal(event=event)
    signup._submitted_answers = ("", "0", "Yes", "N/A", "")
    view = SignupContinuation(signup, 123)
    payment = PaymentModal(view)
    event.archived = True
    source = interaction()

    assert await view.interaction_check(source) is False
    source.response.send_message.reset_mock()
    await payment.on_submit(source)

    assert get_responses(event.event_name) == []
    assert get_waitlist(event.event_name) == []
    assert "archived" in source.response.send_message.call_args.args[0]


async def test_archived_interest_rejects_pending_modal_and_old_buttons(sample_event_list):
    event = sample_event_list[0]
    event.interest_check = True
    modal = InterestCheckModal(event=event)
    modal.extra_people_input._value = "0"
    old_view = InterestCheckEvent(event)
    event.archived = True
    source = interaction()

    await modal.on_submit(source)
    await old_view.register_interest.callback(source)
    with patch("offkai_bot.interactions.remove_response") as remove:
        await old_view.withdraw_interest.callback(source)
    remove.assert_not_called()
    source.response.send_modal.assert_not_awaited()
    assert get_responses(event.event_name) == []
    assert source.response.send_message.await_count == 3


@pytest.mark.parametrize("interest_check", [False, True])
@pytest.mark.parametrize("open_status", [False, True])
async def test_archived_message_update_replaces_mutation_controls(sample_event_list, interest_check, open_status):
    event = sample_event_list[0]
    event.interest_check = interest_check
    event.open = open_status
    event.archived = True
    message = MagicMock(spec=discord.Message, edit=AsyncMock())
    client = MagicMock(spec=discord.Client)
    thread = MagicMock(spec=discord.Thread)
    with (
        patch("offkai_bot.event_actions.fetch_thread_for_event", return_value=thread),
        patch("offkai_bot.event_actions._fetch_event_message", return_value=message),
    ):
        await event_actions.update_event_message(client, event)

    view = message.edit.call_args.kwargs["view"]
    assert isinstance(view, ArchivedEvent)
    assert view.is_persistent()
    assert [item.custom_id for item in view.children] == ["count_button"]
