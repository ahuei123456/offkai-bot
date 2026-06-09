# src/offkai_bot/alerts/task.py
import logging
from abc import ABC, abstractmethod  # Import ABC and abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import discord
import jwt as pyjwt

from offkai_bot.errors import BotCommandError  # Import base error for catching known issues
from offkai_bot.event_actions import perform_close_event
from offkai_bot.util import JST

_log = logging.getLogger(__name__)


# --- Abstract Base Task as Dataclass ---
@dataclass
class Task(ABC):
    """Abstract base dataclass for a scheduled task."""

    client: discord.Client  # All tasks need the client instance

    @abstractmethod
    async def action(self):
        """The core action to be performed by the task. Must be implemented by subclasses."""
        pass  # Or use '...'


# --- Concrete Task: Send Message ---
@dataclass
class SendMessageTask(Task):
    """A concrete task to send a specific message to a channel."""

    channel_id: int
    message: str

    async def action(self):
        """Sends the defined message to the specified channel."""
        _log.debug("Executing SendMessageTask for channel %s", self.channel_id)
        try:
            channel = self.client.get_channel(self.channel_id)
            # Use isinstance with a tuple for multiple types
            if isinstance(channel, discord.TextChannel | discord.Thread):
                await channel.send(self.message)
            elif channel is None:
                _log.warning("SendMessageTask: Channel %s not found.", self.channel_id)
            else:
                _log.warning(
                    "SendMessageTask: Channel %s is not a text channel or thread (Type: %s).",
                    self.channel_id,
                    type(channel),
                )
        except discord.HTTPException as e:
            _log.error("SendMessageTask failed to send message to channel %s: %s", self.channel_id, e)
        except Exception as e:
            _log.exception("Unexpected error in SendMessageTask for channel %s: %s", self.channel_id, e)


# --- Concrete Task: Close Offkai ---
@dataclass
class CloseOffkaiTask(Task):
    """
    A concrete task specifically designed to close an Offkai event automatically.
    Inherits 'client' from Task.
    """

    # Attributes specific to this task type
    event_name: str
    close_msg: str = field(default="Deadline reached. Responses automatically closed.")

    # No __init__ needed. The dataclass automatically generates one that accepts
    # 'client' (from Task) and 'event_name' (from this class).

    async def action(self):
        """
        Executes the logic to automatically close the specified event.
        Handles errors specific to the closing process. Overrides base action.
        """
        _log.info("Executing CloseOffkaiTask for event: '%s'", self.event_name)
        try:
            # Call the core closing logic function
            # self.client is inherited from the Task dataclass

            await perform_close_event(self.client, self.event_name, self.close_msg)
            _log.info("Successfully executed automatic closure for event: '%s'", self.event_name)

        # --- Error Handling within the Task Action ---
        except BotCommandError as e:
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, "Error during automatic closure of '%s': %s", self.event_name, e)
        except discord.HTTPException as e:
            _log.error("Discord API error during automatic closure of '%s': %s", self.event_name, e)
        except Exception as e:
            _log.exception("Unexpected error during automatic closure of '%s': %s", self.event_name, e)
        # --- End Error Handling ---


# --- Concrete Task: Delete Role ---
@dataclass
class DeleteRoleTask(Task):
    """A concrete task to delete an event participant role after the event ends."""

    event_name: str
    role_id: int

    async def action(self):
        """Deletes the event participant role from the guild."""
        _log.info("Executing DeleteRoleTask for event '%s' (role %s)", self.event_name, self.role_id)
        for guild in self.client.guilds:
            role = guild.get_role(self.role_id)
            if role:
                try:
                    await role.delete(reason=f"Offkai '{self.event_name}' ended")
                    _log.info("Deleted role %s for event '%s'.", self.role_id, self.event_name)
                except (discord.Forbidden, discord.HTTPException) as e:
                    _log.error("Failed to delete role %s: %s", self.role_id, e)
                return
        _log.warning("Role %s not found for deletion (event '%s').", self.role_id, self.event_name)


