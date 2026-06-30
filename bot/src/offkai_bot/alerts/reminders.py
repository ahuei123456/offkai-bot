import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import timedelta

import discord

from offkai_bot.alerts.alerts import register_alert, remove_alerts
from offkai_bot.alerts.task import CloseOffkaiTask, DeleteRoleTask, SendMessageTask, Task
from offkai_bot.data.event import Event, get_event
from offkai_bot.data.response import Response, get_responses
from offkai_bot.errors import AlertTimeInPastError, EventNotFoundError
from offkai_bot.util import JST, build_checkin_url

# How long before an event starts the check-in reminder DMs are sent.
CHECKIN_REMINDER_LEAD = timedelta(hours=24)

# Small delay between attendee DMs to stay clear of Discord DM rate limits.
_DM_THROTTLE_SECONDS = 0.5

_log = logging.getLogger(__name__)


def _format_attendee_numbers_en(response: Response) -> str | None:
    if response.attendee_number is None:
        return None

    parts = [f"{response.attendee_number} (you)"]
    for index, number in enumerate(response.extras_attendee_numbers):
        guest_name = response.extras_names[index] if index < len(response.extras_names) else f"guest {index + 1}"
        parts.append(f"{number} ({guest_name})")

    label = "Attendee Number" if len(parts) == 1 else "Attendee Numbers"
    return f"🔢 **{label}:** {', '.join(parts)}"


def _format_attendee_numbers_jp(response: Response) -> str | None:
    if response.attendee_number is None:
        return None

    parts = [f"{response.attendee_number}（本人）"]
    for index, number in enumerate(response.extras_attendee_numbers):
        guest_name = response.extras_names[index] if index < len(response.extras_names) else f"同伴者{index + 1}"
        parts.append(f"{number}（{guest_name}）")

    return f"🔢 **受付番号:** {', '.join(parts)}"


def register_deadline_reminders(client: discord.Client, event: Event, thread: discord.Thread):
    _log.info("Registering deadline reminders for event '%s'.", event.event_name)

    if event.event_deadline and not event.is_past_deadline:
        with contextlib.suppress(AlertTimeInPastError):
            register_alert(event.event_deadline, CloseOffkaiTask(client=client, event_name=event.event_name))
            _log.info("Registered auto-close task for '%s'.", event.event_name)

            if event.channel_id:
                role_ping = f"<@&{event.ping_role_id}> " if event.ping_role_id else ""

                register_alert(
                    event.event_deadline - timedelta(days=1),
                    SendMessageTask(
                        client=client,
                        channel_id=event.channel_id,
                        message=f"{role_ping}24 hours until registration deadline for {event.event_name}! "
                        f"See {thread.mention} for details.\n"
                        f"{event.event_name}の登録締切まであと24時間です！"
                        f"詳細は{thread.mention}をご覧ください。",
                    ),
                )
                _log.info("Registered 24 hour reminder for '%s'.", event.event_name)

                register_alert(
                    event.event_deadline - timedelta(days=3),
                    SendMessageTask(
                        client=client,
                        channel_id=event.channel_id,
                        message=f"{role_ping}3 days until registration deadline for {event.event_name}! "
                        f"See {thread.mention} for details.\n"
                        f"{event.event_name}の登録締切まであと3日です！"
                        f"詳細は{thread.mention}をご覧ください。",
                    ),
                )
                _log.info("Registered 3 day reminder for '%s'.", event.event_name)

                register_alert(
                    event.event_deadline - timedelta(days=7),
                    SendMessageTask(
                        client=client,
                        channel_id=event.channel_id,
                        message=f"{role_ping}1 week until registration deadline for {event.event_name}! "
                        f"See {thread.mention} for details.\n"
                        f"{event.event_name}の登録締切まであと1週間です！"
                        f"詳細は{thread.mention}をご覧ください。",
                    ),
                )

                _log.info("Registered 1 week reminder for '%s'.", event.event_name)

    # Role deletion: 1 day after event (independent of deadline)
    if event.role_id:
        with contextlib.suppress(AlertTimeInPastError):
            register_alert(
                event.event_datetime + timedelta(days=1),
                DeleteRoleTask(client=client, event_name=event.event_name, role_id=event.role_id),
            )
            _log.info("Registered role deletion task for '%s'.", event.event_name)


