# src/offkai_bot/alerts/task.py
import logging
from abc import ABC, abstractmethod  # Import ABC and abstractmethod
from dataclasses import dataclass, field

import discord

from ..errors import BotCommandError  # Import base error for catching known issues

# Assuming perform_close_event is correctly placed and importable
# Adjust the import path if necessary based on your project structure

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
        _log.debug(f"Executing SendMessageTask for channel {self.channel_id}")
        try:
            channel = self.client.get_channel(self.channel_id)
            # Use isinstance with a tuple for multiple types
            if isinstance(channel, discord.TextChannel | discord.Thread):
                await channel.send(self.message)
            elif channel is None:
                _log.warning(f"SendMessageTask: Channel {self.channel_id} not found.")
            else:
                _log.warning(
                    f"SendMessageTask: Channel {self.channel_id} "
                    f"is not a text channel or thread (Type: {type(channel)})."
                )
        except discord.HTTPException as e:
            _log.error(f"SendMessageTask failed to send message to channel {self.channel_id}: {e}")
        except Exception as e:
            _log.exception(f"Unexpected error in SendMessageTask for channel {self.channel_id}: {e}")


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
        _log.info(f"Executing CloseOffkaiTask for event: '{self.event_name}'")
        try:
            # Call the core closing logic function
            # self.client is inherited from the Task dataclass

            from ..event_actions import perform_close_event

            await perform_close_event(self.client, self.event_name, self.close_msg)
            _log.info(f"Successfully executed automatic closure for event: '{self.event_name}'")

        # --- Error Handling within the Task Action ---
        except BotCommandError as e:
            log_level = getattr(e, "log_level", logging.WARNING)
            _log.log(log_level, f"Error during automatic closure of '{self.event_name}': {e}")
        except discord.HTTPException as e:
            _log.error(f"Discord API error during automatic closure of '{self.event_name}': {e}")
        except Exception as e:
            _log.exception(f"Unexpected error during automatic closure of '{self.event_name}': {e}")
        # --- End Error Handling ---
