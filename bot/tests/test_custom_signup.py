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
from offkai_bot.interactions import GatheringModal, promote_waitlist_batch, render_custom_reply_sections, start_signup
from offkai_bot.signup_setup import InstructionModal, SignupSetup
from offkai_bot.util import build_checkin_token


@pytest.fixture
def custom_event():
    responses.RESPONSE_DATA_CACHE = {}
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


def signup_continuation(source):
    for sender in (source.followup.send, source.user.send, source.response.send_message):
        for call in reversed(sender.call_args_list):
            if "view" in call.kwargs:
                return call.kwargs["view"]
    raise AssertionError("Signup continuation was not sent")


async def submit_payment(source, values=None, agreement=" Yes ", target=None):
    """Submit the real second modal from the DM or private channel continuation."""
    view = signup_continuation(source)
    target = target or source
    await view.continue_signup.callback(target)
    payment = target.response.send_modal.call_args.args[0]
    submitted = []
    if payment.payment_method_input is not None:
        submitted.append(
            {
                "type": 18,
                "component": {
                    "type": 3,
                    "custom_id": "payment_method",
                    "values": ["PayNow"] if values is None else values,
                },
            }
        )
    if payment.no_show_input is not None:
        submitted.append({"type": 1, "components": [{"type": 4, "custom_id": "no_show_agreement", "value": agreement}]})
    target.response.send_message.reset_mock()
    await payment._scheduled_task(target, submitted, {})
    return payment


async def complete_signup(modal, source):
    await modal.on_submit(source)
    await submit_payment(source)


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
        await complete_signup(modal, source)
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
    assert "Drinks:" not in payload and "飲み物:" not in payload
    assert f"Please provide proof of payment on the RSVP Page.\n🔗 RSVP Page / QR Code: {link}" in payload
    assert f"RSVPページで支払い証明をアップロードしてください。\n🔗 RSVPページ / QRコード: {link}" in payload
    assert payload.count(link) == 2 and payload.count("Synthetic organizer instructions") == 1
    assert ("✅ 参加確定" in payload) == (outcome == "confirmed")
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
    modal = source.response.send_modal.call_args.args[0]
    source.response.send_message.assert_not_awaited()
    assert all(isinstance(child, discord.ui.TextInput) for child in modal.children)
    custom_event.signup_form["fields"] = ["no_show"]
    custom_event.signup_form["payment_methods"] = {}
    modal = GatheringModal(event=custom_event)
    assert len(modal.children) == 1
    modal.confirmation_input._value = "No"
    responses.RESPONSE_DATA_CACHE = {}
    await modal.on_submit(source)
    assert responses.get_responses(custom_event.event_name) == []
    modal.confirmation_input._value = "Yes"
    await complete_signup(modal, source)
    saved = responses.get_responses(custom_event.event_name)[0]
    assert saved.extra_people == 0 and saved.extras_names == [] and saved.no_show_agreed


@pytest.mark.parametrize("open_event", [True, False])
async def test_two_modal_dispatch_persists_only_after_payment_and_policy(custom_event, open_event):
    custom_event.open = open_event
    responses.RESPONSE_DATA_CACHE = {}
    source = interaction()
    await start_signup(source, custom_event)
    modal = source.response.send_modal.call_args.args[0]
    payload = modal.to_dict()
    assert len(payload["components"]) == 4
    assert all(component["type"] == 1 for component in payload["components"])

    # Use Discord's real modal dispatch/decoding for both old text rows and the new Label/Select.
    submitted = [
        {"type": 1, "components": [{"type": 4, "custom_id": custom_id, "value": value}]}
        for custom_id, value in [
            ("preferred_name", "Recorded Name"),
            ("extra_people", "1"),
            ("behavior_arrival_confirm", "Yes"),
            ("extras_names", "Guest"),
        ]
    ]
    with (
        patch("offkai_bot.interactions.build_checkin_url", return_value="https://synthetic.invalid/pass"),
        patch("offkai_bot.interactions.update_rank") as update_rank,
    ):
        await modal._scheduled_task(source, submitted, {})
        assert responses.get_responses(custom_event.event_name) == []
        assert responses.get_waitlist(custom_event.event_name) == []
        update_rank.assert_not_called()
        source.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        source.user.send.assert_awaited_once()
        assert source.user.send.call_args.args[0] == (
            f"**{custom_event.event_name}**\n\n"
            "Please choose a payment method to complete your registration. "
            "Offkai Bot will send you the instructions on completing payment"
        )
        source.followup.send.assert_awaited_once_with(
            "Check your DMs now. Choose a payment method there to complete your registration.", ephemeral=True
        )
        assert signup_continuation(source).children[0].label == "Choose Payment Method"
        payment_modal = await submit_payment(source)
    payment, policy = payment_modal.to_dict()["components"]
    assert payment["type"] == 18 and payment["label"] == "Payment method"
    assert payment["component"]["type"] == 3 and payment["component"]["required"] is True
    assert [option["value"] for option in payment["component"]["options"]] == ["PayNow"]
    assert policy["components"][0]["custom_id"] == "no_show_agreement"
    assert policy["components"][0]["required"] is True
    saved = (responses.get_responses if open_event else responses.get_waitlist)(custom_event.event_name)[0]
    assert saved.payment_method == "PayNow"
    assert saved.display_name == "Recorded Name" and saved.extra_people == 1 and saved.extras_names == ["Guest"]
    assert saved.no_show_agreed
    reply = source.user.send.call_args.args[0]
    assert "Synthetic organizer instructions" in reply and "https://synthetic.invalid/pass" in reply


