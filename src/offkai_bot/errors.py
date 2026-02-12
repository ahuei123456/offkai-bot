import logging
from datetime import datetime

from discord import Forbidden, HTTPException, Thread, app_commands


class BotCommandError(app_commands.AppCommandError):
    """Base class for custom command errors specific to this bot."""

    log_level: int = logging.INFO

    def __init__(self, message: str):
        super().__init__(message)


# --- Event Specific Errors ---


class EventNotFoundError(BotCommandError):
    """Raised when an event with the specified name cannot be found."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' not found.")


class DuplicateEventError(BotCommandError):
    """Raised when trying to create an event with a name that already exists."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ An event named '{event_name}' already exists.")


class EventArchivedError(BotCommandError):
    """Raised when trying to perform an action (modify, close, reopen) on an archived event."""

    def __init__(self, event_name: str, action: str = "perform action"):
        self.event_name = event_name
        self.action = action  # e.g., "modify", "close", "reopen"
        # You can customize the message further in the handler if needed
        super().__init__(f"❌ Cannot {action} an archived event ('{event_name}').")


class EventAlreadyArchivedError(BotCommandError):
    """Raised when trying to archive an event that is already archived."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' is already archived.")


class EventAlreadyClosedError(BotCommandError):
    """Raised when trying to close an event that is already closed."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' is already closed.")


class EventAlreadyOpenError(BotCommandError):
    """Raised when trying to reopen an event that is already open."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' is already open.")


class MissingChannelIDError(BotCommandError):
    """Raised when an event is missing its associated channel ID."""

    log_level = logging.WARNING

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' does not have a channel ID set.")


class ThreadNotFoundError(BotCommandError):
    """Raised when the thread channel associated with an event cannot be found."""

    log_level = logging.WARNING

    def __init__(self, event_name: str, thread_id: int | None):
        self.event_name = event_name
        self.thread_id = thread_id
        super().__init__(f"❌ Could not find thread channel (ID: {thread_id}) for '{event_name}'.")


class ThreadAccessError(BotCommandError):
    """Error raised when the bot lacks permissions to access/fetch a thread."""

    log_level = logging.ERROR  # Higher severity as it indicates a permission issue

    def __init__(self, event_name: str, thread_id: int | None, original_exception: Exception | None = None):
        self.event_name = event_name
        self.thread_id = thread_id
        self.original_exception = original_exception
        super().__init__(
            f"Bot lacks permissions to access thread for event '{event_name}' (ID: {thread_id}). "
            "Please check bot permissions."
        )


# --- Response Specific Errors ---


class DuplicateResponseError(BotCommandError):
    """Raised when a user tries to submit a response for an event they already responded to."""

    def __init__(self, event_name: str, user_id: int):
        self.event_name = event_name
        self.user_id = user_id
        # Consider using username if readily available, but user_id is guaranteed
        super().__init__(f"❌ You have already submitted a response for event '{event_name}'.")


class ResponseNotFoundError(BotCommandError):
    """Raised when a specific user's response cannot be found for an event."""

    # Changed user_mention: str to user_id: int
    def __init__(self, event_name: str, user_id: int):
        self.event_name = event_name
        self.user_id = user_id
        # Updated message to use user_id (mention can be constructed later if needed)
        super().__init__(f"❌ Could not find a response from user ID {user_id} for '{event_name}'.")


class NoResponsesFoundError(BotCommandError):
    """Raised by attendance command when no responses exist for an event."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        # Note: No '❌' prefix to match original behaviour
        super().__init__(f"No responses found for '{event_name}'.")


class NoWaitlistEntriesFoundError(BotCommandError):
    """Raised by waitlist command when no waitlist entries exist for an event."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"No waitlist entries found for '{event_name}'.")


# --- Input / Command Usage Errors ---


class InvalidDateTimeFormatError(BotCommandError):
    """Raised when a provided date/time string is not in the expected format."""

    def __init__(self, expected_format: str = "YYYY-MM-DD HH:MM"):
        self.expected_format = expected_format
        super().__init__(f"❌ Invalid date format. Use {expected_format}.")


