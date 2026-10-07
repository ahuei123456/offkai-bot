from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer
from offkai_bot import admin_api
from offkai_bot.data.event import Event
from offkai_bot.data.response import (
    Response,
    WaitlistEntry,
    add_response,
    add_to_waitlist,
    get_responses,
    get_waitlist,
    load_responses,
)


@pytest.mark.parametrize("waitlisted", [False, True])
async def test_admin_removal_uses_real_data_and_promotes_only_freed_places(monkeypatch, mock_paths, waitlisted):
    Path(mock_paths["responses"]).write_text("{}")
    load_responses()
    uid, next_uid = 101000000000000001, 101000000000000002
    event = Event(
        "Removal test",
        "Venue",
        "Address",
        "",
        datetime.now(UTC) + timedelta(days=7),
        thread_id=999,
        max_capacity=2,
        open=True,
    )
    kwargs = dict(
        user_id=uid,
        username="Removed user",
        extra_people=1,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event.event_name,
        timestamp=datetime.now(UTC),
    )
    if waitlisted:
        add_to_waitlist(event.event_name, WaitlistEntry(**kwargs))
    else:
        add_response(event.event_name, Response(**kwargs))
    add_to_waitlist(event.event_name, WaitlistEntry(**{**kwargs, "user_id": next_uid, "username": "Next user"}))
    user = MagicMock(spec=discord.User, id=uid, name="Removed user", send=AsyncMock())
    next_user = MagicMock(spec=discord.User, id=next_uid, send=AsyncMock())
    thread = MagicMock(spec=discord.Thread, id=999, remove_user=AsyncMock())
    thread.guild.id = 555
    client = MagicMock(spec=discord.Client)
    client.is_ready.return_value = True
    client.get_channel.return_value = thread
    client.get_user.return_value = user
    client.fetch_user = AsyncMock(return_value=next_user)
    monkeypatch.setattr(admin_api, "get_config", lambda: {"ADMIN_KEY": "synthetic-admin", "GUILDS": [555]})
    monkeypatch.setattr(admin_api, "get_event", lambda name: event)
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        payload = {"event_name": event.event_name, "user_id": str(uid)}
        # Wrong credentials and malformed identities must not mutate the cache/file.
        assert (await http.post("/registrations/remove", json=payload)).status == 401
        assert (
            await http.post(
                "/registrations/remove",
                json={**payload, "user_id": "bad"},
                headers={"Authorization": "Bearer synthetic-admin"},
            )
        ).status == 400
        reply = await http.post(
            "/registrations/remove", json=payload, headers={"Authorization": "Bearer synthetic-admin"}
        )
        assert reply.status == 200
        result = await reply.json()
        assert result["freed_spots"] == (0 if waitlisted else 2)
        assert result["promoted"] == ([] if waitlisted else [next_uid])
        assert result["warnings"] == []
        assert [r.user_id for r in get_responses(event.event_name)] == ([] if waitlisted else [next_uid])
        assert [r.user_id for r in get_waitlist(event.event_name)] == ([next_uid] if waitlisted else [])
        thread.remove_user.assert_awaited_once_with(user)
        user.send.assert_awaited_once()
        duplicate = await http.post(
            "/registrations/remove", json=payload, headers={"Authorization": "Bearer synthetic-admin"}
        )
        assert duplicate.status == 404
        assert thread.remove_user.await_count == 1


async def test_admin_removal_refuses_an_unready_bot(monkeypatch):
    client = MagicMock(spec=discord.Client)
    client.is_ready.return_value = False
    monkeypatch.setattr(admin_api, "get_config", lambda: {"ADMIN_KEY": "synthetic-admin"})
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        reply = await http.post("/registrations/remove", json={}, headers={"Authorization": "Bearer synthetic-admin"})
        assert reply.status == 503


