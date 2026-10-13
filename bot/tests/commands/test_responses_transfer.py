# tests/commands/test_responses_transfer.py

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import response as response_data
from offkai_bot.data.response import EventData, Response, WaitlistEntry, get_responses, get_waitlist
from offkai_bot.data.responses_transfer import (
    describe_responses_changes,
    export_responses_json,
    merge_responses_import,
    parse_responses_import,
    replace_responses,
)
from offkai_bot.errors import ResponsesImportError

TS = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def transfer_config(mock_config):
    with patch("offkai_bot.data.responses_transfer.get_config", return_value=mock_config):
        yield


def make_response(user_id, username, display_name, extra_people=0, extras_names=None):
    return Response(
        user_id=user_id,
        username=username,
        extra_people=extra_people,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name="Summer Bash",
        timestamp=TS,
        extras_names=extras_names or [],
        display_name=display_name,
        payment_method="PayNow",
        no_show_agreed=True,
    )


@pytest.fixture
def current_data(mock_paths):
    data = {
        "Summer Bash": EventData(
            attendees=[
                make_response(1, "alice", "Bob", 1, ["Bob Guest"]),
                make_response(2, "bob", "Bob", 1, ["Bob Guest"]),
            ],
            waitlist=[
                WaitlistEntry(
                    user_id=3,
                    username="carol",
                    extra_people=0,
                    behavior_confirmed=True,
                    arrival_confirmed=True,
                    event_name="Summer Bash",
                    timestamp=TS,
                    display_name="Carol",
                )
            ],
        )
    }
    response_data.RESPONSE_DATA_CACHE = data
    response_data.save_responses()
    return data


def exported_dict() -> dict:
    return json.loads(export_responses_json())


def merged_upload(current, data: dict) -> dict[str, EventData]:
    return merge_responses_import(current, parse_responses_import(json.dumps(data).encode()))


def make_waitlisted(user_id, username, event_name="Summer Bash"):
    return WaitlistEntry(
        user_id=user_id,
        username=username,
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event_name,
        timestamp=TS,
    )


# --- Data layer ---


def test_export_then_import_round_trips_unchanged(current_data):
    upload = parse_responses_import(export_responses_json())
    assert upload.events == current_data
    merged = merge_responses_import(current_data, upload)
    lines, changed = describe_responses_changes(current_data, merged)
    assert lines == [] and changed == set()


def test_import_applies_an_edited_name(current_data):
    data = exported_dict()
    data["Summer Bash"]["attendees"][0].update(display_name="Alice", extra_people=0, extras_names=[])
    parsed = merged_upload(current_data, data)

    lines, changed = describe_responses_changes(current_data, parsed)
    assert changed == {"Summer Bash"}
    assert "headcount 4 → 3" in lines[0]
    assert any("edited: alice" in line for line in lines)

    backup = replace_responses(parsed)
    assert backup is not None and os.path.exists(backup)
    assert get_responses("Summer Bash")[0].display_name == "Alice"
    # The edit is persisted, not just cached.
    response_data.RESPONSE_DATA_CACHE = None
    assert get_responses("Summer Bash")[0].display_name == "Alice"
    assert [e.username for e in get_waitlist("Summer Bash")] == ["carol"]


def test_registrations_missing_from_upload_are_flagged(current_data):
    data = exported_dict()
    data["Summer Bash"]["waitlist"] = []
    lines, _ = describe_responses_changes(current_data, merged_upload(current_data, data))
    assert any("REMOVED" in line and "carol" in line for line in lines)


def test_signup_after_export_in_an_unedited_event_is_kept(current_data):
    data = exported_dict()
    data["Summer Bash"]["attendees"][0]["display_name"] = "Alice"
    # Someone signs up for another event between the export and the import.
    current_data["Winter Meetup"] = EventData(attendees=[], waitlist=[make_waitlisted(9, "dave", "Winter Meetup")])

    merged = merged_upload(current_data, data)
    assert merged["Summer Bash"]["attendees"][0].display_name == "Alice"
    assert [e.username for e in merged["Winter Meetup"]["waitlist"]] == ["dave"]
    lines, changed = describe_responses_changes(current_data, merged)
    assert changed == {"Summer Bash"}


def test_unedited_event_keeps_changes_made_after_export(current_data):
    data = exported_dict()
    data["Other Event"] = {"attendees": [], "waitlist": []}  # Harmless no-op addition.
    current_data["Summer Bash"]["waitlist"].append(make_waitlisted(9, "dave"))

    merged = merged_upload(current_data, data)
    assert [e.username for e in merged["Summer Bash"]["waitlist"]] == ["carol", "dave"]


def test_edit_to_an_event_that_changed_after_export_is_rejected(current_data):
    data = exported_dict()
    data["Summer Bash"]["attendees"][0]["display_name"] = "Alice"
    current_data["Summer Bash"]["waitlist"].append(make_waitlisted(9, "dave"))

    with pytest.raises(ResponsesImportError, match="changed in the bot after your export for: Summer Bash"):
        merged_upload(current_data, data)


