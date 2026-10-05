from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from offkai_bot import payment_proof
from offkai_bot.data.event import Event
from offkai_bot.data.response import Response, WaitlistEntry
from offkai_bot.util import build_checkin_token


def event(name="Post Fest2 Offkai!"):
    return Event(
        name,
        "Venue",
        "Address",
        "",
        datetime.now(UTC) + timedelta(days=7),
        signup_form={"payment_methods": {"Test": "Synthetic instructions"}},
    )


@pytest.mark.parametrize("query", ["POST FEST2 OFFKAI", "post-fest2", "(post fest2)", "Post Fest2 Offkia"])
def test_name_matching_handles_case_partial_and_clear_typo(query):
    target = event()
    assert payment_proof.match_events(query, [target, event("Other gathering")]) == [target]


def test_names_do_not_guess_ambiguous_or_wrong_number():
    events = [event("Post Fest2 Offkai!"), event("Post Fest2 Dinner")]
    assert payment_proof.match_events("post fest2", events) == events
    assert payment_proof.match_events("Post Fest3 Offkai", events) == []
    assert payment_proof.match_events("unrelated", events) == []
    assert payment_proof.match_events("po", events) == []
    twins = [event("Post Fest2 Offkai!"), event("Post Fest2 Offkai?")]
    assert payment_proof.match_events("postfest2offkai", twins) == twins


@pytest.mark.parametrize("waitlisted", [False, True])
def test_candidates_only_include_sender_payment_registrations(monkeypatch, waitlisted):
    target, archived, interest, default = event(), event("Archived"), event("Interest"), event("Default")
    archived.archived, interest.interest_check, default.signup_form = True, True, None
    outsider = event("Someone else's event")
    uid = 101000000000000001
    entry_type = WaitlistEntry if waitlisted else Response
    entry = entry_type(uid, "Synthetic", 0, True, True, target.event_name, datetime.now(UTC))
    monkeypatch.setattr(payment_proof, "load_event_data", lambda: [target, archived, interest, default, outsider])
    monkeypatch.setattr(
        payment_proof, "get_responses", lambda name: [] if waitlisted or name == outsider.event_name else [entry]
    )
    monkeypatch.setattr(
        payment_proof, "get_waitlist", lambda name: [entry] if waitlisted and name != outsider.event_name else []
    )
    assert payment_proof.registered_payment_events(uid) == [target]


def message(content="payment proof post fest2", *, guild=None, bot=False):
    return MagicMock(
        spec=discord.Message,
        content=content,
        guild=guild,
        author=MagicMock(id=101000000000000001, bot=bot),
        attachments=[MagicMock(spec=discord.Attachment)],
        reply=AsyncMock(),
    )


async def test_private_handler_replacement_paid_and_failure_responses(monkeypatch):
    target = event()
    monkeypatch.setattr(payment_proof, "registered_payment_events", lambda uid: [target])
    upload = AsyncMock(return_value={"payment": {"paid": False}, "replaced": False})
    monkeypatch.setattr(payment_proof, "upload_attachment", upload)
    msg = message()
    assert await payment_proof.handle_payment_proof(msg)
    upload.assert_awaited_once_with(msg.attachments[0], target, msg.author.id)
    assert msg.reply.call_args.args[0] == "Payment proof received for Post Fest2 Offkai!. Awaiting confirmation."
    upload.return_value = {"payment": {"paid": True}, "replaced": True}
    msg = message("i paid POST FEST2")
    await payment_proof.handle_payment_proof(msg)
    assert "updated" in msg.reply.call_args.args[0] and "remains confirmed" in msg.reply.call_args.args[0]
    upload.side_effect = RuntimeError("Synthetic storage failure")
    msg = message("proof payment proof post fest2")
    await payment_proof.handle_payment_proof(msg)
    assert "Couldn't save" in msg.reply.call_args.args[0]
    assert "received" not in msg.reply.call_args.args[0]


async def test_handler_ignores_guilds_bots_unrelated_and_refuses_missing_or_ambiguous(monkeypatch):
    upload = AsyncMock()
    monkeypatch.setattr(payment_proof, "upload_attachment", upload)
    for msg in [message(guild=MagicMock()), message(bot=True), message("hello")]:
        assert not await payment_proof.handle_payment_proof(msg)
        msg.reply.assert_not_awaited()
    monkeypatch.setattr(payment_proof, "registered_payment_events", lambda uid: [event(), event("Post Fest2 Dinner")])
    msg = message()
    await payment_proof.handle_payment_proof(msg)
    assert "Which event" in msg.reply.call_args.args[0]
    for content, expected in [("payment proof", "include the event name"), ("payment proof other", "couldn't find")]:
        msg = message(content)
        await payment_proof.handle_payment_proof(msg)
        assert expected in msg.reply.call_args.args[0]
    msg = message("payment proof post fest2 offkai")
    msg.attachments = []
    await payment_proof.handle_payment_proof(msg)
    assert "attach your payment screenshot" in msg.reply.call_args.args[0]
    upload.assert_not_awaited()


async def test_actual_multipart_adapter_uses_signed_identity_and_bounds_download(monkeypatch):
    target, uid = event(), 101000000000000001
    downloaded = b"synthetic-image"
    calls = []

    async def image(request):
        return web.Response(body=downloaded)

    async def upload(request):
        form = await request.post()
        assert form["token"] == build_checkin_token(uid, target.event_name, "synthetic-key")
        assert form["image"].file.read() == downloaded
        calls.append(True)
        return web.json_response({"payment": {"paid": False}, "replaced": True})

    app = web.Application(client_max_size=12 * 1024 * 1024)
    app.router.add_get("/image", image)
    app.router.add_post("/api/payment-proof", upload)
    monkeypatch.setattr(payment_proof, "get_config", lambda: {"ADMIN_KEY": "synthetic-key"})
    async with TestServer(app) as server:
        monkeypatch.setenv("PROOF_UPLOAD_URL", str(server.make_url("/")))
        attachment = MagicMock(
            spec=discord.Attachment,
            size=len(downloaded),
            content_type="image/png",
            filename="proof.png",
            url=str(server.make_url("/image")),
        )
        assert (await payment_proof.upload_attachment(attachment, target, uid))["replaced"]
        attachment.size = payment_proof.MAX_IMAGE_BYTES + 1
        with pytest.raises(ValueError):
            await payment_proof.upload_attachment(attachment, target, uid)
        attachment.size = 1
        downloaded = b"a" * (payment_proof.MAX_IMAGE_BYTES + 1)
        with pytest.raises(ValueError):
            await payment_proof.upload_attachment(attachment, target, uid)
        assert len(calls) == 1