async def test_full_drinks_form_keeps_every_existing_field_before_payment(custom_event):
    custom_event.drinks = ["Tea"]
    custom_event.signup_form["fields"].append("drinks")
    source = interaction()
    await start_signup(source, custom_event)
    modal = source.response.send_modal.call_args.args[0]
    source.response.send_message.assert_not_awaited()
    assert {child.custom_id for child in modal.children} == {
        "preferred_name",
        "extra_people",
        "behavior_arrival_confirm",
        "drink_choice",
        "extras_names",
    }
    assert len(modal.to_dict()["components"]) == 5
    modal.extra_people_input._value = "0"
    modal.drink_choice_input._value = "Tea"
    modal.confirmation_input._value = "Yes"
    await complete_signup(modal, source)
    assert responses.get_responses(custom_event.event_name)[0].drinks == ["tea"]
    assert "🍺 Drinks: tea" in source.user.send.call_args.args[0]


@pytest.mark.parametrize("values", [[], ["Unconfigured"], ["PayNow", "Unconfigured"]])
async def test_modal_rejects_missing_or_unconfigured_payment(custom_event, values):
    responses.RESPONSE_DATA_CACHE = {}
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    await submit_payment(source, values=values)
    assert responses.get_responses(custom_event.event_name) == []
    assert responses.get_waitlist(custom_event.event_name) == []
    assert "choose an enabled payment method" in source.user.send.call_args.args[0]


async def test_separate_policy_rejects_no_without_recording_signup(custom_event):
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    await submit_payment(source, agreement="No")
    assert responses.get_responses(custom_event.event_name) == []
    assert responses.get_waitlist(custom_event.event_name) == []
    assert not modal.no_show_agreed
    assert "no-show / no-refund policy" in source.user.send.call_args.args[0]


async def test_continuation_and_payment_are_bound_to_original_attendee(custom_event):
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    view = signup_continuation(source)
    assert not await view.interaction_check(interaction(43))
    await view.continue_signup.callback(source)
    payment = source.response.send_modal.call_args.args[0]
    await payment.on_submit(interaction(43))
    assert responses.get_responses(custom_event.event_name) == []
    assert responses.get_waitlist(custom_event.event_name) == []
    await submit_payment(source)
    assert len(responses.get_responses(custom_event.event_name)) == 1
    await payment.on_submit(source)
    assert len(responses.get_responses(custom_event.event_name)) == 1


@pytest.mark.parametrize("change", ["capacity", "deadline", "closed"])
async def test_final_step_uses_current_capacity_deadline_and_open_state(custom_event, change):
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    assert responses.get_responses(custom_event.event_name) == []
    if change == "capacity":
        custom_event.max_capacity = 0
    elif change == "deadline":
        custom_event.event_deadline = datetime.now(UTC) - timedelta(seconds=1)
    else:
        custom_event.open = False
    await submit_payment(source)
    assert responses.get_responses(custom_event.event_name) == []
    assert responses.get_waitlist(custom_event.event_name)[0].no_show_agreed


