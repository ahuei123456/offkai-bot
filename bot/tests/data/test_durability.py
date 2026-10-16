"""Persistence failures must not turn a staged change into a successful cache mutation."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from offkai_bot import event_actions
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import atomic, event, ranking, response, responses_transfer
from offkai_bot.data.atomic import atomic_write_json
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.errors import EventAlreadyClosedError, EventArchivedError


@pytest.fixture
def durable_files(tmp_path, monkeypatch):
    settings = {
        "EVENTS_FILE": str(tmp_path / "nested" / "events.json"),
        "RESPONSES_FILE": str(tmp_path / "nested" / "responses.json"),
        "RANKING_FILE": str(tmp_path / "nested" / "rankings.json"),
    }
    for module in (event, response, ranking, responses_transfer):
        monkeypatch.setattr(module, "get_config", lambda: settings)
    return settings


def registration(uid=1, *, waiting=False):
    cls = response.WaitlistEntry if waiting else response.Response
    return cls(uid, f"user{uid}", 0, True, True, "Gathering", datetime(2026, 1, 1, tzinfo=UTC))


def stored_event():
    return event.Event("Gathering", "Venue", "Address", "Maps", datetime(3024, 1, 1, tzinfo=UTC), open=True)


@pytest.mark.parametrize(
    "operation",
    ["add", "remove", "join", "leave", "pop", "specific", "restore", "number", "clear"],
)
def test_response_write_failure_preserves_disk_cache_and_records(durable_files, operation):
    attendee = replace(registration(), attendee_number=5)
    waiting = [registration(2, waiting=True), registration(3, waiting=True)]
    response.RESPONSE_DATA_CACHE = {"Gathering": response.EventData(attendees=[attendee], waitlist=waiting)}
    response.save_responses()
    cache = response.load_responses()
    before = deepcopy(cache)
    path = Path(durable_files["RESPONSES_FILE"])
    disk = path.read_bytes()
    newcomer = registration(4)
    operations = {
        "add": lambda: response.add_response("Gathering", newcomer),
        "remove": lambda: response.remove_response("Gathering", 1),
        "join": lambda: response.add_to_waitlist("Gathering", registration(4, waiting=True)),
        "leave": lambda: response.remove_from_waitlist("Gathering", 2),
        "pop": lambda: response.promote_from_waitlist("Gathering"),
        "specific": lambda: response.promote_specific_from_waitlist("Gathering", 3),
        "restore": lambda: response.restore_waitlist_entry("Gathering", registration(4, waiting=True), 1),
        "number": lambda: response.assign_attendee_numbers("Gathering"),
        "clear": lambda: response.clear_attendee_numbers("Gathering"),
    }
    with (
        patch("offkai_bot.data.atomic.os.replace", side_effect=OSError("disk unavailable")),
        pytest.raises(OSError, match="disk unavailable"),
    ):
        operations[operation]()
    assert response.load_responses() is cache
    assert cache == before
    assert attendee.attendee_number == 5
    assert newcomer.attendee_number is None
    assert path.read_bytes() == disk
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("operation", ["add", "modify", "close", "reopen", "archive", "metadata"])
def test_event_write_failure_preserves_shared_object(durable_files, operation):
    current = stored_event()
    current.open = operation != "reopen"
    event.EVENT_DATA_CACHE = [current]
    response.RESPONSE_DATA_CACHE = {}
    event.save_event_data()
    path = Path(durable_files["EVENTS_FILE"])
    disk = path.read_bytes()
    original = asdict(current)
    operations = {
        "add": lambda: event.add_event("Second", "V", "A", "M", current.event_datetime, 1, 2, []),
        "modify": lambda: event.update_event_details(current.event_name, venue="Changed"),
        "close": lambda: event.set_event_open_status(current.event_name, False),
        "reopen": lambda: event.set_event_open_status(current.event_name, True),
        "archive": lambda: event.archive_event(current.event_name),
        "metadata": lambda: event.persist_event_changes(current, message_id=123),
    }
    with (
        patch("offkai_bot.data.atomic.os.replace", side_effect=OSError("disk unavailable")),
        pytest.raises(OSError, match="disk unavailable"),
    ):
        operations[operation]()
    assert event.get_event(current.event_name) is current
    assert event.load_event_data() == [current]
    assert asdict(current) == original
    assert path.read_bytes() == disk


def test_successful_event_update_keeps_view_reference_and_survives_restart(durable_files):
    current = stored_event()
    event.EVENT_DATA_CACHE = [current]
    assert event.update_event_details(current.event_name, venue="Changed") is current
    assert current.venue == "Changed"
    event.EVENT_DATA_CACHE = None
    assert event.get_event(current.event_name).venue == "Changed"


@pytest.mark.parametrize("operation", ["increment", "decrement", "milestone", "manual", "automatic", "new"])
def test_rank_write_failure_preserves_records(durable_files, operation):
    ranking.RANKING_DATA_CACHE = {
        "1": ranking.UserRank("user1", 1, False, False, False),
        "legacy": ranking.UserRank("legacy", 2, True, False, False),
    }
    ranking.save_rankings()
    cache = ranking.load_rankings()
    held = cache["1"]
    before = deepcopy(cache)
    path = Path(durable_files["RANKING_FILE"])
    disk = path.read_bytes()
    operations = {
        "increment": lambda: ranking.update_rank(1, "renamed"),
        "decrement": lambda: ranking.decrease_rank(1, "user1"),
        "milestone": lambda: ranking.mark_achieved_rank(1),
        "manual": lambda: ranking.migrate_legacy_rank(1, "user1", "legacy"),
        "automatic": lambda: ranking.get_rank(2, "legacy"),
        "new": lambda: ranking.get_rank(3, "new"),
    }
    with (
        patch("offkai_bot.data.ranking._registered_identities", return_value=[(2, "legacy")]),
        patch("offkai_bot.data.atomic.os.replace", side_effect=OSError("disk unavailable")),
        pytest.raises(OSError, match="disk unavailable"),
    ):
        operations[operation]()
    assert ranking.load_rankings() is cache
    assert cache == before
    assert held == before["1"]
    assert path.read_bytes() == disk


@pytest.mark.parametrize(
    "module,key,cache_name",
    [
        (event, "EVENTS_FILE", "EVENT_DATA_CACHE"),
        (response, "RESPONSES_FILE", "RESPONSE_DATA_CACHE"),
        (ranking, "RANKING_FILE", "RANKING_DATA_CACHE"),
    ],
)
def test_read_failure_never_initializes_writable_cache(durable_files, module, key, cache_name):
    path = Path(durable_files[key])
    atomic_write_json(str(path), [])
    with patch("builtins.open", side_effect=PermissionError("unreadable")), pytest.raises(PermissionError):
        {event: event.load_event_data, response: response.load_responses, ranking: ranking.load_rankings}[module]()
    assert getattr(module, cache_name) is None
    assert path.read_text(encoding="utf-8") == "[]"


@pytest.mark.parametrize("kind", ["events", "attendees", "waitlist", "rankings"])
@pytest.mark.parametrize("invalid", [None, 3, "not a record", {}, {"user_id": "bad"}])
def test_mixed_valid_invalid_records_fail_closed_and_preserve_original(durable_files, kind, invalid):
    if kind == "events":
        key, loader, saver = "EVENTS_FILE", event.load_event_data, event.save_event_data
        raw = [stored_event(), invalid]
    elif kind == "rankings":
        key, loader, saver = "RANKING_FILE", ranking.load_rankings, ranking.save_rankings
        # Empty rank dictionaries are a supported legacy record with defaults.
        if isinstance(invalid, dict):
            invalid = {"rank": "invalid"}
        raw = {"1": asdict(ranking.UserRank("user1", 1, True, False, False)), "bad": invalid}
    else:
        key, loader, saver = "RESPONSES_FILE", response.load_responses, response.save_responses
        raw = {"Gathering": {"attendees": [], "waitlist": []}}
        raw["Gathering"][kind] = [registration(waiting=kind == "waitlist"), invalid]
    path = Path(durable_files[key])
    atomic_write_json(str(path), raw, cls=DataclassJSONEncoder)
    disk = path.read_bytes()
    with pytest.raises(ValueError):
        loader()
    with pytest.raises(RuntimeError):
        saver()
    assert path.read_bytes() == disk
    backups = list(path.parent.glob(f"{path.name}.corrupted-*.bak"))
    assert backups and all(backup.read_bytes() == disk for backup in backups)


def test_valid_mixed_legacy_records_load_without_rewriting(durable_files):
    path = Path(durable_files["RESPONSES_FILE"])
    legacy = asdict(registration())
    legacy["user_id"] = "1"
    legacy["extra_people"] = "0"
    legacy["behavior_confirmed"] = "yes"
    legacy.pop("display_name")
    legacy["timestamp"] = legacy["timestamp"].isoformat()
    raw = {"Gathering": [legacy], "Current": {"attendees": [], "waitlist": []}}
    atomic_write_json(str(path), raw, cls=DataclassJSONEncoder)
    old_waitlist = path.parent / "waitlist.json"
    atomic_write_json(str(old_waitlist), {"Gathering": [registration(2, waiting=True)]}, cls=DataclassJSONEncoder)
    durable_files["WAITLIST_FILE"] = str(old_waitlist)
    disk = path.read_bytes()
    with patch("offkai_bot.data.response.atomic_write_json", side_effect=AssertionError("read rewrote data")):
        data = response.load_responses()
    assert data["Gathering"]["attendees"][0].user_id == 1
    assert data["Gathering"]["attendees"][0].display_name is None
    assert data["Gathering"]["waitlist"][0].user_id == 2
    assert data["Current"] == {"attendees": [], "waitlist": []}
    assert path.read_bytes() == disk
    response.remove_from_waitlist("Gathering", 2)
    response.RESPONSE_DATA_CACHE = None
    assert response.get_waitlist("Gathering") == []  # No resurrection from the old waitlist file.


def test_invalid_legacy_waitlist_does_not_publish_partial_migration(durable_files):
    path = Path(durable_files["RESPONSES_FILE"])
    atomic_write_json(str(path), {"Gathering": [registration()]}, cls=DataclassJSONEncoder)
    legacy_path = path.parent / "waitlist.json"
    legacy_path.write_text('{"Gathering": [null]}', encoding="utf-8")
    durable_files["WAITLIST_FILE"] = str(legacy_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        response.load_responses()
    assert response.RESPONSE_DATA_CACHE is None
    assert path.read_bytes() == original
    assert legacy_path.read_text(encoding="utf-8") == '{"Gathering": [null]}'


def test_import_failed_write_keeps_original_cache_and_disk(durable_files):
    original = {"Gathering": response.EventData(attendees=[registration()], waitlist=[])}
    response.RESPONSE_DATA_CACHE = original
    response.save_responses()
    path = Path(durable_files["RESPONSES_FILE"])
    disk = path.read_bytes()
    with (
        patch("offkai_bot.data.atomic.os.replace", side_effect=OSError("disk unavailable")),
        pytest.raises(OSError),
    ):
        responses_transfer.replace_responses({})
    assert response.RESPONSE_DATA_CACHE is original
    assert path.read_bytes() == disk
    assert any(backup.read_bytes() == disk for backup in path.parent.glob("*.pre-import.bak"))


async def test_creation_send_failure_is_reported_but_event_survives_restart(durable_files):
    bot = MagicMock(spec=commands.Bot)
    cog = EventsCog(bot)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 123
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 1
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    thread = MagicMock(spec=discord.Thread)
    thread.id = 456
    thread.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "announcement failed"))
    interaction.channel.create_thread = AsyncMock(return_value=thread)
    with (
        patch("offkai_bot.cogs.events.validate_interaction_context"),
        patch("offkai_bot.cogs.events.register_deadline_reminders"),
        patch("offkai_bot.cogs.events.register_checkin_reminder"),
        pytest.raises(discord.HTTPException, match="announcement failed"),
    ):
        await cog._create_event(
            interaction,
            "Gathering",
            "Venue",
            "Address",
            "Maps",
            datetime(3024, 1, 1, tzinfo=UTC),
            None,
            [],
            None,
            None,
            None,
            False,
            None,
        )
    interaction.followup.send.assert_not_awaited()
    event.EVENT_DATA_CACHE = None
    recovered = event.get_event("Gathering")
    assert recovered.thread_id == 456
    assert recovered.channel_id == 123
    assert recovered.message_id is None


async def test_message_identity_save_failure_propagates_without_cache_mutation(durable_files):
    current = stored_event()
    current.message_id = 10
    event.EVENT_DATA_CACHE = [current]
    event.save_event_data()
    path = Path(durable_files["EVENTS_FILE"])
    original = path.read_bytes()
    message = MagicMock(spec=discord.Message)
    message.id = 20
    message.pin = AsyncMock()
    thread = MagicMock(spec=discord.Thread)
    thread.send = AsyncMock(return_value=message)
    with (
        patch("offkai_bot.event_actions.get_event_view"),
        patch("offkai_bot.data.atomic.os.replace", side_effect=OSError("disk unavailable")),
        pytest.raises(OSError),
    ):
        await event_actions.send_event_message(thread, current)
    assert current.message_id == 10
    assert path.read_bytes() == original
    message.pin.assert_not_awaited()


@pytest.mark.parametrize("failed_file", ["RESPONSES_FILE", "EVENTS_FILE"])
async def test_close_write_failures_leave_event_open_and_retryable(durable_files, failed_file):
    current = stored_event()
    event.EVENT_DATA_CACHE = [current]
    response.RESPONSE_DATA_CACHE = {
        current.event_name: response.EventData(
            attendees=[registration(2), replace(registration(), extra_people=1)], waitlist=[]
        )
    }
    event.save_event_data()
    response.save_responses()
    event_path = Path(durable_files["EVENTS_FILE"])
    response_path = Path(durable_files["RESPONSES_FILE"])
    original_event = event_path.read_bytes()
    original_responses = response_path.read_bytes()
    real_replace = atomic.os.replace

    def fail_selected_file(source, destination):
        if str(destination) == durable_files[failed_file]:
            raise OSError("close write failed")
        real_replace(source, destination)

    client = MagicMock(spec=discord.Client)
    with patch("offkai_bot.event_actions.update_event_message", new_callable=AsyncMock) as update_message:
        with (
            patch("offkai_bot.data.atomic.os.replace", side_effect=fail_selected_file),
            pytest.raises(OSError, match="close write failed"),
        ):
            await event_actions.perform_close_event(client, "gAtHeRiNg")
        assert event.get_event(current.event_name) is current
        assert current.open is True
        assert current.closed_attendance_count is None
        assert current.max_attendee_number is None
        assert event_path.read_bytes() == original_event
        if failed_file == "RESPONSES_FILE":
            assert response_path.read_bytes() == original_responses
            assert not response.has_complete_attendee_numbers(current.event_name)
        else:
            assert response.has_complete_attendee_numbers(current.event_name)
            assert response_path.read_bytes() != original_responses
        update_message.assert_not_awaited()

        # The same public close action can retry either partial-commit boundary.
        result = await event_actions.perform_close_event(client, "gAtHeRiNg")
        assert result is current
        assert current.open is False
        assert current.closed_attendance_count == 3
        assert current.max_attendee_number == 3
        assert response.has_complete_attendee_numbers(current.event_name)
        update_message.assert_awaited_once_with(client, current)

    event.EVENT_DATA_CACHE = None
    response.RESPONSE_DATA_CACHE = None
    recovered = event.get_event(current.event_name)
    assert not recovered.open
    assert recovered.closed_attendance_count == recovered.max_attendee_number == 3
    assert response.has_complete_attendee_numbers(recovered.event_name)


@pytest.mark.parametrize("archived", [False, True])
def test_invalid_close_does_not_change_attendee_numbers(durable_files, archived):
    current = stored_event()
    current.open = False
    current.archived = archived
    event.EVENT_DATA_CACHE = [current]
    error = EventArchivedError if archived else EventAlreadyClosedError
    with patch("offkai_bot.data.event.assign_attendee_numbers") as number, pytest.raises(error):
        event.set_event_open_status(current.event_name, False)
    number.assert_not_called()
