import contextlib
import logging
from datetime import timedelta

import discord

from offkai_bot.alerts.alerts import register_alert
from offkai_bot.alerts.task import CloseOffkaiTask, DeleteRoleTask, SendMessageTask, SendPreEventDMsTask
from offkai_bot.config import get_config
from offkai_bot.data.event import Event
from offkai_bot.errors import AlertTimeInPastError

_log = logging.getLogger(__name__)


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

    # Pre-event DM: 1 day before the event itself, with JWT check-in link
    settings = get_config()
    jwt_secret: str | None = settings.get("JWT_SECRET")
    frontend_url: str | None = settings.get("CHECKIN_FRONTEND_URL")
    if jwt_secret and frontend_url:
        with contextlib.suppress(AlertTimeInPastError):
            register_alert(
                event.event_datetime - timedelta(days=1),
                SendPreEventDMsTask(
                    client=client,
                    event_name=event.event_name,
                    event_datetime=event.event_datetime,
                    venue=event.venue,
                    address=event.address,
                    google_maps_link=event.google_maps_link,
                    jwt_secret=jwt_secret,
                    frontend_url=frontend_url,
                ),
            )
            _log.info("Registered pre-event DM task for '%s'.", event.event_name)
    else:
        _log.info(
            "Skipping pre-event DM registration for '%s': JWT_SECRET or CHECKIN_FRONTEND_URL not set in config.",
            event.event_name,
        )

    # Role deletion: 1 day after event (independent of deadline)
    if event.role_id:
        with contextlib.suppress(AlertTimeInPastError):
            register_alert(
                event.event_datetime + timedelta(days=1),
                DeleteRoleTask(client=client, event_name=event.event_name, role_id=event.role_id),
            )
            _log.info("Registered role deletion task for '%s'.", event.event_name)
