"""Persisted payment-choice expiry, caught up on startup and checked every minute."""

import logging
from datetime import UTC, datetime

import discord

from offkai_bot.data.event import load_event_data
from offkai_bot.data.response import expire_payment_selections, get_waitlist
from offkai_bot.event_actions import fetch_thread_for_event, update_event_message
from offkai_bot.interactions import promote_waitlist_batch
from offkai_bot.role_management import remove_event_role

_log = logging.getLogger(__name__)


async def expire_pending_payments(client: discord.Client) -> None:
    for event in load_event_data():
        try:
            # One atomic roster transaction before any Discord await.
            expired = expire_payment_selections(event, datetime.now(UTC))
        except Exception:
            _log.exception("Payment expiry could not be saved for %r; retrying next tick", event.event_name)
            continue
        if not expired:
            continue
        if event.role_id:
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
                    w.user_id == entry.user_id and w.timestamp == entry.timestamp
                    for w in get_waitlist(event.event_name)
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
        try:
            await promote_waitlist_batch(
                event,
                client,
                freed_spots=sum(1 + entry.extra_people for entry in expired),
                excluded_user_ids={entry.user_id for entry in expired},
            )
        except Exception:
            _log.exception("Waitlist backfill failed after payment expiry for %r", event.event_name)
        try:
            await update_event_message(client, event)
        except Exception:
            _log.exception("Event message update failed after payment expiry for %r", event.event_name)