def build_checkin_reminder_message(event: Event, response: Response, rsvp_url: str) -> str:
    """Builds the bilingual 24-hour check-in reminder DM for one attendee.

    ``rsvp_url`` is the attendee's personal, tokenised URL (or "" when no
    frontend URL is configured). It is private and must only ever be delivered
    via a direct DM to that attendee.
    """
    if event.event_datetime:
        dt_str = event.event_datetime.astimezone(JST).strftime(r"%Y-%m-%d %H:%M") + " JST"
    else:
        dt_str = "TBA"

    extra_people = response.extra_people or 0
    extras_names = response.extras_names or []
    drinks = response.drinks or []
    attendee_numbers_en = _format_attendee_numbers_en(response)
    attendee_numbers_jp = _format_attendee_numbers_jp(response)

    # --- English ---
    en = [
        f"⏰ **Reminder: {event.event_name} is tomorrow!**",
        "",
        f"🍽️ **Venue:** {event.venue}",
        f"📍 **Address:** {event.address}",
        f"🕑 **Date and Time:** {dt_str}",
        f"👥 **Bringing:** {extra_people} extra guest{'s' if extra_people != 1 else ''}",
    ]
    if attendee_numbers_en:
        en.append(attendee_numbers_en)
    if extras_names:
        en.append(f"👥 Guest names: {', '.join(extras_names)}")
    if drinks:
        en.append(f"🍺 Drinks: {', '.join(drinks)}")
    if rsvp_url:
        en += [
            "",
            f"🔗 **RSVP Page / QR Code:** {rsvp_url}",
            "",
            "Please show the QR code at the door for check-in.",
        ]

    # --- Japanese ---
    jp = [
        f"⏰ **リマインダー: {event.event_name} は明日開催です！**",
        "",
        f"🍽️ **会場:** {event.venue}",
        f"📍 **住所:** {event.address}",
        f"🕑 **日時:** {dt_str}",
        f"👥 **同伴者:** {extra_people}名",
    ]
    if attendee_numbers_jp:
        jp.append(attendee_numbers_jp)
    if extras_names:
        jp.append(f"👥 同伴者名: {', '.join(extras_names)}")
    if drinks:
        jp.append(f"🍺 飲み物: {', '.join(drinks)}")
    if rsvp_url:
        jp += [
            "",
            f"🔗 **RSVPページ / QRコード:** {rsvp_url}",
            "",
            "受付でQRコードをご提示ください。",
        ]

    return "\n".join(en) + "\n\n" + "\n".join(jp)


@dataclass
class SendCheckinReminderTask(Task):
    """Sends a personal 24-hour check-in reminder DM (with the attendee's private
    QR link) to every confirmed attendee. DMs users only — the tokenised URL is
    never posted to a channel/thread."""

    event_name: str
    # Holds a reference to the background DM fan-out task created in action().
    # Kept alive here so the GC cannot collect it before it finishes; also lets
    # tests await it directly without sleeping.
    _fan_out_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def action(self) -> None:
        _log.info("Executing SendCheckinReminderTask for event: '%s'", self.event_name)

        # Reload the event at fire time; skip if gone or archived.
        try:
            event = get_event(self.event_name)
        except EventNotFoundError:
            _log.warning("SendCheckinReminderTask: event '%s' no longer exists. Skipping.", self.event_name)
            return
        if event.archived:
            _log.info("SendCheckinReminderTask: event '%s' is archived. Skipping.", self.event_name)
            return

        # Confirmed attendees only — never waitlisted users.
        attendees = get_responses(self.event_name)
        if not attendees:
            _log.info("SendCheckinReminderTask: no attendees for '%s'. Nothing to send.", self.event_name)
            return

        # Hand the slow DM fan-out off to a background task so action() returns
        # promptly.  alert_loop is @tasks.loop(minutes=1.0) with no overlap — if
        # action() blocks for longer than a minute (fetch_user + 0.5 s sleep per
        # attendee adds up fast) the next tick fires late and any alert scheduled
        # in the skipped minute is silently dropped.  create_task() schedules the
        # coroutine on the running event loop and returns immediately.
        self._fan_out_task = asyncio.create_task(self._send_dms(event, attendees))

    async def _send_dms(self, event: Event, attendees: list[Response]) -> None:
        """Fan-out: DM each confirmed attendee their private check-in link."""
        last_index = len(attendees) - 1
        sent = 0
        for index, response in enumerate(attendees):
            # Per-attendee private URL using the shared token helper.
            rsvp_url = build_checkin_url(response.user_id, self.event_name)
            message = build_checkin_reminder_message(event, response, rsvp_url)
            try:
                # DM the individual user. fetch_user + user.send opens a private
                # DM — this never targets a guild/text channel.
                user = await self.client.fetch_user(response.user_id)
                await user.send(message)
                sent += 1
            except (discord.Forbidden, discord.HTTPException) as e:
                # Log identity + error type only — never the URL, token, or body.
                _log.warning(
                    "SendCheckinReminderTask: failed to DM user %s for event '%s' (%s).",
                    response.user_id,
                    self.event_name,
                    type(e).__name__,
                )
            except Exception as e:
                _log.warning(
                    "SendCheckinReminderTask: unexpected error DMing user %s for event '%s' (%s).",
                    response.user_id,
                    self.event_name,
                    type(e).__name__,
                )

            # Throttle only between sends, not after the last attendee.
            if index != last_index:
                await asyncio.sleep(_DM_THROTTLE_SECONDS)

        _log.info("SendCheckinReminderTask: sent %s/%s reminder DMs for '%s'.", sent, len(attendees), self.event_name)


def unregister_checkin_reminder(event_name: str) -> None:
    """Removes any pending check-in reminder for the given event."""
    remove_alerts(lambda task: isinstance(task, SendCheckinReminderTask) and task.event_name == event_name)


def register_checkin_reminder(client: discord.Client, event: Event) -> None:
    """Schedules a 24-hour-before-event check-in reminder DM to every confirmed
    attendee. Replaces any existing reminder for this event so editing the event
    time never leaves a stale reminder. No-op for archived events."""
    # Drop any previous reminder for this event first.
    unregister_checkin_reminder(event.event_name)

    if event.archived:
        return

    with contextlib.suppress(AlertTimeInPastError):
        register_alert(
            event.event_datetime - CHECKIN_REMINDER_LEAD,
            SendCheckinReminderTask(client=client, event_name=event.event_name),
        )
        _log.info("Registered 24-hour check-in reminder for '%s'.", event.event_name)
