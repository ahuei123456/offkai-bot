"""Waitlist privacy and promoted-attendee payment selection regressions."""

import asyncio
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
    assert entry.payment_selection_demotes
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


async def test_new_deferred_signup_still_demotes_after_promotion_and_reload(custom_event):
    custom_event.max_capacity = 0
    source = interaction()
    signup = GatheringModal(event=custom_event)
    signup.extra_people_input._value = "0"
    signup.confirmation_input._value = "Yes"
    await signup.on_submit(source)
    await submit_payment(source)
    responses.RESPONSE_DATA_CACHE = None
    promoted = responses.promote_waitlist_response(custom_event, source.user.id)
    assert promoted.payment_selection_demotes
    expired = responses.expire_payment_selections(custom_event, promoted.payment_selection_expires_at)
    assert [entry.user_id for entry in expired] == [source.user.id]
    assert responses.get_responses(custom_event.event_name) == []


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
    assert entry.payment_selection_demotes
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
@pytest.mark.parametrize("saved_method", [None, "Removed method"])
async def test_promotion_sends_persistent_72_hour_choice_without_payment_instructions(
    custom_event, queued_entry, automatic, saved_method
):
    queued_entry.payment_method = saved_method
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
    assert modal.timeout == 300  # Only the popup expires; the persistent choice remains available for 72 hours.
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
    assert not saved.payment_selection_demotes
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


async def test_sending_legacy_confirmation_does_not_repair_registration(custom_event, queued_entry):
    queued_entry.payment_method = "PayNow"
    entry = responses.promote_waitlist_response(custom_event)
    entry.payment_method = None
    entry.payment_selection_expires_at = None  # Simulate a legacy confirmed record.
    send = AsyncMock()
    with patch("offkai_bot.data.response.atomic_write_json") as write:
        await send_signup_reply(send, custom_event, entry, "Attendance confirmed", "Confirmed")
    write.assert_not_called()
    assert responses.get_responses(custom_event.event_name)[0] is entry
    assert entry.payment_selection_expires_at is None
    send.assert_awaited_once()


async def test_organizer_resend_reports_dm_failure_without_thread_ping(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    user = interaction(entry.user_id).user
    user.send.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "DM blocked")
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    with patch("offkai_bot.interactions.notify_dm_failure", new_callable=AsyncMock) as notice:
        sent, failed = await resend_registration_details(custom_event, bot)
    assert sent == [] and failed == [entry.username]
    notice.assert_not_awaited()


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


async def test_legacy_selected_waitlist_method_remains_usable_after_promotion(custom_event, queued_entry):
    queued_entry.payment_method = "PayNow"
    send = AsyncMock()
    await send_signup_reply(send, custom_event, queued_entry, "Waitlisted — attendance is not confirmed", "Waitlisted")
    assert "Synthetic organizer instructions" not in send.call_args.args[0]
    entry = responses.promote_waitlist_response(custom_event)
    await send_signup_reply(send, custom_event, entry, "Attendance confirmed", "Confirmed", promotion=True)
    assert entry.payment_method == "PayNow" and entry.payment_selection_expires_at is None
    assert "Synthetic organizer instructions" in send.call_args.args[0]
    assert "view" not in send.call_args.kwargs


async def test_concurrent_popups_commit_only_one_choice(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    custom_event.signup_form["payment_methods"]["Cash"] = "Cash instructions"
    sources = [interaction(entry.user_id), interaction(entry.user_id)]
    modals = [PromotedPaymentModal(PromotedPaymentSelection(custom_event, entry)) for _ in sources]
    for modal, method in zip(modals, ["PayNow", "Cash"], strict=True):
        modal.payment_method_input._values = [method]
    await asyncio.gather(*(modal.on_submit(source) for modal, source in zip(modals, sources, strict=True)))
    saved = responses.get_responses(custom_event.event_name)[0]
    assert saved.payment_method == "PayNow"
    assert saved.payment_selection_expires_at is None
    assert "expired" in sources[1].response.send_message.call_args.args[0]


async def test_concurrent_manual_and_automatic_promotion_do_not_reset_choice(custom_event, queued_entry):
    user = interaction(queued_entry.user_id).user
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fetch_user(user_id):
        entered.set()
        await release.wait()
        return user

    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(side_effect=fetch_user))
    with patch("offkai_bot.cogs.events.update_event_message", new=AsyncMock()):
        manual = asyncio.create_task(
            EventsCog.promote.callback(
                EventsCog(bot), interaction(), custom_event.event_name, str(queued_entry.user_id)
            )
        )
        await entered.wait()
        saved = responses.get_responses(custom_event.event_name)[0]
        expiry = saved.payment_selection_expires_at
        assert await promote_waitlist_batch(custom_event, bot) == []
        release.set()
        await manual
    assert responses.get_responses(custom_event.event_name) == [saved]
    assert saved.payment_selection_expires_at == expiry
    user.send.assert_awaited_once()