@pytest.mark.parametrize("with_payment", [False, True])
async def test_custom_without_policy_never_records_assumed_agreement(custom_event, with_payment):
    custom_event.signup_form["fields"].remove("no_show")
    if not with_payment:
        custom_event.signup_form["payment_methods"] = {}
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    with patch("offkai_bot.interactions.build_checkin_url", return_value="https://synthetic.invalid/pass"):
        await modal.on_submit(source)
        if with_payment:
            payment = await submit_payment(source)
            assert payment.no_show_input is None
    assert responses.get_responses(custom_event.event_name)[0].no_show_agreed is False
    reply = source.user.send.call_args.args[0]
    assert ("Please provide proof of payment" in reply) == with_payment
    assert "no-refund policy agreed" not in reply


@pytest.mark.parametrize("drinks", [[], ["Tea"]])
async def test_default_signup_still_opens_existing_text_form(custom_event, drinks):
    custom_event.signup_form = None
    custom_event.drinks = drinks
    source = interaction()
    await start_signup(source, custom_event)
    modal = source.response.send_modal.call_args.args[0]
    source.response.send_message.assert_not_awaited()
    assert len(modal.children) == 4 + bool(drinks)
    assert all(isinstance(child, discord.ui.TextInput) for child in modal.children)


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
        {"fields": ["payment_method"], "payment_methods": {"PayPal": "Organizer text"}}, source, setup.publication
    )


async def test_creator_named_payment_reaches_attendee_form_and_reply(custom_event):
    source = interaction(42)
    create = AsyncMock()
    setup = SignupSetup(42, [], create)
    # Initially there are no payment selects with empty/invalid option arrays.
    assert [child.row for child in setup.children if isinstance(child, discord.ui.Select)] == [0]
    assert len(setup.to_components()[-1]["components"]) == 4
    setup.fields = ["guests", "no_show"]
    await setup.add_payment_method.callback(source)
    modal = source.response.send_modal.call_args.args[0]
    name = "My local bank " + "x" * 86  # Valid maximum-length method; modal titles remain short.
    assert len(name) == 100 and len(modal.title) <= 45
    await modal._scheduled_task(
        source,
        [
            {"type": 1, "components": [{"type": 4, "custom_id": field.custom_id, "value": value}]}
            for field, value in [
                (modal.name_input, f" {name} "),
                (modal.instructions, " Transfer using event reference "),
                (modal.jp_payment_info, " 主催者が入力した支払い案内 "),
            ]
        ],
        {},
    )
    source.response.edit_message.assert_awaited_once_with(view=setup)
    assert setup.fields == ["guests", "no_show", "payment_method"]
    assert setup.configuration()["payment_methods"] == {name: "Transfer using event reference"}
    assert setup.configuration()["payment_instructions_jp"] == {name: "主催者が入力した支払い案内"}
    fields = next(child for child in setup.children if child.row == 0)
    methods = next(child for child in setup.children if child.row == 1)
    assert {option.value for option in fields.options if option.default} == set(setup.fields)
    assert [(option.value, option.default) for option in methods.options] == [(name, True)]

    custom_event.signup_form = setup.configuration()
    events.EVENT_DATA_CACHE = [custom_event]
    events.save_event_data()
    events.EVENT_DATA_CACHE = None
    assert events.get_event(custom_event.event_name).signup_form == custom_event.signup_form
    attendee = GatheringModal(event=custom_event)
    attendee.extra_people_input._value = "0"
    attendee.confirmation_input._value = "Yes"
    await attendee.on_submit(source)
    payment = await submit_payment(source, values=[name])
    assert [option.value for option in payment.payment_method_input.options] == [name]
    assert responses.get_responses(custom_event.event_name)[0].payment_method == name
    reply = source.user.send.call_args.args[0]
    assert "Transfer using event reference" in reply
    assert "支払い案内: 主催者が入力した支払い案内" in reply
    await setup.publish.callback(source)
    create.assert_awaited_once_with(setup.configuration(), source, setup.publication)


