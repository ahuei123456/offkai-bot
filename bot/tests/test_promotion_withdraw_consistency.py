# tests/test_promotion_withdraw_consistency.py
"""Regressions for promotion/withdrawal consistency: rank credit on promotion (CONS-08),
the RSVP/QR link in manual-promotion DMs (CONS-09), and withdrawals that finish their
cleanup even when every notification fails (CONS-10)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from offkai_bot import payment_selection
from offkai_bot.cogs.events import EventsCog
from offkai_bot.data import event as event_data
from offkai_bot.data import ranking as ranking_data
from offkai_bot.data import response as response_data
from offkai_bot.data.event import Event
from offkai_bot.data.ranking import get_rank, update_rank
from offkai_bot.data.response import Response, WaitlistEntry, add_response, add_to_waitlist, get_responses, get_waitlist
from offkai_bot.interactions import ClosedEvent, OpenEvent, build_promotion_message


@pytest.fixture(autouse=True)
def empty_caches():
    """Start from empty in-memory data: the module's temp files are shared between tests."""
    event_data.EVENT_DATA_CACHE = []
    response_data.RESPONSE_DATA_CACHE = {}
    ranking_data.RANKING_DATA_CACHE = {}


def _event(name: str, *, open_: bool = True, max_capacity: int | None = 2, **kwargs) -> Event:
    now = datetime.now(UTC)
    event = Event(
        event_name=name,
        venue="v",
        address="a",
        google_maps_link="",
        event_datetime=now + timedelta(days=30),
        event_deadline=now + timedelta(days=7),
        channel_id=456,
        thread_id=111,
        open=open_,
        max_capacity=max_capacity,
        **kwargs,
    )
    event_data.EVENT_DATA_CACHE = [event]
    return event


def _response(event: Event, user_id: int, name: str, extra: int = 0) -> Response:
    return Response(
        user_id=user_id,
        username=name,
        extra_people=extra,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event.event_name,
        timestamp=datetime.now(UTC),
    )


def _waitlisted(event: Event, user_id: int, name: str) -> WaitlistEntry:
    return WaitlistEntry(
        user_id=user_id,
        username=name,
        extra_people=0,
        behavior_confirmed=True,
        arrival_confirmed=True,
        event_name=event.event_name,
        timestamp=datetime.now(UTC),
    )


def _withdraw_interaction(user_id: int, name: str) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = user_id
    interaction.user.name = name
    interaction.user.mention = f"<@{user_id}>"
    interaction.user.send = AsyncMock()
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.channel.remove_user = AsyncMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.client = MagicMock()
    interaction.client.get_channel.return_value = None
    interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))
    return interaction


def _http_error(cls=discord.HTTPException):
    return cls(MagicMock(status=403 if cls is discord.Forbidden else 500), "failed")


# --- CONS-08: promotion earns the same rank credit that withdrawal later removes ---


async def test_auto_promotion_credits_rank_so_withdrawal_balances():
    event = _event("Rank Event")
    add_response(event.event_name, _response(event, 100, "UserA", extra=1))
    add_to_waitlist(event.event_name, _waitlisted(event, 200, "UserB"))
    update_rank(200, "UserB")  # One earlier offkai.

    await OpenEvent(event).withdraw.callback(_withdraw_interaction(100, "UserA"))

    assert [r.user_id for r in get_responses(event.event_name)] == [200]
    assert get_rank(200, "UserB") == 2

    await OpenEvent(event).withdraw.callback(_withdraw_interaction(200, "UserB"))

    assert get_rank(200, "UserB") == 1  # Was 1 -> 1 -> 0 before promotions earned credit.


async def test_payment_expiry_demotion_reverses_rank_credit():
    event = _event("Expiry Event", signup_form={"fields": [], "payment_methods": {"Cash": "Pay at door"}})
    expired = _response(event, 300, "UserC")
    update_rank(300, "UserC")
    update_rank(300, "UserC")  # Earlier offkai + this promotion.
    client = MagicMock(spec=discord.Client)
    client.get_user.return_value = MagicMock(send=AsyncMock())

    with (
        patch.object(payment_selection, "expire_payment_selections", return_value=[expired]),
        patch.object(payment_selection, "get_payment_expiry_backfill", return_value=None),
        patch.object(payment_selection, "update_event_message", new_callable=AsyncMock),
    ):
        await payment_selection._expire_event_payments(client, event)

    assert get_rank(300, "UserC") == 1  # Re-promotion would then return it to 2, not 3.


# --- CONS-09: manual promotion DMs carry the attendee's RSVP / QR link ---


