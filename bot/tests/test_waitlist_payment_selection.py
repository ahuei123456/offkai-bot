"""Waitlist privacy and promoted-attendee payment selection regressions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import event as events
from offkai_bot.data import response as responses
from offkai_bot.data.event import Event
from offkai_bot.interactions import (
    GatheringModal,
    PromotedPaymentModal,
    PromotedPaymentSelection,
    promote_waitlist_batch,
    render_custom_reply_sections,
    resend_registration_details,
    restore_payment_selections,
    send_signup_reply,
)

from .test_custom_signup import interaction, signup_continuation, submit_payment


@pytest.fixture
def custom_event():
    responses.RESPONSE_DATA_CACHE = {}
    event = Event(
        event_name="Synthetic Waitlist Payment",
        venue="Venue",
        address="Address",
        google_maps_link="",
        event_datetime=datetime.now(UTC) + timedelta(days=7),
        open=True,
        signup_form={
            "fields": ["preferred_name", "guests", "payment_method", "no_show"],
            "payment_methods": {"PayNow": "Synthetic organizer instructions"},
        },
    )
    events.EVENT_DATA_CACHE = [event]
    return event


@pytest.mark.parametrize("status", ["Waitlisted — attendance is not confirmed", "Attendance confirmed"])
def test_waitlist_reply_never_discloses_payment_instructions(custom_event, status):
    entry = responses.WaitlistEntry(
        user_id=123,
        username="Synthetic",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=custom_event.event_name,
        timestamp=datetime.now(UTC),
        payment_method="PayNow",
        no_show_agreed=True,
    )
    custom_event.signup_form["payment_instructions_jp"] = {"PayNow": "秘密の支払い案内"}
    with patch("offkai_bot.interactions.build_checkin_url", return_value="https://synthetic.invalid/pass"):
        text = "\n".join(render_custom_reply_sections(custom_event, entry, status))
    assert "Synthetic organizer instructions" not in text
    assert "秘密の支払い案内" not in text
    assert "PayNow" not in text
    assert "proof of payment" not in text
    assert "I paid" not in text


async def test_waitlist_signup_only_requests_agreement_not_payment(custom_event):
    custom_event.max_capacity = 0
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    view = signup_continuation(source)
    await view.continue_signup.callback(source)
    followup_modal = source.response.send_modal.call_args.args[0]
    assert followup_modal.payment_method_input is None
    assert followup_modal.no_show_input is not None
    assert source.user.send.await_count == 1
    assert "Please choose a payment method" not in source.user.send.call_args.args[0]
    assert "5 minutes" not in source.user.send.call_args.args[0]


@pytest.mark.parametrize("reason", ["closed", "deadline", "capacity", "group"])
async def test_waitlist_registration_needs_no_payment_choice(custom_event, reason):
    if reason == "closed":
        custom_event.open = False
    elif reason == "deadline":
        custom_event.event_deadline = datetime.now(UTC) - timedelta(seconds=1)
    else:
        custom_event.max_capacity = 1 if reason == "group" else 0
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "1" if reason == "group" else "0"
    modal.extras_names_input._value = "Guest" if reason == "group" else ""
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    second = await submit_payment(source)
    assert second.payment_method_input is None
    entry = responses.get_waitlist(custom_event.event_name)[0]
    assert entry.payment_method is None and entry.no_show_agreed
    assert "Synthetic organizer instructions" not in source.payment_target.response.send_message.call_args.args[0]


async def test_waitlist_without_agreement_saves_immediately(custom_event):
    custom_event.max_capacity = 0
    custom_event.signup_form["fields"].remove("no_show")
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    assert len(responses.get_waitlist(custom_event.event_name)) == 1
    assert responses.get_waitlist(custom_event.event_name)[0].payment_method is None
    assert "view" not in source.user.send.call_args.kwargs


async def test_capacity_change_during_agreement_starts_72_hour_choice_when_confirmed(custom_event):
    custom_event.max_capacity = 0
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    custom_event.max_capacity = 1
    await submit_payment(source)
    entry = responses.get_responses(custom_event.event_name)[0]
    assert entry.payment_method is None and entry.payment_selection_expires_at > datetime.now(UTC)
    reply = source.payment_target.response.send_message
    assert "72 hours" in reply.call_args.args[0]
    assert isinstance(reply.call_args.kwargs["view"], PromotedPaymentSelection)


async def test_capacity_becomes_full_after_payment_selection_suppresses_instructions(custom_event):
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    custom_event.max_capacity = 0
    await submit_payment(source)
    entry = responses.get_waitlist(custom_event.event_name)[0]
    assert entry.payment_method is None
    assert "Synthetic organizer instructions" not in source.payment_target.response.send_message.call_args.args[0]


@pytest.fixture
def queued_entry(custom_event):
    entry = responses.WaitlistEntry(
        user_id=123,
        username="Synthetic",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=custom_event.event_name,
        timestamp=datetime.now(UTC),
        no_show_agreed=True,
        display_name="Saved name",
        extras_names=["Guest"],
        drinks=["Tea"],
    )
    responses.RESPONSE_DATA_CACHE = {custom_event.event_name: {"attendees": [], "waitlist": [entry]}}
    events.EVENT_DATA_CACHE = [custom_event]
    return entry


@pytest.mark.parametrize("automatic", [False, True])
async def test_promotion_sends_persistent_72_hour_choice_without_payment_instructions(
    custom_event, queued_entry, automatic
):
    user = interaction(queued_entry.user_id).user
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    before = datetime.now(UTC)
    if automatic:
        await promote_waitlist_batch(custom_event, bot)
    else:
        with patch("offkai_bot.cogs.events.update_event_message", new=AsyncMock()):
            await EventsCog.promote.callback(
                EventsCog(bot), interaction(), custom_event.event_name, str(queued_entry.user_id)
            )
    entry = responses.get_responses(custom_event.event_name)[0]
    assert before + timedelta(hours=72) <= entry.payment_selection_expires_at <= datetime.now(UTC) + timedelta(hours=72)
    assert entry.timestamp == queued_entry.timestamp
    assert entry.payment_method is None and entry.no_show_agreed
    assert entry.extras_names == ["Guest"] and entry.drinks == ["Tea"]
    view = user.send.call_args.kwargs["view"]
    assert isinstance(view, PromotedPaymentSelection) and view.is_persistent()
    assert view.timeout is None
    assert "72 hours" in user.send.call_args.args[0] and "5 minutes" not in user.send.call_args.args[0]
    descriptions = "\n".join(e.description for e in user.send.call_args.kwargs["embeds"])
    assert "A spot has opened up" in descriptions
    assert "Synthetic organizer instructions" not in descriptions
    assert "proof of payment" not in descriptions


async def test_promoted_choice_survives_reload_and_completes_without_reregistering(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    original = PromotedPaymentSelection(custom_event, entry)
    responses.RESPONSE_DATA_CACHE = None
    bot = MagicMock(spec=discord.Client)
    restore_payment_selections(bot)
    restored = bot.add_view.call_args.args[0]
    assert restored.choose_payment.custom_id == original.choose_payment.custom_id
    assert restored.expires_at == entry.payment_selection_expires_at
    source = interaction(entry.user_id)
    source.guild = None
    source.message = MagicMock(spec=discord.Message, edit=AsyncMock())
    await restored.choose_payment.callback(source)
    modal = source.response.send_modal.call_args.args[0]
    assert modal.timeout == 72 * 60 * 60
    submitted = [
        {
            "type": 18,
            "component": {
                "type": 3,
                "custom_id": "payment_method",
                "values": ["PayNow"],
            },
        }
    ]
    await modal._scheduled_task(source, submitted, {})
    current = responses.get_responses(custom_event.event_name)
    assert len(current) == 1
    saved = current[0]
    assert saved.timestamp == queued_entry.timestamp and saved.extras_names == queued_entry.extras_names
    assert saved.payment_method == "PayNow" and saved.payment_selection_expires_at is None
    assert restored.is_finished() and restored.choose_payment.disabled
    source.message.edit.assert_awaited_once_with(view=restored)
    assert "Synthetic organizer instructions" in source.response.send_message.call_args.args[0]
    assert not await original.interaction_check(interaction(entry.user_id))
    responses.RESPONSE_DATA_CACHE = None
    assert responses.get_responses(custom_event.event_name)[0].payment_method == "PayNow"


@pytest.mark.parametrize("age_hours", [71, 72, 73])
async def test_promotion_deadline_is_checked_even_after_modal_was_opened(custom_event, queued_entry, age_hours):
    entry = responses.promote_waitlist_response(custom_event)
    view = PromotedPaymentSelection(custom_event, entry)
    modal = PromotedPaymentModal(view)
    modal.payment_method_input._values = ["PayNow"]
    source = interaction(entry.user_id)
    now = entry.payment_selection_expires_at - timedelta(hours=72 - age_hours)
    with (
        patch("offkai_bot.interactions.datetime") as clock,
        patch("offkai_bot.data.response.datetime") as storage_clock,
    ):
        clock.now.return_value = now
        storage_clock.now.return_value = now
        await modal.on_submit(source)
    saved = responses.get_responses(custom_event.event_name)[0]
    assert saved.payment_method == ("PayNow" if age_hours < 72 else None)
    if age_hours >= 72:
        assert "expired" in source.response.send_message.call_args.args[0]
        assert len(responses.get_responses(custom_event.event_name)) == 1


@pytest.mark.parametrize("change", ["wrong_owner", "withdrawn", "rejoined", "archived", "disabled_methods"])
async def test_promoted_choice_rejects_wrong_or_stale_registration(custom_event, queued_entry, change):
    entry = responses.promote_waitlist_response(custom_event)
    view = PromotedPaymentSelection(custom_event, entry)
    source = interaction(entry.user_id)
    if change == "wrong_owner":
        source.user.id = 999
    elif change == "withdrawn":
        responses.RESPONSE_DATA_CACHE[custom_event.event_name]["attendees"] = []
    elif change == "rejoined":
        entry.timestamp += timedelta(seconds=1)
    elif change == "archived":
        custom_event.archived = True
    else:
        custom_event.signup_form["payment_methods"] = {}
    assert not await view.interaction_check(source)
    assert entry.payment_method is None


async def test_payment_choice_storage_failure_is_retryable_and_atomic(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    view = PromotedPaymentSelection(custom_event, entry)
    modal = PromotedPaymentModal(view)
    modal.payment_method_input._values = ["PayNow"]
    source = interaction(entry.user_id)
    with patch("offkai_bot.data.response.atomic_write_json", side_effect=OSError("Synthetic write failure")):
        await modal.on_submit(source)
    assert responses.get_responses(custom_event.event_name)[0] is entry
    assert entry.payment_method is None and not view.is_finished()
    assert "could not be saved" in source.response.send_message.call_args.args[0]
    await modal.on_submit(interaction(entry.user_id))
    assert responses.get_responses(custom_event.event_name)[0].payment_method == "PayNow"


async def test_resend_does_not_extend_promotion_deadline_or_reveal_waitlist_payment(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    expiry = entry.payment_selection_expires_at
    user = interaction(entry.user_id).user
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    await resend_registration_details(custom_event, bot)
    assert user.send.call_args.kwargs["view"].expires_at == expiry
    assert entry.payment_selection_expires_at == expiry
    assert "Synthetic organizer instructions" not in "\n".join(
        e.description for e in user.send.call_args.kwargs["embeds"]
    )
    queued_entry.payment_method = "PayNow"
    responses.RESPONSE_DATA_CACHE[custom_event.event_name] = {"attendees": [], "waitlist": [queued_entry]}
    await resend_registration_details(custom_event, bot)
    assert "view" not in user.send.call_args.kwargs
    assert "Synthetic organizer instructions" not in user.send.call_args.args[0]


async def test_expired_choice_is_not_restored_or_extended(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    entry.payment_selection_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    bot = MagicMock(spec=discord.Client)
    restore_payment_selections(bot)
    bot.add_view.assert_not_called()
    send = AsyncMock()
    await send_signup_reply(send, custom_event, entry, "Attendance confirmed", "Confirmed")
    assert "view" not in send.call_args.kwargs
    assert entry.payment_method is None


async def test_legacy_selected_waitlist_method_is_only_disclosed_after_promotion(custom_event, queued_entry):
    queued_entry.payment_method = "PayNow"
    send = AsyncMock()
    await send_signup_reply(send, custom_event, queued_entry, "Waitlisted — attendance is not confirmed", "Waitlisted")
    assert "Synthetic organizer instructions" not in send.call_args.args[0]
    entry = responses.promote_waitlist_response(custom_event)
    await send_signup_reply(send, custom_event, entry, "Attendance confirmed", "Confirmed", promotion=True)
    assert entry.payment_method == "PayNow" and entry.payment_selection_expires_at is None
    assert "Synthetic organizer instructions" in send.call_args.args[0]
    assert "view" not in send.call_args.kwargs