async def test_instruction_edit_and_select_refresh_preserve_current_choices():
    source = interaction(42)
    setup = SignupSetup(42, [], AsyncMock())
    long_name = "Bank " + "x" * 95
    setup.instructions = {"Cash": "Pay at venue", long_name: "Original instructions"}
    setup.methods = ["Cash"]
    setup.fields = ["preferred_name", "payment_method"]
    setup.refresh_selects()
    editor = next(child for child in setup.children if child.row == 2)
    editor._refresh_state(source, {"values": [long_name]})
    await editor.callback(source)
    modal = source.response.send_modal.call_args.args[0]
    assert modal.name_input is None and len(modal.children) == 2 and len(modal.title) <= 45
    assert modal.instructions.default == "Original instructions"
    modal.instructions._value = " Updated instructions "
    await modal.on_submit(source)
    assert setup.instructions == {"Cash": "Pay at venue", long_name: "Updated instructions"}
    assert setup.methods == ["Cash"] and setup.fields == ["preferred_name", "payment_method"]
    source.response.edit_message.assert_awaited_once_with(view=setup)
    methods = next(child for child in setup.children if child.row == 1)
    assert [option.value for option in methods.options if option.default] == ["Cash"]
    methods._refresh_state(source, {"values": [long_name]})
    await methods.callback(source)
    assert setup.configuration()["payment_methods"] == {long_name: "Updated instructions"}
    fields = next(child for child in setup.children if child.row == 0)
    fields._refresh_state(source, {"values": ["preferred_name"]})
    await fields.callback(source)
    assert setup.configuration()["payment_methods"] == {}
    assert setup.instructions[long_name] == "Updated instructions"
    assert source.response.edit_message.await_count == 3


async def test_optional_jp_instructions_edit_clear_and_omit(custom_event):
    source = interaction(42)
    setup = SignupSetup(42, [], AsyncMock())
    setup.instructions = {"PayNow": "Original language", "Disabled": "Unused"}
    setup.methods = ["PayNow"]
    setup.fields = ["payment_method"]
    setup.jp_instructions = {"PayNow": "元の案内", "Disabled": "表示しない"}
    modal = InstructionModal(setup, "PayNow")
    assert not modal.jp_payment_info.required
    assert modal.jp_payment_info.default == "元の案内"
    modal.instructions._value = "Original language"
    modal.jp_payment_info._value = " 新しい案内 "
    await modal.on_submit(source)
    assert setup.configuration()["payment_instructions_jp"] == {"PayNow": "新しい案内"}
    await setup.preview.callback(source)
    assert "新しい案内" in source.followup.send.call_args.kwargs["embed"].description
    modal.jp_payment_info._value = " "
    await modal.on_submit(source)
    assert "payment_instructions_jp" not in setup.configuration()
    custom_event.signup_form = setup.configuration()
    entry = responses.Response(
        user_id=42,
        username="Name",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=custom_event.event_name,
        timestamp=datetime.now(UTC),
        payment_method="PayNow",
    )
    with patch("offkai_bot.interactions.build_checkin_url", return_value="https://synthetic.invalid/pass"):
        en, jp = render_custom_reply_sections(custom_event, entry, "Attendance confirmed")
    assert "Original language" in en and "Original language" not in jp
    assert "支払い案内:" not in jp
    assert "💳 支払い方法: PayNow" in jp
    assert "📎 Please provide proof" in en and "📎 Please provide proof" not in jp


@pytest.mark.parametrize(
    ("name", "instructions"),
    [(" ", "Text"), ("x" * 101, "Text"), (" cash ", "Text"), ("Bank", " "), ("Bank", "x" * 1001)],
)
async def test_invalid_new_method_does_not_change_draft(name, instructions):
    setup = SignupSetup(42, [], AsyncMock())
    setup.instructions = {"Cash": "Pay at venue"}
    before = setup.configuration()
    modal = InstructionModal(setup)
    modal.name_input._value = name
    modal.instructions._value = instructions
    source = interaction(42)
    await modal.on_submit(source)
    assert setup.configuration() == before and setup.instructions == {"Cash": "Pay at venue"}
    source.response.send_message.assert_awaited_once()
    source.response.edit_message.assert_not_awaited()


async def test_method_limit_matches_discord_select_limit():
    setup = SignupSetup(42, [], AsyncMock())
    setup.instructions = {f"Method {index}": "Instructions" for index in range(24)}
    modal = InstructionModal(setup)
    modal.name_input._value = "Last method"
    modal.instructions._value = "Instructions"
    await modal.on_submit(interaction(42))
    assert len(setup.instructions) == 25 and setup.add_payment_method.disabled
    for child in setup.children:
        if isinstance(child, discord.ui.Select) and child.row in [1, 2]:
            assert len(child.options) == 25 and child.max_values <= 25
    modal = InstructionModal(setup)
    modal.name_input._value = "One too many"
    modal.instructions._value = "Instructions"
    source = interaction(42)
    await modal.on_submit(source)
    assert len(setup.instructions) == 25 and "One too many" not in setup.instructions
    assert "up to 25" in source.response.send_message.call_args.args[0]