async def test_concurrent_automatic_batches_respect_group_capacity(custom_event, queued_entry):
    from dataclasses import replace

    custom_event.max_capacity = 3
    responses.add_to_waitlist(custom_event.event_name, replace(queued_entry, user_id=456))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fetch_user(user_id):
        entered.set()
        await release.wait()
        return interaction(user_id).user

    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(side_effect=fetch_user))
    first = asyncio.create_task(promote_waitlist_batch(custom_event, bot))
    await entered.wait()  # First group is committed, but its DM is still pending.
    assert await promote_waitlist_batch(custom_event, bot) == []
    release.set()
    assert await first == [queued_entry.user_id]
    assert sum(1 + entry.extra_people for entry in responses.get_responses(custom_event.event_name)) == 2
    assert [entry.user_id for entry in responses.get_waitlist(custom_event.event_name)] == [456]


async def test_old_popup_cannot_complete_a_new_promotion_window(custom_event, queued_entry):
    old = responses.promote_waitlist_response(custom_event)
    modal = PromotedPaymentModal(PromotedPaymentSelection(custom_event, old))
    modal.payment_method_input._values = ["PayNow"]
    responses.remove_response(custom_event.event_name, old.user_id)
    responses.add_to_waitlist(custom_event.event_name, queued_entry)
    current = responses.promote_waitlist_response(custom_event)
    assert current.timestamp == old.timestamp
    assert current.payment_selection_expires_at != old.payment_selection_expires_at
    source = interaction(old.user_id)
    await modal.on_submit(source)
    assert "expired" in source.response.send_message.call_args.args[0]
    assert responses.get_responses(custom_event.event_name)[0] is current
    assert current.payment_method is None


