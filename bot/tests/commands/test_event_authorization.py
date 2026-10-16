"""Multi-guild regressions for event data and Discord side effects."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from offkai_bot.cogs.events import EventsCog, _require_guild_event
from offkai_bot.data import event as event_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event
from offkai_bot.data.response import EventData, WaitlistEntry
from offkai_bot.data.responses_transfer import export_responses_json
from offkai_bot.errors import EventNotFoundError, ResponsesImportError


@pytest.fixture
def scoped():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_channel_or_thread.side_effect = lambda channel_id: object() if channel_id == 10 else None
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock(defer=AsyncMock(), send_message=AsyncMock())
    interaction.followup = MagicMock(send=AsyncMock())
    interaction.user = MagicMock(send=AsyncMock())
    bot = MagicMock(spec=commands.Bot)
    bot.fetch_channel = AsyncMock(return_value=MagicMock(guild=MagicMock(id=2)))
    local = Event("Local", "v", "a", "g", datetime.now(UTC), channel_id=10, open=True)
    foreign = Event("Foreign", "v", "a", "g", datetime.now(UTC), channel_id=20, open=True)
    event_data.EVENT_DATA_CACHE = [local, foreign]
    response_data.RESPONSE_DATA_CACHE = {
        "Local": EventData(attendees=[], waitlist=[]),
        "Foreign": EventData(attendees=[], waitlist=[]),
    }
    return EventsCog(bot), interaction, local, foreign


@pytest.mark.parametrize(
    "command,kwargs",
    [
        ("modify_offkai", {"update_msg": "change", "venue": "changed"}),
        ("close_offkai", {}),
        ("reopen_offkai", {}),
        ("archive_offkai", {}),
        ("broadcast", {"message": "secret"}),
        ("delete_response", {"member": MagicMock()}),
        ("resend_confirmation", {}),
        ("promote", {"username": "123"}),
        ("attendance", {}),
        ("attendance_report", {}),
        ("waitlist", {}),
        ("drinks", {}),
    ],
)
async def test_foreign_event_rejected_before_side_effects(scoped, command, kwargs):
    cog, interaction, _, foreign = scoped
    with (
        patch("offkai_bot.cogs.events.fetch_thread_for_event", new_callable=AsyncMock) as fetch,
        patch("offkai_bot.cogs.events.perform_close_event", new_callable=AsyncMock) as close,
        patch("offkai_bot.cogs.events.remove_registration", new_callable=AsyncMock) as remove,
        patch("offkai_bot.cogs.events.persist_event_changes") as save,
        pytest.raises(EventNotFoundError),
    ):
        await getattr(EventsCog, command).callback(cog, interaction, event_name="Foreign", **kwargs)
    assert foreign.open and not foreign.archived and foreign.venue == "v"
    fetch.assert_not_awaited()
    close.assert_not_awaited()
    remove.assert_not_awaited()
    save.assert_not_called()
    interaction.followup.send.assert_not_awaited()
    interaction.response.send_message.assert_not_awaited()


async def test_cache_miss_fetch_checks_guild_and_supports_legacy_thread(scoped):
    cog, interaction, local, _ = scoped
    local.channel_id = None
    local.thread_id = 30
    cog.bot.fetch_channel.return_value = MagicMock(guild=MagicMock(id=1))
    assert await _require_guild_event(cog.bot, interaction, "Local") is local
    cog.bot.fetch_channel.assert_awaited_once_with(30)


async def test_missing_discord_ownership_fails_closed(scoped):
    cog, interaction, local, _ = scoped
    local.channel_id = None
    with pytest.raises(EventNotFoundError):
        await _require_guild_event(cog.bot, interaction, "Local")


async def test_autocomplete_hides_foreign_events_and_usernames(scoped):
    cog, interaction, _, _ = scoped
    choices = await cog.event_autocomplete_base(interaction, "")
    assert [choice.value for choice in choices] == ["Local"]
    interaction.namespace = MagicMock(event_name="Foreign")
    with patch("offkai_bot.cogs.events.get_waitlist") as read:
        assert await cog.waitlist_user_autocomplete(interaction, "") == []
    read.assert_not_called()
    interaction.guild = None
    assert await cog.event_autocomplete_base(interaction, "") == []


async def test_export_and_metadata_contain_only_invoking_guild(scoped):
    cog, interaction, _, _ = scoped
    await EventsCog.export_responses.callback(cog, interaction)
    payload = json.loads(interaction.user.send.call_args.kwargs["file"].fp.read())
    assert set(payload) == {"_export", "Local"}
    assert set(payload["_export"]["event_fingerprints"]) == {"Local"}


def attachment(payload):
    raw = json.dumps(payload).encode()
    return MagicMock(size=len(raw), read=AsyncMock(return_value=raw))


@pytest.mark.parametrize("metadata_only", [False, True])
@pytest.mark.parametrize("apply", [False, True])
async def test_import_rejects_foreign_keys_including_metadata(scoped, metadata_only, apply):
    cog, interaction, _, _ = scoped
    payload = json.loads(export_responses_json())
    if metadata_only:
        del payload["Foreign"]
    with (
        patch("offkai_bot.cogs.events.replace_responses") as replace,
        pytest.raises(EventNotFoundError),
    ):
        await EventsCog.import_responses.callback(cog, interaction, attachment(payload), apply=apply)
    replace.assert_not_called()
    interaction.followup.send.assert_not_awaited()


async def test_scoped_import_preserves_other_guild_and_scopes_rollback(scoped):
    cog, interaction, _, _ = scoped
    payload = json.loads(export_responses_json(data={"Local": response_data.RESPONSE_DATA_CACHE["Local"]}))
    payload["Local"]["attendees"] = [
        {
            "user_id": 5,
            "username": "local user",
            "event_name": "Local",
            "timestamp": datetime.now(UTC).isoformat(),
            "extra_people": 0,
            "behavior_confirmed": True,
            "arrival_confirmed": True,
        }
    ]
    foreign_data = response_data.RESPONSE_DATA_CACHE["Foreign"]
    with (
        patch("offkai_bot.cogs.events.replace_responses", return_value=None) as replace,
        patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock),
    ):
        await EventsCog.import_responses.callback(cog, interaction, attachment(payload), apply=True)
    assert replace.call_args.args[0]["Foreign"] is foreign_data
    assert len(replace.call_args.args[0]["Local"]["attendees"]) == 1
    files = interaction.followup.send.call_args.kwargs["files"]
    rollback = json.loads(files[-1].fp.read())
    assert set(rollback) == {"_export", "Local"}
    assert set(rollback["_export"]["event_fingerprints"]) == {"Local"}


async def test_signup_during_ownership_fetch_survives_and_conflicts_with_old_export(scoped):
    cog, interaction, _, _ = scoped
    payload = json.loads(export_responses_json(data={"Local": response_data.RESPONSE_DATA_CACHE["Local"]}))
    payload["Local"]["attendees"] = [
        {
            "user_id": 5,
            "username": "edit",
            "event_name": "Local",
            "timestamp": datetime.now(UTC).isoformat(),
            "extra_people": 0,
            "behavior_confirmed": True,
            "arrival_confirmed": True,
        }
    ]
    signup = WaitlistEntry(7, "new signup", 0, True, True, "Local", datetime.now(UTC))

    async def fetch_with_signup(channel_id):
        # A concurrent signup can replace the cache dictionary, not merely mutate it.
        response_data.RESPONSE_DATA_CACHE = {
            "Local": EventData(attendees=[], waitlist=[signup]),
            "Foreign": EventData(attendees=[], waitlist=[]),
            "New Event": EventData(attendees=[], waitlist=[]),
        }
        return MagicMock(guild=MagicMock(id=2))

    cog.bot.fetch_channel.side_effect = fetch_with_signup
    with (
        patch("offkai_bot.cogs.events.replace_responses") as replace,
        pytest.raises(ResponsesImportError, match="changed in the bot"),
    ):
        await EventsCog.import_responses.callback(cog, interaction, attachment(payload), apply=True)
    replace.assert_not_called()
    assert response_data.RESPONSE_DATA_CACHE["Local"]["waitlist"] == [signup]


async def test_known_foreign_guild_ownership_never_fetches_discord(scoped):
    cog, interaction, _, _ = scoped
    cog.bot.get_channel.return_value = MagicMock(guild=MagicMock(id=2))
    with pytest.raises(EventNotFoundError):
        await _require_guild_event(cog.bot, interaction, "Foreign")
    cog.bot.fetch_channel.assert_not_awaited()
    await EventsCog.export_responses.callback(cog, interaction)
    cog.bot.fetch_channel.assert_not_awaited()
    payload = json.loads(interaction.user.send.call_args.kwargs["file"].fp.read())
    assert set(payload) == {"_export", "Local"}
