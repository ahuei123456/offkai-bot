"""Every promotion snapshot keeps a registration visible to payment cleanup."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import response as data
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.errors import DuplicateResponseError
from offkai_bot.interactions import promote_waitlist_batch


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("failure", [None, "encode", "replace"])
async def test_promotion_snapshots_and_failure_rollback(manual, failure, sample_event_list, mock_config):
    event = sample_event_list[0]
    event.open = False
    event.closed_attendance_count = 10
    event.max_attendee_number = 15
    event.role_id = None
    entries = [
        data.WaitlistEntry(
            user_id=uid,
            username=f"user{uid}",
            display_name=f"Name {uid}",
            extra_people=1,
            behavior_confirmed=True,
            arrival_confirmed=True,
            event_name=event.event_name,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            drinks=["Tea", "Water"],
            extras_names=["Guest"],
            payment_method="PayPay",
            no_show_agreed=True,
        )
        for uid in (101, 102, 103)
    ]
    data.RESPONSE_DATA_CACHE = {event.event_name: data.EventData(attendees=[], waitlist=entries)}
    data.save_responses()
    path = Path(mock_config["RESPONSES_FILE"])
    before = path.read_bytes()
    cache = data.load_responses()
    original_event_data = cache[event.event_name]
    snapshots = [json.loads(before)]
    real_write = data.atomic_write_json

    def record_write(file_path, snapshot, **kwargs):
        if failure == "encode":
            raise TypeError("serialization failed")
        real_write(file_path, snapshot, **kwargs)
        snapshots.append(json.loads(path.read_text()))

    client = MagicMock(spec=discord.Client)
    client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    target = 102 if manual else 101

    async def promote():
        if manual:
            await EventsCog.promote.callback(EventsCog(client), interaction, event.event_name, str(target))
        else:
            assert await promote_waitlist_batch(event, client, freed_spots=2) == [101, 102, 103]

    with (
        patch.object(data, "atomic_write_json", side_effect=record_write),
        patch("offkai_bot.cogs.events.get_event", return_value=event),
        patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock),
        patch("offkai_bot.data.event.save_event_data"),
        patch("offkai_bot.data.atomic.os.replace", side_effect=OSError("replace failed"))
        if failure == "replace"
        else patch("offkai_bot.interactions.build_checkin_url", return_value=None),
    ):
        if failure:
            with pytest.raises((OSError, TypeError)):
                await promote()
            assert path.read_bytes() == before
            assert cache[event.event_name] is original_event_data
            assert cache[event.event_name]["waitlist"] == entries
            assert cache[event.event_name]["attendees"] == []
            assert event.max_attendee_number == 15
            client.fetch_user.assert_not_awaited()
            interaction.followup.send.assert_not_awaited()
            assert not list(path.parent.glob(f"{path.name}.*.tmp"))
        else:
            await promote()
            assert len(snapshots) == (2 if manual else 4)
            for snapshot in snapshots:
                event_snapshot = snapshot[event.event_name]
                # Model cleanup's exact event/user registration membership test.
                ids = [row["user_id"] for key in ("attendees", "waitlist") for row in event_snapshot[key]]
                assert sorted(ids) == [101, 102, 103]
            promoted = next(row for row in data.get_responses(event.event_name) if row.user_id == target)
            original = next(entry for entry in entries if entry.user_id == target)
            for key, value in original.__dict__.items():
                assert getattr(promoted, key) == value
            assert promoted.attendee_number == 16
            assert promoted.extras_attendee_numbers == [17]
            expected = deepcopy(cache)
            data.RESPONSE_DATA_CACHE = None
            assert data.load_responses() == expected
    # Failure also leaves the reloaded disk view identical to the original cache.
    if failure:
        data.RESPONSE_DATA_CACHE = None
        assert json.dumps(data.load_responses(), cls=DataclassJSONEncoder) == json.dumps(
            cache, cls=DataclassJSONEncoder
        )


def test_duplicate_promotion_preserves_both_lists(sample_event_list):
    event = sample_event_list[0]
    entry = data.WaitlistEntry(1, "user", 0, True, True, event.event_name, datetime.now(UTC))
    existing = data.Response(**entry.__dict__)
    data.RESPONSE_DATA_CACHE = {event.event_name: data.EventData(attendees=[existing], waitlist=[entry])}
    with patch.object(data, "atomic_write_json") as write:
        with pytest.raises(DuplicateResponseError):
            data.promote_waitlist_response(event)
        write.assert_not_called()
    assert data.get_waitlist(event.event_name) == [entry]
    assert data.get_responses(event.event_name) == [existing]


@pytest.mark.parametrize(
    "open_event, existing_number, closed_count, historic_max, expected",
    [
        (True, None, None, None, None),
        (True, 7, None, None, 8),
        (False, 7, 10, 15, 16),
        (False, 20, 10, 15, 21),
    ],
)
def test_promotion_reuses_numbering_rules(
    sample_event_list, open_event, existing_number, closed_count, historic_max, expected
):
    event = sample_event_list[0]
    event.open = open_event
    event.closed_attendance_count = closed_count
    event.max_attendee_number = historic_max
    existing = data.Response(
        1, "existing", 0, True, True, event.event_name, datetime.now(UTC), attendee_number=existing_number
    )
    entry = data.WaitlistEntry(2, "waiting", 1, True, True, event.event_name, datetime.now(UTC))
    data.RESPONSE_DATA_CACHE = {event.event_name: data.EventData(attendees=[existing], waitlist=[entry])}
    with patch("offkai_bot.data.event.save_event_data") as save_event:
        promoted = data.promote_waitlist_response(event)
        assert promoted is not None
        assert promoted.attendee_number == expected
        assert promoted.extras_attendee_numbers == ([] if expected is None else [expected + 1])
        assert save_event.call_count == (0 if expected is None else 1)
        if expected is not None:
            assert event.max_attendee_number == expected + 1


def test_event_metadata_failure_keeps_committed_response_consistent(sample_event_list, mock_config):
    event = sample_event_list[0]
    event.open = False
    entry = data.WaitlistEntry(1, "waiting", 0, True, True, event.event_name, datetime.now(UTC))
    data.RESPONSE_DATA_CACHE = {event.event_name: data.EventData(attendees=[], waitlist=[entry])}
    with (
        patch("offkai_bot.data.event.save_event_data", side_effect=OSError("event metadata failed")),
        pytest.raises(OSError),
    ):
        data.promote_waitlist_response(event)
    assert data.get_waitlist(event.event_name) == []
    assert data.get_responses(event.event_name)[0].user_id == 1
    expected = deepcopy(data.load_responses())
    data.RESPONSE_DATA_CACHE = None
    assert data.load_responses() == expected