# --- Concrete Task: Send Pre-Event DMs ---
@dataclass
class SendPreEventDMsTask(Task):
    """Sends a reminder DM to every confirmed attendee 1 day before the event.

    Each DM includes the attendee's registration details and a JWT-signed
    check-in page URL they can show at the door.  Requires JWT_SECRET and
    CHECKIN_FRONTEND_URL to be set in config.json.
    """

    event_name: str
    event_datetime: datetime
    venue: str
    address: str
    google_maps_link: str
    jwt_secret: str
    frontend_url: str

    async def action(self):
        from offkai_bot.data.response import get_responses

        _log.info("Executing SendPreEventDMsTask for event: '%s'", self.event_name)

        responses = get_responses(self.event_name)
        if not responses:
            _log.info("No attendees found for '%s'. Skipping pre-event DMs.", self.event_name)
            return

        # Token valid until 7 days after the event
        exp = self.event_datetime + timedelta(days=7)
        dt_str = self.event_datetime.astimezone(JST).strftime(r"%Y-%m-%d %H:%M") + " JST"

        sent = 0
        failed = 0
        for response in responses:
            try:
                token = pyjwt.encode(
                    {
                        "user_id": response.user_id,
                        "event_name": self.event_name,
                        "exp": int(exp.timestamp()),
                    },
                    self.jwt_secret,
                    algorithm="HS256",
                )
                checkin_url = f"{self.frontend_url.rstrip('/')}/?token={token}"

                drinks_msg = f"\n🍺 **Drinks**: {', '.join(response.drinks)}" if response.drinks else ""
                drinks_msg_jp = f"\n🍺 **飲み物**: {', '.join(response.drinks)}" if response.drinks else ""

                guests_msg = ""
                guests_msg_jp = ""
                if response.extra_people > 0:
                    names = ", ".join(n for n in response.extras_names if n.strip()) or "—"
                    guests_msg = f"\n👥 **Guests**: {response.extra_people} ({names})"
                    guests_msg_jp = f"\n👥 **同伴者**: {response.extra_people}名（{names}）"

                dm = (
                    f"🎉 See you tomorrow at **{self.event_name}**!\n\n"
                    f"📅 **Date & Time**: {dt_str}\n"
                    f"🍽️ **Venue**: {self.venue}\n"
                    f"📍 **Address**: {self.address}\n"
                    f"🌎 **Map**: {self.google_maps_link}\n\n"
                    f"Your confirmed registration:\n"
                    f"✔ Attendance Confirmed"
                    f"{drinks_msg}"
                    f"{guests_msg}\n\n"
                    f"🎫 **Check-In Page**\n"
                    f"{checkin_url}\n"
                    f"Show this at the door to check in quickly!\n\n"
                    f"---\n\n"
                    f"🎉 明日は**{self.event_name}**でお会いしましょう！\n\n"
                    f"📅 **日時**: {dt_str}\n"
                    f"🍽️ **会場**: {self.venue}\n"
                    f"📍 **住所**: {self.address}\n"
                    f"🌎 **地図**: {self.google_maps_link}\n\n"
                    f"参加確定内容：\n"
                    f"✔ 参加確定"
                    f"{drinks_msg_jp}"
                    f"{guests_msg_jp}\n\n"
                    f"🎫 **チェックインページ**\n"
                    f"{checkin_url}\n"
                    f"入口でこのページを見せてチェックインしてください！"
                )

                user = await self.client.fetch_user(response.user_id)
                await user.send(dm)
                sent += 1
                _log.info("Sent pre-event DM to user %s for event '%s'.", response.user_id, self.event_name)
            except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                failed += 1
                _log.warning(
                    "Could not send pre-event DM to user %s for event '%s': %s",
                    response.user_id,
                    self.event_name,
                    e,
                )
            except Exception as e:
                failed += 1
                _log.exception(
                    "Unexpected error sending pre-event DM to user %s for event '%s': %s",
                    response.user_id,
                    self.event_name,
                    e,
                )

        _log.info(
            "Pre-event DM task for '%s' complete. Sent: %s, Failed: %s.",
            self.event_name,
            sent,
            failed,
        )
