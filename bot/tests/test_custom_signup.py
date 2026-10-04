"""Focused custom signup regression, with all Discord delivery mocked."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import event as events
from offkai_bot.data import response as responses
from offkai_bot.data.event import Event, create_event_message
from offkai_bot.interactions import GatheringModal, promote_waitlist_batch, start_signup
from offkai_bot.signup_setup import SignupSetup
from offkai_bot.util import build_checkin_token


@pytest.fixture
def custom_event():
    return Event(
        event_name="Synthetic Custom",
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


def interaction(user_id=191524132624531458):
    value = MagicMock(spec=discord.Interaction)
    value.user = MagicMock(spec=discord.Member)
    value.user.id = user_id
    value.user.name = "Synthetic"
    value.user.display_name = "Discord Name"
    value.user.send = AsyncMock()
    value.user.roles = [MagicMock(name="role")]
    value.user.roles[0].name = "Offkai Organizer"
    value.channel = MagicMock(spec=discord.TextChannel)
    value.guild = MagicMock(spec=discord.Guild)
    value.response.send_message = AsyncMock()
    value.response.edit_message = AsyncMock()
    value.response.send_modal = AsyncMock()
    value.response.defer = AsyncMock()
    value.followup.send = AsyncMock()
    return value


@pytest.mark.parametrize("outcome", ["confirmed", "closed", "deadline", "capacity", "group_exceeds"])
@pytest.mark.parametrize("dm_fails", [False, True])
async def test_custom_signup_all_outcomes_and_fallback(custom_event, outcome, dm_fails):
    events.EVENT_DATA_CACHE = [custom_event]
    responses.RESPONSE_DATA_CACHE = {}
    if outcome == "closed":
        custom_event.open = False
    if outcome == "deadline":
        custom_event.event_deadline = datetime.now(UTC) - timedelta(minutes=1)
    if outcome == "capacity":
        custom_event.max_capacity = 0
    if outcome == "group_exceeds":
        custom_event.max_capacity = 1
    source = interaction()
    if dm_fails:
        source.user.send.side_effect = discord.Forbidden(MagicMock(status=403), "DM blocked")
    modal = GatheringModal(event=custom_event, payment_method="PayNow")
    modal.preferred_name_input._value = "Recorded Name"
    modal.extra_people_input._value = "1"
    modal.extras_names_input._value = "Guest"
    modal.confirmation_input._value = " Yes "
    token = build_checkin_token(source.user.id, custom_event.event_name, "synthetic-test-key")
    link = f"https://synthetic.invalid/?token={token}"
    with patch("offkai_bot.interactions.build_checkin_url", return_value=link):
        await modal.on_submit(source)
    entry = (
        responses.get_responses(custom_event.event_name)
        if outcome == "confirmed"
        else responses.get_waitlist(custom_event.event_name)
    )[0]
    assert entry.payment_method == "PayNow"
    assert entry.no_show_agreed is True
    payload = (source.response.send_message if dm_fails else source.user.send).call_args.args[0]
    assert "Synthetic organizer instructions" in payload
    assert link in payload
    assert "Recorded Name" in payload and "Guest" in payload
    assert "no-refund" in payload
    assert ("Attendance confirmed" in payload) == (outcome == "confirmed")
    # Persisted answers survive a real cache reload.
    responses.RESPONSE_DATA_CACHE = None
    reloaded = (
        responses.get_responses(custom_event.event_name)
        if outcome == "confirmed"
        else responses.get_waitlist(custom_event.event_name)
    )[0]
    assert reloaded.payment_method == "PayNow" and reloaded.no_show_agreed


async def test_field_selection_payment_entry_and_yes_validation(custom_event):
    source = interaction()
    await start_signup(source, custom_event)
    view = source.response.send_message.call_args.kwargs["view"]
    assert source.response.send_message.call_args.kwargs["ephemeral"]
    assert [o.label for o in view.children[0].options] == ["PayNow"]
    custom_event.signup_form["fields"] = ["no_show"]
    custom_event.signup_form["payment_methods"] = {}
    modal = GatheringModal(event=custom_event)
    assert len(modal.children) == 1
    modal.confirmation_input._value = "No"
    responses.RESPONSE_DATA_CACHE = {}
    await modal.on_submit(source)
    assert responses.get_responses(custom_event.event_name) == []
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    saved = responses.get_responses(custom_event.event_name)[0]
    assert saved.extra_people == 0 and saved.extras_names == [] and saved.no_show_agreed


async def test_setup_private_draft_requires_instructions_and_cancel_creates_nothing():
    create = AsyncMock()
    source = interaction(42)
    setup = SignupSetup(42, [], create)
    assert await setup.interaction_check(source)
    assert not await setup.interaction_check(interaction(43))
    setup.fields = ["payment_method", "no_show"]
    setup.methods = ["PayNow"]
    with pytest.raises(ValueError, match="instructions"):
        setup.configuration()
    setup.instructions["PayNow"] = "Organizer text"
    assert setup.configuration()["payment_methods"] == {"PayNow": "Organizer text"}
    await setup.cancel.callback(source)
    create.assert_not_awaited()
    assert setup.finished


async def test_setup_publish_uses_selected_configuration():
    source = interaction(42)
    create = AsyncMock()
    setup = SignupSetup(42, [], create)
    setup.fields = ["payment_method"]
    setup.methods = ["PayPal"]
    setup.instructions["PayPal"] = "Organizer text"
    await setup.publish.callback(source)
    create.assert_awaited_once_with(
        {"fields": ["payment_method"], "payment_methods": {"PayPal": "Organizer text"}}, source
    )


async def test_automatic_and_manual_promotions_preserve_custom_answers(custom_event):
    events.EVENT_DATA_CACHE = [custom_event]
    responses.RESPONSE_DATA_CACHE = {}
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
    bot = MagicMock()
    bot.fetch_user = AsyncMock(return_value=interaction().user)
    for automatic in [True, False]:
        responses.RESPONSE_DATA_CACHE = {custom_event.event_name: {"attendees": [], "waitlist": [entry]}}
        if automatic:
            assert await promote_waitlist_batch(custom_event, bot) == [123]
        else:
            with patch("offkai_bot.cogs.events.update_event_message", new=AsyncMock()):
                await EventsCog.promote.callback(EventsCog(bot), interaction(), custom_event.event_name, "123")
        saved = responses.get_responses(custom_event.event_name)[0]
        assert saved.payment_method == "PayNow" and saved.no_show_agreed


def test_legacy_defaults_and_custom_announcement(custom_event):
    legacy = {"user_id": 123, "username": "Synthetic"}
    assert responses._parse_response_from_dict(legacy, "Legacy").payment_method is None
    assert responses._parse_waitlist_entry_from_dict(legacy, "Legacy").no_show_agreed is False
    assert "4000" not in create_event_message(custom_event)
    assert "Payment instructions are supplied at signup" in create_event_message(custom_event)
    custom_event.signup_form = None
    assert "4000" in create_event_message(custom_event)


def test_event_configuration_survives_reload(custom_event, mock_paths):
    events.EVENT_DATA_CACHE = [custom_event]
    events.save_event_data()
    events.EVENT_DATA_CACHE = None
    assert events.get_event(custom_event.event_name).signup_form == custom_event.signup_form
    with open(mock_paths["events"]) as file:
        assert json.load(file)[0]["signup_form"] == custom_event.signup_form


async def test_synthetic_cross_stack_fixture(custom_event, tmp_path):
    """Produce real bot signup records for the frontend's optional integration run."""
    import os
    from pathlib import Path

    from offkai_bot.data.encoders import DataclassJSONEncoder

    fixture_dir = Path(os.environ.get("OFFKAI_SYNTHETIC_OUTPUT", str(tmp_path)))
    fixture_dir.mkdir(parents=True, exist_ok=True)
    events.EVENT_DATA_CACHE = []
    responses.RESPONSE_DATA_CACHE = {}
    replies = {}
    for index, name in enumerate(["Synthetic Confirmed", "Synthetic Waitlist"]):
        event = Event(
            event_name=name,
            venue="Synthetic Venue",
            address="Synthetic Address",
            google_maps_link="",
            event_datetime=custom_event.event_datetime,
            open=index == 0,
            signup_form=custom_event.signup_form,
        )
        events.EVENT_DATA_CACHE.append(event)
        source = interaction()
        modal = GatheringModal(event=event, payment_method="PayNow")
        modal.preferred_name_input._value = "Recorded name"
        modal.extra_people_input._value = "1"
        modal.extras_names_input._value = "Guest"
        modal.confirmation_input._value = "Yes"
        token = build_checkin_token(source.user.id, name, "synthetic-test-key")
        url = f"https://synthetic.invalid/?token={token}"
        with patch("offkai_bot.interactions.build_checkin_url", return_value=url):
            await modal.on_submit(source)
        reply = source.user.send.call_args.args[0]
        assert "Synthetic organizer instructions" in reply and token in reply
        replies[name] = {"token": token, "reply": reply}
    for filename, value in [
        ("events.json", events.EVENT_DATA_CACHE),
        ("responses.json", responses.RESPONSE_DATA_CACHE),
        ("replies.json", replies),
    ]:
        (fixture_dir / filename).write_text(json.dumps(value, cls=DataclassJSONEncoder))


async def test_long_custom_reply_is_one_embed_message(custom_event):
    custom_event.event_name = "🎉" * 90
    custom_event.signup_form["payment_methods"]["PayNow"] = "Instructions " + "x" * 987
    events.EVENT_DATA_CACHE = [custom_event]
    responses.RESPONSE_DATA_CACHE = {}
    source = interaction()
    modal = GatheringModal(event=custom_event, payment_method="PayNow")
    modal.preferred_name_input._value = "N" * 32
    modal.extra_people_input._value = "5"
    modal.extras_names_input._value = ",".join(["G" * 31] * 5)
    modal.confirmation_input._value = "Yes"
    token = build_checkin_token(source.user.id, custom_event.event_name, "synthetic-test-key")
    link = "https://synthetic.invalid/" + "a" * 100 + "/?token=" + token
    with patch("offkai_bot.interactions.build_checkin_url", return_value=link):
        await modal.on_submit(source)
    source.user.send.assert_awaited_once()
    description = source.user.send.call_args.kwargs["embed"].description
    assert len(description) > 2000
    assert len(description) <= 4096
    assert link in description and "Instructions" in description