async def test_payment_confirmation_requires_auth_registration_and_reports_dm_failure(monkeypatch):
    uid = 101000000000000001
    event = Event("Payment test", "Venue", "Address", "", datetime.now(UTC))
    user = MagicMock(spec=discord.User, send=AsyncMock())
    client = MagicMock(spec=discord.Client)
    client.is_ready.return_value = True
    client.get_user.return_value = user
    monkeypatch.setattr(admin_api, "get_config", lambda: {"ADMIN_KEY": "synthetic-admin"})
    monkeypatch.setattr(admin_api, "registered_payment_events", lambda user_id: [event] if user_id == uid else [])
    payload = {"event_name": event.event_name, "user_id": str(uid)}
    headers = {"Authorization": "Bearer synthetic-admin"}
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        assert (await http.post("/payments/confirm", json=payload)).status == 401
        assert (
            await http.post("/payments/confirm", json={**payload, "event_name": "Other"}, headers=headers)
        ).status == 404
        user.send.assert_not_awaited()
        assert (await http.post("/payments/confirm", json=payload, headers=headers)).status == 200
        user.send.assert_awaited_once_with("Payment confirmed for Payment test!")
        user.send.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "DM blocked")
        assert (await http.post("/payments/confirm", json=payload, headers=headers)).status == 502


@pytest.mark.parametrize("failure,status", [(discord.NotFound, 404), (discord.Forbidden, 403), (RuntimeError, 503)])
async def test_preflight_failure_explicitly_reports_no_removal(monkeypatch, failure, status):
    event = Event("Preflight", "Venue", "Address", "", datetime.now(UTC), thread_id=999)
    client = MagicMock(spec=discord.Client)
    client.is_ready.return_value = True
    client.get_user.return_value = None
    error = RuntimeError("Unavailable") if failure is RuntimeError else failure(MagicMock(status=status), "Unavailable")
    client.fetch_user = AsyncMock(side_effect=error)
    thread = MagicMock(spec=discord.Thread)
    thread.guild.id = 555
    remove = AsyncMock()
    monkeypatch.setattr(admin_api, "remove_registration", remove)
    monkeypatch.setattr(admin_api, "get_config", lambda: {"ADMIN_KEY": "synthetic-admin", "GUILDS": [555]})
    monkeypatch.setattr(admin_api, "get_event", lambda name: event)
    monkeypatch.setattr(admin_api, "fetch_thread_for_event", AsyncMock(return_value=thread))
    async with TestClient(TestServer(admin_api.create_admin_app(client))) as http:
        reply = await http.post(
            "/registrations/remove",
            json={"event_name": event.event_name, "user_id": "101000000000000001"},
            headers={"Authorization": "Bearer synthetic-admin"},
        )
        assert reply.status == status
        assert (await reply.json())["removed"] is False
        remove.assert_not_awaited()


@pytest.mark.parametrize("port_mode", ["invalid", "occupied", "available"])
async def test_optional_admin_api_real_startup_failures_do_not_block_bot(monkeypatch, port_mode):
    import socket

    from offkai_bot import main

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    if port_mode == "occupied":
        listener.listen()
    else:
        listener.close()
    monkeypatch.setenv("ADMIN_API_HOST", "127.0.0.1")
    monkeypatch.setenv("ADMIN_API_PORT", "invalid" if port_mode == "invalid" else str(port))
    monkeypatch.setattr(main, "settings", {"GUILDS": []})
    monkeypatch.setattr(main, "get_config", lambda: {})
    for name in ["load_event_data", "load_responses", "load_rankings", "start_alert_loop"]:
        monkeypatch.setattr(main, name, MagicMock())
    monkeypatch.setattr(main, "load_and_update_events", AsyncMock())
    client = main.OffkaiClient(intents=discord.Intents.none())
    client.load_extension = AsyncMock()
    try:
        await client.setup_hook()
        assert client.load_extension.await_count == 2
        main.load_and_update_events.assert_awaited_once_with(client)
        main.start_alert_loop.assert_called_once_with(client)
        assert (client.admin_api is not None) is (port_mode == "available")
    finally:
        await client.close()
        listener.close()