class InvalidChannelTypeError(BotCommandError):
    """Raised when a command is used in an unsupported channel type."""

    log_level = logging.WARNING

    def __init__(self, expected_type: str = "server text channel"):
        self.expected_type = expected_type
        super().__init__(f"❌ This command can only be used in a {expected_type}.")


class NoChangesProvidedError(BotCommandError):
    """Raised when a modification command is called without any actual changes."""

    def __init__(self):
        super().__init__("❌ No changes provided to modify.")


# --- NEW DATETIME VALIDATION ERRORS ---


class EventDateTimeInPastError(BotCommandError):
    """Raised when the provided event date/time is in the past."""

    def __init__(self):
        super().__init__("❌ Event date/time must be set in the future.")


class EventDeadlineInPastError(BotCommandError):
    """Raised when the provided event deadline is in the past."""

    def __init__(self):
        super().__init__("❌ Event deadline must be set in the future.")


class EventDeadlineAfterEventError(BotCommandError):
    """Raised when the provided event deadline is not before the event date/time."""

    def __init__(self):
        super().__init__("❌ Event deadline must be set *before* the event date/time.")


class CapacityReductionError(BotCommandError):
    """Raised when trying to reduce capacity below current attendee count."""

    def __init__(self, event_name: str, new_capacity: int, current_count: int):
        self.event_name = event_name
        self.new_capacity = new_capacity
        self.current_count = current_count
        super().__init__(
            f"❌ Cannot reduce capacity of '{event_name}' to {new_capacity}. Current attendee count is {current_count}."
        )


class CapacityReductionWithWaitlistError(BotCommandError):
    """Raised when trying to reduce capacity while there are users on the waitlist."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(
            f"❌ Cannot reduce capacity of '{event_name}' while there are users on the waitlist. "
            "Please wait for the waitlist to be empty."
        )


class AlertTimeInPastError(BotCommandError):
    """Raised when attempting to register an alert for a time in the past."""

    log_level = logging.WARNING

    def __init__(self, alert_time: datetime):
        # Format the time nicely for the error message, including timezone
        time_str = alert_time.strftime("%Y-%m-%d %H:%M:%S %Z") if alert_time.tzinfo else str(alert_time)
        super().__init__(f"Cannot register alert for a time in the past: {time_str}")


# --- END NEW DATETIME VALIDATION ERRORS ---


# --- Discord API / Permissions Errors (Optional Wrappers) ---
# You might choose to handle discord.Forbidden/HTTPException directly in on_command_error,
# but wrappers can provide more context if needed.


class ThreadCreationError(BotCommandError):
    """Raised specifically when thread creation fails."""

    log_level = logging.WARNING

    def __init__(self, event_name: str, original_exception: Exception):
        self.event_name = event_name
        self.original_exception = original_exception
        super().__init__(f"❌ Failed to create the event thread for '{event_name}'. Check bot permissions.")


class PinPermissionError(BotCommandError):
    """Raised when the bot fails to pin a message, likely due to lack of permissions."""

    log_level = logging.WARNING

    def __init__(self, channel, original_exception: Forbidden):
        self.channel = channel
        self.original_exception = original_exception
        super().__init__(
            f"❌ Failed to pin the event message in {channel.mention}. "
            "Please ensure the bot has the 'Manage Messages' permission in this channel."
        )


class BroadcastPermissionError(BotCommandError):
    log_level = logging.WARNING

    def __init__(self, channel: Thread, original_exception: Forbidden):
        self.channel = channel
        self.original_exception = original_exception
        super().__init__(f"❌ Bot lacks permission to send messages in {channel.mention}.")


class BroadcastSendError(BotCommandError):
    log_level = logging.WARNING

    def __init__(self, channel: Thread, original_exception: HTTPException):
        self.channel = channel
        self.original_exception = original_exception
        super().__init__(f"❌ Failed to send message to {channel.mention}.")


# You would then catch these in your on_command_error handler:
# elif isinstance(original_error, EventNotFound):
#     await interaction.response.send_message(str(original_error), ephemeral=True)
# elif isinstance(original_error, InvalidDateTimeFormat):
#     await interaction.response.send_message(str(original_error), ephemeral=True)
# ... and so on
