# src/offkai_bot/alerts/task.py
import logging
from abc import ABC, abstractmethod  # Import ABC and abstractmethod
from dataclasses import dataclass, field

import discord

from offkai_bot.errors import BotCommandError  # Import base error for catching known issues
from offkai_bot.event_actions import perform_close_event

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