@pytest.mark.parametrize("blocked", ["another_owner", "finished", "publishing"])
async def test_method_modal_keeps_existing_draft_access_checks(blocked):
    setup = SignupSetup(42, [], AsyncMock())
    setup.finished = blocked == "finished"
    setup.publishing = blocked == "publishing"
    modal = InstructionModal(setup)
    modal.name_input._value = "My bank"
    modal.instructions._value = "Instructions"
    source = interaction(43 if blocked == "another_owner" else 42)
    await modal.on_submit(source)
    assert setup.instructions == {} and setup.methods == []
    source.response.send_message.assert_awaited_once()


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
            await complete_signup(modal, source)
        reply = source.user.send.call_args.args[0]
        assert "Synthetic organizer instructions" in reply and token in reply
        replies[name] = {"token": token, "reply": reply}
    for filename, value in [
        ("events.json", events.EVENT_DATA_CACHE),
        ("responses.json", responses.RESPONSE_DATA_CACHE),
        ("replies.json", replies),
    ]:
        (fixture_dir / filename).write_text(json.dumps(value, cls=DataclassJSONEncoder))


@pytest.mark.parametrize("outcome", ["confirmed", "waitlist", "capacity_exceeded"])
@pytest.mark.parametrize("dm_fails", [False, True])
async def test_long_custom_reply_has_complete_language_embeds(custom_event, outcome, dm_fails):
    custom_event.event_name = "🎉" * 90
    custom_event.signup_form["payment_methods"]["PayNow"] = "Instructions " + "x" * 987
    custom_event.signup_form["payment_instructions_jp"] = {"PayNow": "案内" + "あ" * 998}
    events.EVENT_DATA_CACHE = [custom_event]
    responses.RESPONSE_DATA_CACHE = {}
    source = interaction()
    if outcome == "waitlist":
        custom_event.open = False
    elif outcome == "capacity_exceeded":
        custom_event.max_capacity = 1
    if dm_fails:
        source.user.send.side_effect = discord.Forbidden(MagicMock(status=403), "DM blocked")
    modal = GatheringModal(event=custom_event, payment_method="PayNow")
    modal.preferred_name_input._value = "N" * 32
    modal.extra_people_input._value = "5"
    modal.extras_names_input._value = ",".join(["G" * 31] * 5)
    modal.confirmation_input._value = "Yes"
    token = build_checkin_token(source.user.id, custom_event.event_name, "synthetic-test-key")
    link = "https://synthetic.invalid/" + "a" * 100 + "/?token=" + token
    with patch("offkai_bot.interactions.build_checkin_url", return_value=link):
        await complete_signup(modal, source)
    assert source.user.send.await_count == 2  # Payment prompt, then the final confirmation.
    delivery = source.response.send_message if dm_fails else source.user.send
    embeds = delivery.call_args.kwargs["embeds"]
    assert len(embeds) == 2
    descriptions = [embed.description for embed in embeds]
    assert all(len(text.encode("utf-16-le")) // 2 <= 4096 for text in descriptions)
    assert sum(len(text.encode("utf-16-le")) // 2 for text in descriptions) <= 6000
    assert all(link in text for text in descriptions)
    assert "Instructions" in descriptions[0] and "案内" not in descriptions[0]
    assert "案内" in descriptions[1] and "Instructions" not in descriptions[1]


async def test_custom_command_stays_draft_until_create(custom_event):
    source = interaction(42)
    cog = EventsCog(MagicMock())
    with patch.object(cog, "_create_event", new=AsyncMock()) as create:
        await EventsCog.create_offkai.callback(
            cog,
            source,
            "New Synthetic",
            "Venue",
            "Address",
            "https://synthetic.invalid/maps",
            custom_event.event_datetime.isoformat(),
            form="custom",
        )
        create.assert_not_awaited()
        setup = source.response.send_message.call_args.kwargs["view"]
        assert source.response.send_message.call_args.kwargs["ephemeral"] is True
        setup.fields = ["payment_method", "no_show"]
        setup.methods = ["PayNow"]
        setup.instructions["PayNow"] = "Synthetic organizer instructions"
        await setup.publish.callback(source)
        create.assert_awaited_once()
        assert create.call_args.args[-1] == setup.configuration()


@pytest.mark.parametrize("failure", ["rejected_thread", "unknown_thread", "after_thread"])
async def test_draft_retry_only_before_resources_exist(custom_event, failure):
    source = interaction(42)
    source.channel.id = 456
    source.response.is_done.return_value = True
    announcement = MagicMock(spec=discord.Message)
    announcement.pin = AsyncMock()
    source.followup.send.return_value = announcement
    thread = MagicMock(spec=discord.Thread)
    thread.id = 789
    thread.mention = "<#789>"
    cog = EventsCog(MagicMock())
    await EventsCog.create_offkai.callback(
        cog,
        source,
        "Retry Synthetic",
        "Venue",
        "Address",
        "https://synthetic.invalid/maps",
        custom_event.event_datetime.isoformat(),
        form="custom",
    )
    setup = source.response.send_message.call_args.kwargs["view"]
    setup.fields = ["payment_method"]
    setup.methods = ["PayNow"]
    setup.instructions["PayNow"] = "Keep these instructions"
    expected = setup.configuration()
    if failure == "rejected_thread":
        exception = discord.Forbidden(MagicMock(status=403), "Thread creation rejected")
        source.channel.create_thread = AsyncMock(side_effect=[exception, thread])
    elif failure == "unknown_thread":
        source.channel.create_thread = AsyncMock(side_effect=TimeoutError("Response unknown"))
    else:
        source.channel.create_thread = AsyncMock(return_value=thread)
    with (
        patch("offkai_bot.cogs.events.register_deadline_reminders"),
        patch("offkai_bot.cogs.events.register_checkin_reminder"),
        patch("offkai_bot.cogs.events.send_event_message", new=AsyncMock()) as send,
    ):
        if failure == "after_thread":
            send.side_effect = RuntimeError("Announcement failed")
        await setup.publish.callback(source)
        source.response.defer.assert_awaited_with(thinking=True, ephemeral=True)
        assert not setup.publishing
        assert setup.configuration() == expected
        if failure == "rejected_thread":
            assert not setup.finished and not setup.publication.resources_may_exist
            assert await setup.interaction_check(source)
            assert "retry" in source.followup.send.call_args.args[0]
            await setup.publish.callback(source)
            assert setup.finished and setup.publication.resources_may_exist
            assert source.channel.create_thread.await_count == 2
        else:
            assert setup.finished and setup.publication.resources_may_exist
            assert not await setup.interaction_check(source)
            await setup.publish.callback(interaction(42))
            assert source.channel.create_thread.await_count == 1


async def test_draft_blocks_concurrent_publication_without_finishing():
    import asyncio

    started = asyncio.Event()
    finish = asyncio.Event()

    async def create(config, source, publication):
        started.set()
        await finish.wait()

    source = interaction(42)
    setup = SignupSetup(42, [], create)
    task = asyncio.create_task(setup.publish.callback(source))
    await started.wait()
    try:
        assert setup.publishing and not setup.finished
        assert not await setup.interaction_check(interaction(42))
        await setup.publish.callback(interaction(42))
        assert setup.publishing and not setup.finished
    finally:
        finish.set()
        await task
    assert setup.finished and not setup.publishing


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize("long_reply", [False, True])
async def test_promotions_send_identical_confirmed_signup_instructions(
    custom_event, automatic, long_reply, monkeypatch
):
    from offkai_bot.interactions import render_custom_reply

    events.EVENT_DATA_CACHE = [custom_event]
    monkeypatch.setattr(
        "offkai_bot.interactions.build_checkin_url", lambda *args: "https://synthetic.invalid/?token=test"
    )
    if long_reply:
        custom_event.signup_form["payment_methods"]["PayNow"] = "Instructions " * 100
        custom_event.signup_form["payment_instructions_jp"] = {"PayNow": "支払い案内" * 250}
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
    responses.RESPONSE_DATA_CACHE = {custom_event.event_name: {"attendees": [], "waitlist": [entry]}}
    user = interaction().user
    bot = MagicMock(fetch_user=AsyncMock(return_value=user))
    if automatic:
        await promote_waitlist_batch(custom_event, bot)
    else:
        with patch("offkai_bot.cogs.events.update_event_message", new=AsyncMock()):
            await EventsCog.promote.callback(EventsCog(bot), interaction(), custom_event.event_name, "123")
    saved = responses.get_responses(custom_event.event_name)[0]
    assert saved.timestamp == entry.timestamp
    expected = render_custom_reply(custom_event, saved, "Attendance confirmed")
    if long_reply:
        sections = [embed.description for embed in user.send.call_args.kwargs["embeds"]]
        assert all(
            actual.endswith(original)
            for actual, original in zip(
                sections, render_custom_reply_sections(custom_event, saved, "Attendance confirmed"), strict=True
            )
        )
        assert "A spot has opened up" in sections[0] and "空きが出た" in sections[1]
    else:
        actual = user.send.call_args.args[0]
        assert "A spot has opened up" in actual and "空きが出た" in actual
        assert all(
            section in actual for section in render_custom_reply_sections(custom_event, saved, "Attendance confirmed")
        )
    assert "Synthetic organizer instructions" in expected or "Instructions" in expected
    assert "支払い証明" in expected


async def test_interest_removal_keeps_success_when_announcement_fails(custom_event):
    from offkai_bot.registration_removal import remove_registration

    custom_event.interest_check = True
    entry = responses.Response(
        user_id=123,
        username="Synthetic",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=custom_event.event_name,
        timestamp=datetime.now(UTC),
    )
    responses.RESPONSE_DATA_CACHE = {custom_event.event_name: {"attendees": [entry], "waitlist": []}}
    with patch(
        "offkai_bot.registration_removal.update_event_message", new=AsyncMock(side_effect=RuntimeError("Unavailable"))
    ):
        result = await remove_registration(MagicMock(), custom_event, interaction(123).user, None)
    assert result["removed"] is True
    assert responses.get_responses(custom_event.event_name) == []
    assert any("announcement" in warning for warning in result["warnings"])


@pytest.mark.parametrize("deadline_error", [False, True])
async def test_custom_creation_preserves_actionable_domain_error(deadline_error):
    from offkai_bot.errors import DuplicateEventError, EventDeadlineInPastError

    source = interaction(42)
    source.response.is_done.return_value = True
    error = EventDeadlineInPastError() if deadline_error else DuplicateEventError("Already exists")
    setup = SignupSetup(42, [], AsyncMock(side_effect=error))
    await setup.publish.callback(source)
    assert str(error) in source.followup.send.call_args.args[0]
    assert not setup.finished and not setup.publishing


@pytest.mark.parametrize("waitlisted", [False, True])
async def test_duplicate_custom_signup_never_shows_payment_continuation(custom_event, waitlisted):
    source = interaction()
    entry_type = responses.WaitlistEntry if waitlisted else responses.Response
    entry = entry_type(
        user_id=source.user.id,
        username="Synthetic",
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=custom_event.event_name,
        timestamp=datetime.now(UTC),
    )
    responses.RESPONSE_DATA_CACHE = {
        custom_event.event_name: {
            "attendees": [] if waitlisted else [entry],
            "waitlist": [entry] if waitlisted else [],
        }
    }
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    assert "view" not in source.response.send_message.call_args.kwargs
    assert "already" in source.user.send.call_args.args[0].lower()


async def test_custom_create_keeps_private_ack_and_public_pinned_announcement(custom_event):
    source = interaction(42)
    source.channel.id = 456
    thread = MagicMock(spec=discord.Thread, id=789, mention="<#789>")
    source.channel.create_thread = AsyncMock(return_value=thread)
    announcement = MagicMock(spec=discord.Message, pin=AsyncMock())
    source.channel.send = AsyncMock(return_value=announcement)
    source.edit_original_response = AsyncMock()
    cog = EventsCog(MagicMock())
    with (
        patch("offkai_bot.cogs.events.register_deadline_reminders"),
        patch("offkai_bot.cogs.events.register_checkin_reminder"),
        patch("offkai_bot.cogs.events.send_event_message", new=AsyncMock()),
    ):
        await cog._create_event(
            source,
            "Private setup",
            "Venue",
            "Address",
            "",
            custom_event.event_datetime,
            None,
            [],
            None,
            None,
            None,
            False,
            custom_event.signup_form,
        )
    source.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
    source.channel.send.assert_awaited_once()
    assert "# Offkai Created: Private setup" in source.channel.send.call_args.args[0]
    announcement.pin.assert_awaited_once()
    source.edit_original_response.assert_awaited_once()
    source.followup.send.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["confirmed", "closed", "capacity", "group_too_large"])
async def test_payment_dm_keeps_original_server_context_and_replies_directly(custom_event, outcome):
    from offkai_bot import interactions

    custom_event.role_id = 333
    if outcome == "closed":
        custom_event.open = False
    elif outcome == "capacity":
        custom_event.max_capacity = 0
    elif outcome == "group_too_large":
        custom_event.max_capacity = 1
    source = interaction()
    source.channel = MagicMock(spec=discord.Thread)
    source.channel.add_user = AsyncMock()
    source.channel.send = AsyncMock()
    source.user.display_name = "Original server nickname"
    target = interaction(source.user.id)
    target.guild = None
    target.channel = MagicMock(spec=discord.DMChannel)
    target.channel.send = AsyncMock()
    target.user = MagicMock(spec=discord.User, id=source.user.id, name=source.user.name, display_name="Global name")
    target.user.send = AsyncMock()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "1" if outcome == "group_too_large" else "0"
    modal.extras_names_input._value = "Guest" if outcome == "group_too_large" else ""
    modal.confirmation_input._value = "Yes"
    assert "check your DMs" in modal.confirmation_input.placeholder
    with (
        patch.object(interactions, "assign_event_role", new_callable=AsyncMock) as role,
        patch.object(interactions, "update_rank") as rank,
        patch.object(interactions, "get_rank", return_value=next(iter(interactions.MILESTONE_MESSAGES))),
        patch.object(interactions, "can_rank_message_sent", return_value=True),
        patch.object(interactions, "mark_achieved_rank"),
    ):
        await modal.on_submit(source)
        assert responses.get_responses(custom_event.event_name) == []
        assert responses.get_waitlist(custom_event.event_name) == []
        await submit_payment(source, target=target)
        recorded = (responses.get_responses if outcome == "confirmed" else responses.get_waitlist)(
            custom_event.event_name
        )
        assert len(recorded) == 1
        assert recorded[0].display_name == "Original server nickname"
        assert recorded[0].payment_method == "PayNow" and recorded[0].no_show_agreed
        source.channel.add_user.assert_awaited_once_with(target.user)
        target.user.send.assert_not_awaited()
        target.channel.send.assert_not_awaited()
        target.response.send_message.assert_awaited_once()
        reply = target.response.send_message.call_args.args[0]
        assert "Synthetic organizer instructions" in reply
        assert "I've sent you a DM" not in reply
        if outcome == "confirmed":
            role.assert_awaited_once_with(source.guild, source.user.id, custom_event.role_id)
            rank.assert_called_once()
            source.channel.send.assert_awaited_once()  # Milestone stays in the event thread.
        else:
            role.assert_not_awaited()
            rank.assert_not_called()
        assert signup_continuation(source).finished


@pytest.mark.parametrize("failure", [discord.Forbidden, discord.HTTPException])
async def test_blocked_payment_dm_reuses_private_continuation_and_entered_details(custom_event, failure):
    source = interaction()
    source.user.send.side_effect = failure(MagicMock(status=403), "DM unavailable")
    modal = GatheringModal(event=custom_event)
    modal.preferred_name_input._value = "Saved name"
    modal.extra_people_input._value = "1"
    modal.extras_names_input._value = "Saved guest"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    source.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    assert source.followup.send.call_args.kwargs["ephemeral"] is True
    assert signup_continuation(source).signup is modal
    assert responses.get_responses(custom_event.event_name) == []
    await submit_payment(source)
    saved = responses.get_responses(custom_event.event_name)[0]
    assert saved.display_name == "Saved name" and saved.extras_names == ["Saved guest"]
    assert saved.payment_method == "PayNow" and saved.no_show_agreed
    assert source.response.send_message.call_args.kwargs["ephemeral"] is True


async def test_payment_validation_error_stays_in_dm_and_can_retry(custom_event):
    source = interaction()
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    await modal.on_submit(source)
    target = interaction(source.user.id)
    target.guild = None
    await submit_payment(source, agreement="No", target=target)
    assert "no-show / no-refund" in target.response.send_message.call_args.args[0]
    target.user.send.assert_not_awaited()
    assert responses.get_responses(custom_event.event_name) == []
    await submit_payment(source, target=target)
    assert len(responses.get_responses(custom_event.event_name)) == 1


async def test_capacity_notice_from_payment_dm_stays_in_event_thread(custom_event):
    source = interaction()
    source.channel = MagicMock(spec=discord.Thread, add_user=AsyncMock(), send=AsyncMock())
    custom_event.max_capacity = 1
    target = interaction(source.user.id)
    target.guild = None
    target.channel = MagicMock(spec=discord.DMChannel, send=AsyncMock())
    modal = GatheringModal(event=custom_event)
    modal.extra_people_input._value = "0"
    modal.confirmation_input._value = "Yes"
    with patch("offkai_bot.interactions.get_rank", return_value=-1):
        await modal.on_submit(source)
        await submit_payment(source, target=target)
    assert "Maximum capacity has been reached" in source.channel.send.call_args.args[0]
    target.channel.send.assert_not_awaited()
