"""Persisted payment-choice expiry, caught up on startup and checked every minute."""

import logging
from datetime import UTC, datetime

import discord
from discord.ext import tasks

from offkai_bot.data.event import Event, load_event_data
from offkai_bot.data.response import (
    clear_payment_expiry_backfill,
    expire_payment_selections,
    get_payment_expiry_backfill,
    get_waitlist,
)
from offkai_bot.event_actions import fetch_thread_for_event, update_event_message
from offkai_bot.interactions import promote_waitlist_batch
from offkai_bot.role_management import remove_event_role

_log = logging.getLogger(__name__)


_processing_events: set[str] = set()


async def expire_pending_payments(client: discord.Client) -> None:
    for event in load_event_data():
        if event.event_name in _processing_events:
            continue
        _processing_events.add(event.event_name)
        try:
            await _expire_event_payments(client, event)
        finally:
            _processing_events.discard(event.event_name)


async def _expire_event_payments(client: discord.Client, event: Event) -> None:
    now = datetime.now(UTC)
    if (
        event.archived
        or event.interest_check
        or event.event_datetime <= now
        or not (event.signup_form or {}).get("payment_methods")
    ):
        return
    try:
        # One atomic roster transaction before any Discord await.
        expired = expire_payment_selections(event, now)
    except Exception:
        _log.exception("Payment expiry could not be saved for %r; retrying next tick", event.event_name)
        return
    if not expired and get_payment_expiry_backfill(event.event_name) is None:
        return
    if expired and event.role_id:
        try:
            thread = await fetch_thread_for_event(client, event)
            for entry in expired:
                await remove_event_role(thread.guild, entry.user_id, event.role_id, event=event)
        except Exception:
            _log.exception("Expired payment participant role cleanup failed for %r", event.event_name)
    for entry in expired:
        try:
            user = client.get_user(entry.user_id) or await client.fetch_user(entry.user_id)
            if not any(
                w.user_id == entry.user_id and w.timestamp == entry.timestamp for w in get_waitlist(event.event_name)
            ):
                continue  # Withdrawn or manually promoted while the user lookup was pending.
            await user.send(
                f"Your 72-hour payment-method selection window for **{event.event_name}** expired. "
                "You and your guests have moved to the end of the waitlist. "
                "Contact the organizer to be promoted again and receive a new payment-choice window.\n"
                f"**{event.event_name}**の支払い方法選択期限が過ぎたため、同行者とともに"
                "ウェイトリストの最後に移動しました。再昇格については主催者にお問い合わせください。"
            )
        except Exception:
            _log.exception("Payment expiry notification failed for user %s", entry.user_id)
    pending = get_payment_expiry_backfill(event.event_name)
    if pending is not None:
        try:
            await promote_waitlist_batch(
                event,
                client,
                target_attendance=pending["target_count"],
                eligible_registrations=set(pending["eligible_registrations"]),
                excluded_user_ids=set(pending["excluded_user_ids"]),
            )
            clear_payment_expiry_backfill(event.event_name, pending)
        except Exception:
            _log.exception("Waitlist backfill remains saved for retry after payment expiry for %r", event.event_name)
    try:
        await update_event_message(client, event)
    except Exception:
        _log.exception("Event message update failed after payment expiry for %r", event.event_name)


_client: discord.Client | None = None


@tasks.loop(minutes=1.0)
async def payment_selection_loop() -> None:
    if _client is not None:
        try:
            await expire_pending_payments(_client)
        except Exception:
            _log.exception("Payment expiry sweep failed; retrying next tick")


@payment_selection_loop.before_loop
async def before_payment_selection_loop() -> None:
    if _client is not None:
        await _client.wait_until_ready()


def start_payment_selection_loop(client: discord.Client) -> None:
    global _client
    _client = client
    if not payment_selection_loop.is_running():
        payment_selection_loop.start()


def stop_payment_selection_loop() -> None:
    global _client
    payment_selection_loop.cancel()
    _client = None