def test_upload_without_export_metadata_is_rejected(current_data):
    data = exported_dict()
    del data["_export"]
    with pytest.raises(ResponsesImportError, match="no valid '_export' section"):
        parse_responses_import(json.dumps(data).encode())


def test_rollback_file_undoes_an_import(current_data):
    data = exported_dict()
    data["Summer Bash"]["attendees"][0]["display_name"] = "Alice"
    merged = merged_upload(current_data, data)
    rollback = export_responses_json(data=current_data, baseline=merged)
    replace_responses(merged)

    restored = merge_responses_import(merged, parse_responses_import(rollback))
    assert restored["Summer Bash"]["attendees"][0].display_name == "Bob"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.__setitem__("Summer Bash", []), "only 'attendees' and 'waitlist'"),
        (lambda d: d["Summer Bash"]["attendees"][0].pop("user_id"), "missing 'user_id'"),
        (lambda d: d["Summer Bash"]["attendees"][0].update(timestamp="yesterday"), "invalid user_id or timestamp"),
        (lambda d: d["Summer Bash"]["attendees"][0].update(extra_people=6), "must be 0-5"),
        (lambda d: d["Summer Bash"]["attendees"][0].update(extra_people=2), "exactly 2 extras_names"),
        (lambda d: d["Summer Bash"]["waitlist"][0].update(user_id=1), "more than once"),
        (lambda d: d["Summer Bash"]["attendees"][0].update(event_name="Winter Meetup"), "must be 'Summer Bash'"),
    ],
)
def test_invalid_uploads_are_rejected(current_data, mutate, message):
    data = exported_dict()
    mutate(data)
    with pytest.raises(ResponsesImportError, match=message):
        parse_responses_import(json.dumps(data).encode())


def test_non_json_upload_is_rejected(current_data):
    with pytest.raises(ResponsesImportError, match="not valid JSON"):
        parse_responses_import(b"{not json")


# --- Commands ---


@pytest.fixture
def cog():
    return EventsCog(MagicMock(spec=commands.Bot))


@pytest.fixture
def interaction():
    value = MagicMock(spec=discord.Interaction)
    value.user = MagicMock(spec=discord.Member)
    value.user.id = 123
    value.user.send = AsyncMock()
    value.guild = MagicMock(spec=discord.Guild)
    value.channel = MagicMock(spec=discord.TextChannel)
    value.response = MagicMock(defer=AsyncMock())
    value.followup = MagicMock(send=AsyncMock())
    return value


def attachment(payload: bytes) -> MagicMock:
    file = MagicMock(spec=discord.Attachment)
    file.size = len(payload)
    file.read = AsyncMock(return_value=payload)
    return file


async def test_export_command_dms_the_file(cog, interaction, current_data):
    await EventsCog.export_responses.callback(cog, interaction)
    sent = interaction.user.send.call_args.kwargs["file"]
    sent_data, expected = json.loads(sent.fp.read()), exported_dict()
    for data in (sent_data, expected):
        del data["_export"]["exported_at"]
    assert sent_data == expected
    interaction.followup.send.assert_awaited_once()


async def test_import_command_previews_without_changing_data(cog, interaction, current_data):
    data = exported_dict()
    data["Summer Bash"]["attendees"][0]["display_name"] = "Alice"
    await EventsCog.import_responses.callback(cog, interaction, attachment(json.dumps(data).encode()))
    assert "Preview only" in interaction.followup.send.call_args.args[0]
    assert get_responses("Summer Bash")[0].display_name == "Bob"


async def test_import_command_applies_and_returns_previous_data(
    cog, interaction, current_data, prepopulated_event_cache
):
    previous = exported_dict()
    data = exported_dict()
    data["Summer Bash"]["attendees"][0]["display_name"] = "Alice"
    with patch("offkai_bot.cogs.events.update_event_message", new=AsyncMock()) as update_message:
        await EventsCog.import_responses.callback(cog, interaction, attachment(json.dumps(data).encode()), apply=True)
    assert get_responses("Summer Bash")[0].display_name == "Alice"
    update_message.assert_awaited_once()
    kwargs = interaction.followup.send.call_args.kwargs
    assert "Imported" in interaction.followup.send.call_args.args[0]
    rollback = json.loads(kwargs["files"][0].fp.read())
    # Same registrations as before the import, fingerprinted against the imported data so it can be re-imported.
    assert {k: v for k, v in rollback.items() if k != "_export"} == {
        k: v for k, v in previous.items() if k != "_export"
    }
    assert rollback["_export"]["event_fingerprints"] != previous["_export"]["event_fingerprints"]


async def test_import_command_reports_no_differences(cog, interaction, current_data):
    await EventsCog.import_responses.callback(cog, interaction, attachment(export_responses_json()), apply=True)
    assert "nothing to import" in interaction.followup.send.call_args.args[0]