async def test_renamed_method_offers_new_choice_and_resend_does_not_extend_it(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    selected = responses.complete_payment_selection(
        custom_event.event_name, entry.user_id, entry.timestamp, entry.payment_selection_expires_at, "PayNow"
    )
    custom_event.signup_form["payment_methods"] = {"PayNow (SG)": "Updated organizer instructions"}
    user = interaction(selected.user_id).user
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    send = user.send
    await resend_registration_details(custom_event, bot)
    current = responses.get_responses(custom_event.event_name)[0]
    assert current.payment_method is None
    assert current.timestamp == queued_entry.timestamp and current.extras_names == queued_entry.extras_names
    view = send.call_args.kwargs["view"]
    assert view.expires_at == current.payment_selection_expires_at
    deadline = current.payment_selection_expires_at
    await resend_registration_details(custom_event, bot)
    assert responses.get_responses(custom_event.event_name)[0].payment_selection_expires_at == deadline
    source = interaction(entry.user_id)
    modal = PromotedPaymentModal(view)
    modal.payment_method_input._values = ["PayNow (SG)"]
    await modal.on_submit(source)
    assert responses.get_responses(custom_event.event_name)[0].payment_method == "PayNow (SG)"
    assert "Updated organizer instructions" in source.response.send_message.call_args.args[0]


async def test_renamed_method_write_failure_preserves_selected_registration(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    selected = responses.complete_payment_selection(
        custom_event.event_name, entry.user_id, entry.timestamp, entry.payment_selection_expires_at, "PayNow"
    )
    custom_event.signup_form["payment_methods"] = {"Replacement": "New instructions"}
    user = interaction(selected.user_id).user
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    with patch("offkai_bot.data.response.atomic_write_json", side_effect=OSError("Synthetic failure")):
        sent, failed = await resend_registration_details(custom_event, bot)
    assert sent == [] and failed == [selected.username]
    assert responses.get_responses(custom_event.event_name)[0] is selected
    assert selected.payment_method == "PayNow" and selected.payment_selection_expires_at is None
    user.send.assert_not_awaited()
    bot.fetch_user.assert_awaited_once_with(selected.user_id)


async def test_legacy_confirmed_missing_method_can_choose_before_upload(custom_event, queued_entry):
    queued_entry.payment_method = "PayNow"
    entry = responses.promote_waitlist_response(custom_event)
    entry.payment_method = None
    entry.payment_selection_expires_at = None  # Simulate a legacy confirmed record.
    assert entry.payment_selection_expires_at is None
    responses.save_responses()
    user = interaction(entry.user_id).user
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    send = user.send
    await resend_registration_details(custom_event, bot)
    current = responses.get_responses(custom_event.event_name)[0]
    assert current.payment_selection_expires_at > datetime.now(UTC)
    assert send.call_args.kwargs["view"].expires_at == current.payment_selection_expires_at
    source = interaction(entry.user_id)
    modal = PromotedPaymentModal(send.call_args.kwargs["view"])
    modal.payment_method_input._values = ["PayNow"]
    await modal.on_submit(source)
    assert responses.get_responses(custom_event.event_name)[0].payment_method == "PayNow"


@pytest.mark.parametrize("invalid", [False, True])
async def test_button_dispatch_runs_owner_check_once(custom_event, queued_entry, invalid):
    entry = responses.promote_waitlist_response(custom_event)
    view = PromotedPaymentSelection(custom_event, entry)
    source = interaction(999 if invalid else entry.user_id)
    with patch("offkai_bot.interactions.get_responses", wraps=responses.get_responses) as lookup:
        await view._scheduled_task(view.choose_payment, source)
        assert lookup.call_count == 1
    if invalid:
        source.response.send_modal.assert_not_awaited()
        source.response.send_message.assert_awaited_once()
    else:
        source.response.send_modal.assert_awaited_once()


async def test_popup_timeout_does_not_end_or_extend_the_72_hour_choice(custom_event, queued_entry):
    entry = responses.promote_waitlist_response(custom_event)
    view = PromotedPaymentSelection(custom_event, entry)
    first = interaction(entry.user_id)
    await view._scheduled_task(view.choose_payment, first)
    popup = first.response.send_modal.call_args.args[0]
    assert popup.timeout == 300
    popup.stop()
    second = interaction(entry.user_id)
    await view._scheduled_task(view.choose_payment, second)
    assert second.response.send_modal.call_args.args[0] is not popup
    assert not view.is_finished()
    assert view.expires_at == entry.payment_selection_expires_at


@pytest.mark.parametrize("path", ["automatic", "manual", "resend"])
async def test_failed_payment_dm_reuses_enable_dms_notice(custom_event, queued_entry, path):
    user = interaction(queued_entry.user_id).user
    user.send.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "DM blocked")
    bot = MagicMock(spec=discord.Client, fetch_user=AsyncMock(return_value=user))
    thread = MagicMock(spec=discord.Thread, archived=False, locked=False, send=AsyncMock())
    with (
        patch("offkai_bot.event_actions.fetch_thread_for_event", new=AsyncMock(return_value=thread)),
        patch("offkai_bot.cogs.events.update_event_message", new=AsyncMock()),
    ):
        if path == "automatic":
            await promote_waitlist_batch(custom_event, bot)
        elif path == "manual":
            await EventsCog.promote.callback(EventsCog(bot), interaction(), custom_event.event_name, str(user.id))
        else:
            responses.promote_waitlist_response(custom_event)
            await resend_registration_details(custom_event, bot)
    if path == "resend":
        thread.send.assert_not_awaited()
        assert responses.get_responses(custom_event.event_name)[0].payment_selection_expires_at is not None
        return
    thread.send.assert_awaited_once()
    text = thread.send.call_args.args[0]
    assert f"<@{user.id}>" in text
    assert "I couldn't send you a DM. Please enable DMs from this server" in text
    assert "resend your confirmation" in text
    assert "restart registration" not in text
    assert "Synthetic organizer instructions" not in text
    assert "https://" not in text
    assert responses.get_responses(custom_event.event_name)[0].payment_selection_expires_at is not None


@pytest.mark.parametrize("state", ["locked", "archived", "event_archived", "send_fails"])
async def test_dm_recovery_respects_thread_state_and_failure(custom_event, state):
    from offkai_bot.interactions import notify_dm_failure

    thread = MagicMock(spec=discord.Thread, archived=state == "archived", locked=state == "locked", send=AsyncMock())
    custom_event.archived = state == "event_archived"
    if state == "send_fails":
        thread.send.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "No access")
    with patch("offkai_bot.event_actions.fetch_thread_for_event", new=AsyncMock(return_value=thread)):
        await notify_dm_failure(MagicMock(spec=discord.Client), custom_event, 123)
    thread.edit.assert_not_called()
    assert thread.send.await_count == (1 if state == "send_fails" else 0)