def test_promotion_message_includes_rsvp_link_when_configured():
    event = _event("Link Event")
    response = _response(event, 400, "UserD")
    with patch("offkai_bot.interactions.build_checkin_url", return_value="https://rsvp.example/?token=t"):
        manual = build_promotion_message(event, response, manual=True)
        automatic = build_promotion_message(event, response)

    for message in (manual, automatic):
        assert "RSVP Page / QR Code:** https://rsvp.example/?token=t" in message
        assert "RSVPページ / QRコード:** https://rsvp.example/?token=t" in message
    assert "manually promoted" in manual
    assert "automatically moved" in automatic


def test_promotion_message_omits_link_when_unconfigured():
    event = _event("No Link Event")
    with patch("offkai_bot.interactions.build_checkin_url", return_value=""):
        message = build_promotion_message(event, _response(event, 401, "UserE"), manual=True)
    assert "RSVP" not in message


async def test_manual_promote_command_dm_contains_rsvp_link_and_credits_rank():
    event = _event("Manual Event")
    add_to_waitlist(event.event_name, _waitlisted(event, 500, "UserF"))
    bot = MagicMock(spec=commands.Bot)
    promoted_user = MagicMock(send=AsyncMock())
    bot.fetch_user = AsyncMock(return_value=promoted_user)
    bot.get_channel.return_value = None
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = None
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.response = MagicMock(defer=AsyncMock())
    interaction.followup = MagicMock(send=AsyncMock())

    with (
        patch("offkai_bot.cogs.events.validate_guild_context"),
        patch("offkai_bot.cogs.events.update_event_message", new_callable=AsyncMock),
        patch("offkai_bot.interactions.build_checkin_url", return_value="https://rsvp.example/?token=m"),
    ):
        await EventsCog(bot).promote.callback(EventsCog(bot), interaction, event.event_name, "500")

    dm = promoted_user.send.await_args.args[0]
    assert "https://rsvp.example/?token=m" in dm
    assert get_rank(500, "UserF") == 1


# --- CONS-10: withdrawal cleanup and promotion never depend on notifications ---


async def test_withdraw_cleans_up_and_promotes_when_every_notification_fails():
    event = _event("Notify Fail Event", open_=False, closed_attendance_count=2, role_id=777, creator_id=1)
    add_response(event.event_name, _response(event, 600, "UserG", extra=1))
    add_to_waitlist(event.event_name, _waitlisted(event, 700, "UserH"))
    interaction = _withdraw_interaction(600, "UserG")
    interaction.user.send.side_effect = _http_error(discord.Forbidden)
    interaction.response.send_message.side_effect = _http_error()
    interaction.client.fetch_user.side_effect = _http_error()  # Creator and promoted-user DMs fail too.

    with patch("offkai_bot.interactions.remove_event_role", new_callable=AsyncMock) as remove_role:
        await ClosedEvent(event).withdraw.callback(interaction)

    assert [r.user_id for r in get_responses(event.event_name)] == [700]
    assert get_waitlist(event.event_name) == []
    interaction.channel.remove_user.assert_awaited_once_with(interaction.user)
    remove_role.assert_awaited_once()


async def test_withdraw_rejected_for_archived_event():
    event = _event("Archived Event", open_=False, archived=True)
    add_response(event.event_name, _response(event, 800, "UserI"))
    interaction = _withdraw_interaction(800, "UserI")

    await ClosedEvent(event).withdraw.callback(interaction)

    assert [r.user_id for r in get_responses(event.event_name)] == [800]
    interaction.channel.remove_user.assert_not_awaited()
    message = interaction.response.send_message.await_args.args[0]
    assert "archived" in message


async def test_withdraw_error_message_has_single_prefix():
    event = _event("Prefix Event")
    interaction = _withdraw_interaction(900, "Nobody")

    await OpenEvent(event).withdraw.callback(interaction)

    message = interaction.response.send_message.await_args.args[0]
    assert message.startswith("❌ ") and not message.startswith("❌ ❌")


async def test_admin_removal_still_promotes_when_rank_write_fails():
    from offkai_bot.registration_removal import remove_registration

    event = _event("Rank Fail Event")
    add_response(event.event_name, _response(event, 1000, "UserJ", extra=1))
    add_to_waitlist(event.event_name, _waitlisted(event, 1100, "UserK"))
    member = MagicMock(spec=discord.Member)
    member.id, member.name = 1000, "UserJ"
    client = MagicMock()
    client.get_channel.return_value = None
    client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))

    with patch("offkai_bot.registration_removal.decrease_rank", side_effect=OSError("disk full")):
        result = await remove_registration(client, event, member, None)

    assert result["promoted"] == [1100]
