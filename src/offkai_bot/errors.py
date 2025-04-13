# In a new file like errors.py or within util.py
from discord import app_commands, Thread, HTTPException, Forbidden

class BotCommandError(app_commands.AppCommandError):
    """Base class for custom command errors specific to this bot."""
    def __init__(self, message: str):
        super().__init__(message)

# --- Event Specific Errors ---

class EventNotFound(BotCommandError):
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
        self.action = action # e.g., "modify", "close", "reopen"
        # You can customize the message further in the handler if needed
        super().__init__(f"❌ Cannot {action} an archived event ('{event_name}').")

class EventAlreadyArchived(BotCommandError):
    """Raised when trying to archive an event that is already archived."""
    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' is already archived.")

class EventAlreadyClosed(BotCommandError):
    """Raised when trying to close an event that is already closed."""
    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' is already closed.")

class EventAlreadyOpen(BotCommandError):
    """Raised when trying to reopen an event that is already open."""
    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' is already open.")

class MissingChannelIDError(BotCommandError):
    """Raised when an event is missing its associated channel ID."""
    def __init__(self, event_name: str):
        self.event_name = event_name
        super().__init__(f"❌ Event '{event_name}' does not have a channel ID set.")

class ThreadNotFoundError(BotCommandError):
    """Raised when the thread channel associated with an event cannot be found."""
    def __init__(self, event_name: str, channel_id: int | None):
        self.event_name = event_name
        self.channel_id = channel_id
        super().__init__(f"❌ Could not find thread channel (ID: {channel_id}) for '{event_name}'.")

# --- Response Specific Errors ---

class ResponseNotFound(BotCommandError):
    """Raised when a specific user's response cannot be found for an event."""
    def __init__(self, event_name: str, user_mention: str):
        self.event_name = event_name
        self.user_mention = user_mention
        super().__init__(f"❌ Could not find a response from user {user_mention} for '{event_name}'.")

class NoResponsesFound(BotCommandError):
    """Raised by attendance command when no responses exist for an event."""
    def __init__(self, event_name: str):
        self.event_name = event_name
        # Note: No '❌' prefix to match original behaviour
        super().__init__(f"No responses found for '{event_name}'.")

# --- Input / Command Usage Errors ---

class InvalidDateTimeFormat(BotCommandError):
    """Raised when a provided date/time string is not in the expected format."""
    def __init__(self, expected_format: str = "YYYY-MM-DD HH:MM"):
        self.expected_format = expected_format
        super().__init__(f"❌ Invalid date format. Use {expected_format}.")

class InvalidChannelTypeError(BotCommandError):
    """Raised when a command is used in an unsupported channel type."""
    def __init__(self, expected_type: str = "server text channel"):
        self.expected_type = expected_type
        super().__init__(f"❌ This command can only be used in a {expected_type}.")

class NoChangesProvidedError(BotCommandError):
    """Raised when a modification command is called without any actual changes."""
    def __init__(self):
        super().__init__("❌ No changes provided to modify.")

# --- Discord API / Permissions Errors (Optional Wrappers) ---
# You might choose to handle discord.Forbidden/HTTPException directly in on_command_error,
# but wrappers can provide more context if needed.

class ThreadCreationError(BotCommandError):
    """Raised specifically when thread creation fails."""
    def __init__(self, event_name: str, original_exception: Exception):
        self.event_name = event_name
        self.original_exception = original_exception
        super().__init__(f"❌ Failed to create the event thread for '{event_name}'. Check bot permissions.")

class BroadcastPermissionError(BotCommandError):
    def __init__(self, channel: Thread, original_exception: Forbidden):
        self.channel = channel
        self.original_exception = original_exception
        super().__init__(f"❌ Bot lacks permission to send messages in {channel.mention}.")

class BroadcastSendError(BotCommandError):
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
