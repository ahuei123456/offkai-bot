import contextlib
import logging
from datetime import timedelta

import discord

from offkai_bot.alerts.alerts import register_alert
from offkai_bot.alerts.task import CloseOffkaiTask, SendMessageTask
from offkai_bot.data.event import Event
from offkai_bot.errors import AlertTimeInPastError

_log = logging.getLogger(__name__)


def register_deadline_reminders(client: discord.Client, event: Event, thread: discord.Thread):
    _log.info(f"Registering deadline reminders for event '{event.event_name}'.")

    if event.event_deadline and not event.is_past_deadline:
        with contextlib.suppress(AlertTimeInPastError):
            register_alert(event.event_deadline, CloseOffkaiTask(client=client, event_name=event.event_name))
            _log.info(f"Registered auto-close task for '{event.event_name}'.")

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
                _log.info(f"Registered 24 hour reminder for '{event.event_name}'.")

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
                _log.info(f"Registered 3 day reminder for '{event.event_name}'.")

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

                _log.info(f"Registered 1 week reminder for '{event.event_name}'.")
