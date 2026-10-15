"""Organizer promotion must bypass capacity without restarting an already-confirmed choice."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from aiohttp import ClientConnectionError
from aiohttp.test_utils import TestClient, TestServer

from offkai_bot import admin_api
from offkai_bot.data import event as events
from offkai_bot.data import response as responses
from offkai_bot.data.event import Event

UID = 101000000000000001
HEADERS = {"Authorization": "Bearer synthetic-admin"}


@pytest.fixture
def promotion_context(monkeypatch):
    event = Event(
        "Manual promotion",
        "Venue",
        "Address",
        "",
        datetime.now(UTC) + timedelta(days=7),
        thread_id=999,
        max_capacity=0,
        open=True,
        signup_form={"fields": [], "payment_methods": {"Bank": "Synthetic bank instructions"}},
    )
    entry = responses.WaitlistEntry(
        UID,
        "Synthetic",
        2,
        True,
        True,
        event.event_name,
        datetime.now(UTC),
        extras_names=["Guest A", "Guest B"],
        payment_method=None,
        payment_selection_demotes=True,
        no_show_agreed=True,
    )
    events.EVENT_DATA_CACHE = [event]
    responses.RESPONSE_DATA_CACHE = {}
    responses.add_to_waitlist(event.event_name, entry)
    user = MagicMock(spec=discord.User, id=UID, send=AsyncMock())
    thread = MagicMock(spec=discord.Thread, id=999, archived=False, locked=False, add_user=AsyncMock())
    thread.guild.id = 555
    client = MagicMock(spec=discord.Client)
    client.is_ready.return_value = True
    client.get_channel.return_value = thread
    client.get_user.return_value = user
    monkeypatch.setattr(admin_api, "get_config", lambda: {"ADMIN_KEY": "synthetic-admin", "GUILDS": [555]})
    monkeypatch.setattr(admin_api, "update_event_message", AsyncMock(), raising=False)
    payload = {
        "event_name": event.event_name,
        "user_id": str(UID),
        "registration_timestamp": entry.timestamp.isoformat(),
    }
    return event, entry, user, thread, client, payload


async def test_frontend_promotion_bypasses_capacity_and_starts_one_fresh_choice(promotion_context):
    event, entry, user, thread, client, payload = promotion_context
    before = datetime.now(UTC)
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        assert (await http.post("/registrations/promote", json=payload)).status == 401
        response = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        assert response.status == 200
        result = await response.json()
        assert result["promoted"] is True and result["warnings"] == []
        current = responses.get_responses(event.event_name)[0]
        assert current.user_id == UID and current.extra_people == 2
        assert current.extras_names == entry.extras_names and current.no_show_agreed
        assert current.timestamp == entry.timestamp
        assert current.payment_method is None
        assert (
            before + timedelta(hours=72)
            <= current.payment_selection_expires_at
            <= datetime.now(UTC) + timedelta(hours=72)
        )
        assert responses.get_waitlist(event.event_name) == []
        user.send.assert_awaited_once()
        assert user.send.call_args.kwargs["view"].expires_at == current.payment_selection_expires_at
        thread.add_user.assert_awaited_once_with(user)
        deadline = current.payment_selection_expires_at
        repeat = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        assert repeat.status == 409
        assert (await repeat.json())["promoted"] is False
        assert responses.get_responses(event.event_name)[0].payment_selection_expires_at == deadline
        assert user.send.await_count == 1


async def test_frontend_promotion_rechecks_registration_after_preflight(promotion_context, monkeypatch):
    event, entry, _, thread, client, payload = promotion_context

    async def changed_registration(*args):
        responses.remove_from_waitlist(event.event_name, UID)
        replacement = responses.WaitlistEntry(**{**entry.__dict__, "timestamp": entry.timestamp + timedelta(seconds=1)})
        responses.add_to_waitlist(event.event_name, replacement)
        return thread

    monkeypatch.setattr(admin_api, "fetch_thread_for_event", changed_registration)
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        response = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        result = await response.json()
    assert response.status == 409
    assert result == {"error": "registration_changed", "promoted": False}
    assert responses.get_responses(event.event_name) == []
    assert responses.get_waitlist(event.event_name)[0].timestamp != entry.timestamp


@pytest.mark.parametrize("state", ["archived", "interest", "other_guild", "bot_unready"])
async def test_frontend_promotion_rejects_ineligible_context_without_writing(promotion_context, state):
    event, entry, user, thread, client, payload = promotion_context
    if state == "archived":
        event.archived = True
    elif state == "interest":
        event.interest_check = True
    elif state == "other_guild":
        thread.guild.id = 777
    else:
        client.is_ready.return_value = False
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        response = await http.post("/registrations/promote", json=payload, headers=HEADERS)
    assert response.status in (400, 403, 503)
    assert responses.get_responses(event.event_name) == []
    assert responses.get_waitlist(event.event_name) == [entry]
    user.send.assert_not_awaited()


async def test_frontend_promotion_survives_failed_dm(promotion_context):
    event, _, user, _, client, payload = promotion_context
    user.send.side_effect = ClientConnectionError("Synthetic DM failure")
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        response = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        result = await response.json()
    assert response.status == 200
    assert result["promoted"] is True
    assert any("DM" in warning for warning in result["warnings"])
    assert len(responses.get_responses(event.event_name)) == 1
    assert responses.get_waitlist(event.event_name) == []


async def test_concurrent_frontend_promotions_do_not_renew_the_deadline(promotion_context):
    event, _, user, _, client, payload = promotion_context
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_dm(*args, **kwargs):
        started.set()
        await release.wait()

    user.send.side_effect = delayed_dm
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:

        async def first_request():
            reply = await http.post("/registrations/promote", json=payload, headers=HEADERS)
            return reply.status, await reply.json()

        first = asyncio.create_task(first_request())
        await asyncio.wait_for(started.wait(), timeout=2)
        deadline = responses.get_responses(event.event_name)[0].payment_selection_expires_at
        second = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        assert second.status == 409
        assert (await second.json())["promoted"] is False
        release.set()
        status, result = await first
        assert status == 200 and result["promoted"] is True
    assert len(responses.get_responses(event.event_name)) == 1
    assert responses.get_responses(event.event_name)[0].payment_selection_expires_at == deadline
    assert user.send.await_count == 1


async def test_failed_promotion_write_preserves_waitlist_and_can_retry(promotion_context, monkeypatch):
    event, entry, user, _, client, payload = promotion_context
    write = responses.atomic_write_json
    monkeypatch.setattr(responses, "atomic_write_json", MagicMock(side_effect=OSError("Synthetic write failure")))
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        reply = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        assert reply.status == 502
        assert await reply.json() == {"error": "promotion_unconfirmed"}
        assert responses.get_responses(event.event_name) == []
        assert responses.get_waitlist(event.event_name) == [entry]
        user.send.assert_not_awaited()
        monkeypatch.setattr(responses, "atomic_write_json", write)
        reply = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        assert reply.status == 200
        assert (await reply.json())["promoted"] is True


async def test_promotion_without_payment_methods_numbers_closed_event_group(promotion_context):
    event, entry, user, _, client, payload = promotion_context
    event.signup_form = None
    event.open = False
    event.closed_attendance_count = 1
    event.max_attendee_number = 1
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        reply = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        assert reply.status == 200
        assert (await reply.json())["promoted"] is True
    current = responses.get_responses(event.event_name)[0]
    assert current.attendee_number == 2 and current.extras_attendee_numbers == [3, 4]
    assert current.extra_people == entry.extra_people
    assert current.payment_selection_expires_at is None
    assert "view" not in user.send.call_args.kwargs


async def test_promotion_reports_discord_thread_rejection_without_losing_payment_dm(promotion_context):
    event, entry, user, thread, client, payload = promotion_context
    thread.add_user.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        response = await http.post("/registrations/promote", json=payload, headers=HEADERS)
        result = await response.json()
    assert response.status == 200 and result["promoted"] is True
    assert len(result["warnings"]) == 1
    assert "thread" in result["warnings"][0].lower()
    assert "permissions" in result["warnings"][0].lower()
    current = responses.get_responses(event.event_name)[0]
    assert current.user_id == entry.user_id and current.payment_selection_expires_at is not None
    user.send.assert_awaited_once()
    assert user.send.call_args.kwargs["view"].expires_at == current.payment_selection_expires_at
