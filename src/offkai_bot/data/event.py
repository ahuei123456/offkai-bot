# src/offkai_bot/data/event.py
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Use relative imports for sibling modules within the package
from offkai_bot.config import get_config
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.data.response import get_responses, get_waitlist
from offkai_bot.errors import (
    CapacityReductionError,
    CapacityReductionWithWaitlistError,
    EventAlreadyArchivedError,
    EventAlreadyClosedError,
    EventAlreadyOpenError,
    EventArchivedError,
    EventNotFoundError,
    NoChangesProvidedError,
)
from offkai_bot.util import JST, parse_drinks, parse_event_datetime, validate_event_datetime, validate_event_deadline

_log = logging.getLogger(__name__)


# Constants can stay here if general, or move if specific
OFFKAI_MESSAGE = (
    "Please take note of the following:\n"
    "以下の注意事項をご確認ください：\n\n"
    "1. We will not accomodate any allergies or dietary restrictions.\n"
    "アレルギーや食事制限には対応しません。\n"
    "2. Please register yourself and all your +1s by the deadline if you are planning on attending. "
    "Anyone who shows up uninvited or with uninvited guests can and will be turned away.\n"
    "参加予定の方は、締め切りまでにご自身と同伴者全員の登録をお願いします。"
    "招待されていない方や、招待されていない同伴者を連れてきた場合、入場をお断りすることがあります。\n"
    "3. Please show up on time. Restaurants tend to be packed after live events "
    "and we have been asked to give up table space in the past.\n"
    "時間通りにお越しください。ライブイベント後はレストランが混み合うことが多く、"
    "過去に席を譲るよう求められたことがあります。\n"
    "4. To simplify accounting, we will split the bill evenly among all participants, "
    "regardless of how much you eat or drink. Expect to pay around 4000 yen, "
    "maybe more if some people decide to drink a lot.\n"
    "会計を簡単にするため、飲食量に関係なく均等に割り勘します。"
    "約4000円程度を見込んでください。たくさん飲む方がいる場合はもう少し高くなることがあります。\n"
    "5. Depending on turnout or venue restrictions, we might need to change the location of the offkai.\n"
    "参加者数や会場の制約により、オフ会の場所を変更する場合があります。\n"
    "6. Please pay attention to this thread for day-of announcements before the offkai starts.\n"
    "オフ会開始前の当日のお知らせについては、このスレッドに注意してください。\n"
)


# --- Event Dataclass ---
@dataclass
class Event:
    event_name: str
    venue: str
    address: str
    google_maps_link: str
    event_datetime: datetime
    event_deadline: datetime | None = None
    message: str | None = None  # Optional message for the event itself

    channel_id: int | None = None
    thread_id: int | None = None
    message_id: int | None = None
    open: bool = False
    archived: bool = False
    drinks: list[str] = field(default_factory=list)
    max_capacity: int | None = None  # None means unlimited capacity
    creator_id: int | None = None  # Discord user ID of the event creator
    closed_attendance_count: int | None = None  # Attendance count when event was closed
    ping_role_id: int | None = None  # Discord role ID to ping in deadline reminders
    role_id: int | None = None  # Discord role ID for event participants

    @property
    def has_drinks(self):
        return len(self.drinks) > 0

    @property
    def is_over(self) -> bool:
        """Checks if the event's start time (event_datetime) is in the past."""
        # Ensure comparison is between timezone-aware datetimes (UTC)
        now_utc = datetime.now(UTC)
        return now_utc > self.event_datetime

    @property
    def is_past_deadline(self) -> bool:
        """
        Checks if the event's deadline (event_deadline) has passed.
        Returns False if no deadline is set.
        """
        if self.event_deadline is None:
            return False  # No deadline set, so it can't be past

        # Ensure comparison is between timezone-aware datetimes (UTC)
        now_utc = datetime.now(UTC)
        return now_utc > self.event_deadline

    def format_details(self):
        drinks_str = ", ".join(self.drinks) if self.drinks else "No selection needed!"

        if self.event_datetime:
            event_dt_jst = self.event_datetime.astimezone(JST)
            dt_str = event_dt_jst.strftime(r"%Y-%m-%d %H:%M") + " JST"
        else:
            dt_str = "Not Set"

        if self.event_deadline:
            unix_ts = int(self.event_deadline.timestamp())
            deadline_str = f"<t:{unix_ts}:F> (<t:{unix_ts}:R>)"
        else:
            deadline_str = "Not Set"

        role_line = f"\n🏷️ **Role (ロール)**: <@&{self.role_id}>" if self.role_id else ""

        return (
            f"📅 **Event Name (イベント名)**: {self.event_name}\n"
            f"🍽️ **Venue (会場)**: {self.venue}\n"
            f"📍 **Address (住所)**: {self.address}\n"
            f"🌎 **Google Maps Link (地図)**: {self.google_maps_link}\n"
            f"🕑 **Date and Time (日時)**: {dt_str}\n"
            f"📅 **Deadline (締切)**: {deadline_str}\n"
            f"🍺 **Drinks (飲み物)**: {drinks_str}"
            f"{role_line}"
        )

    def __str__(self):
        return self.format_details()


def create_event_message(event: Event) -> str:
    """Creates the full Discord message content for an event announcement."""
    # Use the format_details method from the Event dataclass
    event_details = event.format_details()

    return (
        f"{event_details}\n\n"  # Event details first
        f"{OFFKAI_MESSAGE}\n"  # Standard rules
        "Click the button below to confirm your attendance!\n"  # Call to action
        "下のボタンをクリックして参加を確認してください！"
    )


# --- Event Data Handling ---

EVENT_DATA_CACHE: list[Event] | None = None


def _load_event_data() -> list[Event]:
    """
    Loads event data from JSON, converts to Event dataclasses,
    and handles missing or empty files. (Internal use)
    """
    settings = get_config()
    global EVENT_DATA_CACHE
    events_list = []
    file_path = settings["EVENTS_FILE"]

    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise FileNotFoundError

        with open(file_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)

        if not isinstance(raw_data, list):
            _log.error(
                f"Invalid format in {file_path}: Expected a JSON list, got {type(raw_data)}. Loading empty list."
            )
            raw_data = []

        for event_dict in raw_data:
            # --- Check for required 'event_name' BEFORE trying to create Event ---
            if "event_name" not in event_dict or not event_dict["event_name"]:
                _log.error(f"Skipping event entry due to missing or empty 'event_name'. Data: {event_dict}")
                continue  # Skip this dictionary and move to the next one

            # --- Parse and Convert event_datetime ---
            raw_dt_str = event_dict.get("event_datetime")
            if raw_dt_str:
                try:
                    dt_obj = datetime.fromisoformat(raw_dt_str)
                    if dt_obj.tzinfo is None:
                        # Assume naive datetime is JST, make aware, convert to UTC
                        aware_jst = dt_obj.replace(tzinfo=JST)
                        event_datetime_utc = aware_jst.astimezone(UTC)
                        _log.debug(
                            f"Converted naive datetime '{raw_dt_str}' (assumed JST) to UTC: {event_datetime_utc}"
                        )
                    else:
                        # Already aware, just convert to UTC
                        event_datetime_utc = dt_obj.astimezone(UTC)
                        _log.debug(f"Converted aware datetime '{raw_dt_str}' to UTC: {event_datetime_utc}")
                except (ValueError, TypeError) as e:
                    _log.warning(
                        f"Could not parse/convert ISO datetime '{raw_dt_str}' for {event_dict.get('event_name')}: {e}"
                    )
                    _log.error(f"Skipping event entry due to missing or empty 'event_datetime'. Data: {event_dict}")
                    continue
            # --- End event_datetime Parsing ---

            # --- Parse and Convert event_deadline ---
            event_deadline_utc = None
            raw_deadline_str = event_dict.get("event_deadline")
            if raw_deadline_str:
                try:
                    dt_obj = datetime.fromisoformat(raw_deadline_str)
                    if dt_obj.tzinfo is None:
                        # Assume naive datetime is JST, make aware, convert to UTC
                        aware_jst = dt_obj.replace(tzinfo=JST)
                        event_deadline_utc = aware_jst.astimezone(UTC)
                        _log.debug(
                            f"Converted naive deadline '{raw_deadline_str}' (assumed JST) to UTC: {event_deadline_utc}"
                        )
                    else:
                        # Already aware, just convert to UTC
                        event_deadline_utc = dt_obj.astimezone(UTC)
                        _log.debug(f"Converted aware deadline '{raw_deadline_str}' to UTC: {event_deadline_utc}")
                except (ValueError, TypeError) as e:
                    _log.warning(
                        f"Could not parse/convert ISO deadline '{raw_deadline_str}' "
                        f"for {event_dict.get('event_name')}: {e}"
                    )
                    event_deadline_utc = None  # Keep as None on error
            # --- End event_deadline Parsing ---

            drinks = event_dict.get("drinks", [])

            try:
                if "event_deadline" in event_dict:
                    event = Event(
                        event_name=event_dict["event_name"],
                        venue=event_dict.get("venue", "Unknown Venue"),
                        address=event_dict.get("address", "Unknown Address"),
                        google_maps_link=event_dict.get("google_maps_link", ""),
                        event_datetime=event_datetime_utc,
                        event_deadline=event_deadline_utc,
                        message=event_dict.get("message"),
                        channel_id=event_dict.get("channel_id"),
                        thread_id=event_dict.get("thread_id"),
                        message_id=event_dict.get("message_id"),
                        open=event_dict.get("open", False),
                        archived=event_dict.get("archived", False),
                        drinks=drinks,
                        max_capacity=event_dict.get("max_capacity"),
                        creator_id=event_dict.get("creator_id"),
                        closed_attendance_count=event_dict.get("closed_attendance_count"),
                        ping_role_id=event_dict.get("ping_role_id"),
                        role_id=event_dict.get("role_id"),
                    )
                else:
                    # Old format, so we ignore channel_id and event_deadline
                    event = Event(
                        event_name=event_dict["event_name"],
                        venue=event_dict.get("venue", "Unknown Venue"),
                        address=event_dict.get("address", "Unknown Address"),
                        google_maps_link=event_dict.get("google_maps_link", ""),
                        event_datetime=event_datetime_utc,
                        event_deadline=None,
                        message=event_dict.get("message"),
                        channel_id=None,  # No deadline, so no channel
                        thread_id=event_dict.get("channel_id"),
                        message_id=event_dict.get("message_id"),
                        open=event_dict.get("open", False),
                        archived=event_dict.get("archived", False),
                        drinks=drinks,
                        max_capacity=event_dict.get("max_capacity"),
                        creator_id=event_dict.get("creator_id"),
                        closed_attendance_count=event_dict.get("closed_attendance_count"),
                        ping_role_id=event_dict.get("ping_role_id"),
                        role_id=event_dict.get("role_id"),
                    )
                    _log.info(
                        f"Found old events.json format for {event.event_name}. Successfully converted to new format."
                    )
                events_list.append(event)
            except TypeError as e:
                _log.error(f"Error creating Event object from dict {event_dict}: {e}")

    except FileNotFoundError:
        _log.warning(f"{file_path} not found or empty. Creating default empty file.")
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump([], file, indent=4)
            _log.info(f"Created empty events file at {file_path}")
        except OSError as e:
            _log.error(f"Could not create default events file at {file_path}: {e}")
        EVENT_DATA_CACHE = []
        return []
    except json.JSONDecodeError:
        _log.error(f"Error decoding JSON from {file_path}. File might be corrupted or invalid. Loading empty list.")
        EVENT_DATA_CACHE = []
        return []
    except Exception as e:
        _log.exception(f"An unexpected error occurred loading event data from {file_path}: {e}")
        EVENT_DATA_CACHE = []
        return []

    EVENT_DATA_CACHE = events_list
    return events_list


def load_event_data() -> list[Event]:
    """Returns cached event data or loads it if cache is empty."""
    if EVENT_DATA_CACHE is not None:
        return EVENT_DATA_CACHE
    else:
        return _load_event_data()


def save_event_data():
    """Saves the current state of EVENT_DATA_CACHE to the JSON file."""
    global EVENT_DATA_CACHE
    settings = get_config()
    if EVENT_DATA_CACHE is None:
        _log.error("Attempted to save event data before loading.")
        return

    try:
        with open(settings["EVENTS_FILE"], "w", encoding="utf-8") as file:
            json.dump(
                EVENT_DATA_CACHE,
                file,
                indent=4,
                cls=DataclassJSONEncoder,
                ensure_ascii=False,
            )
    except OSError as e:
        _log.error(f"Error writing event data to {settings['EVENTS_FILE']}: {e}")
    except Exception as e:
        _log.exception(f"An unexpected error occurred saving event data: {e}")


def get_event(event_name: str) -> Event:
    """Gets a specific event by name from the cached data."""
    events = load_event_data()
    for event in events:
        # Case-insensitive comparison for robustness
        if event_name.lower() == event.event_name.lower():
            return event
    raise EventNotFoundError(event_name)


def add_event(
    event_name: str,
    venue: str,
    address: str,
    google_maps_link: str,
    event_datetime: datetime,
    channel_id: int,
    thread_id: int,
    drinks_list: list[str],
    event_deadline: datetime | None = None,  # Signup deadline is optional
    announce_msg: str | None = None,  # Pass announce_msg if you want to store it on Event
    max_capacity: int | None = None,  # Max capacity is optional (None = unlimited)
    creator_id: int | None = None,  # Discord user ID of the event creator
    ping_role_id: int | None = None,  # Discord role ID to ping in deadline reminders
    role_id: int | None = None,  # Discord role ID for event participants
) -> Event:
    """Creates an Event object and adds it to the in-memory cache."""

    # Step 1: Validation
    # validate_event_datetime(event_datetime)
    # validate_event_deadline(event_datetime, event_deadline)

    # Step 2: Data Object Creation
    new_event = Event(
        event_name=event_name,
        venue=venue,
        address=address,
        google_maps_link=google_maps_link,
        event_datetime=event_datetime,
        event_deadline=event_deadline,
        channel_id=channel_id,
        thread_id=thread_id,
        message_id=None,  # Will be set later by send_event_message
        open=True,
        archived=False,
        drinks=drinks_list,
        message=announce_msg,  # Store announce_msg if desired
        max_capacity=max_capacity,
        creator_id=creator_id,
        ping_role_id=ping_role_id,
        role_id=role_id,
    )

    # Step 3: State Modification
    events_cache = load_event_data()  # Get or load the cache
    events_cache.append(new_event)
    _log.info(f"Event '{event_name}' added to cache.")

    # DO NOT SAVE HERE - Saving is handled later

    return new_event  # Return the created event object


def update_event_details(
    event_name: str,
    venue: str | None = None,
    address: str | None = None,
    google_maps_link: str | None = None,
    date_time_str: str | None = None,
    deadline_str: str | None = None,
    drinks_str: str | None = None,
    max_capacity: int | None = None,
) -> Event:
    """
    Finds an event by name, validates inputs, applies modifications if changes exist,
    and returns the updated event object.

    Modifies the event object directly within the EVENT_DATA_CACHE only after all
    validations pass and changes are detected. Does NOT save the data to disk.

    Raises:
        EventNotFoundError: If the event cannot be found.
        EventArchivedError: If the event is already archived.
        InvalidDateTimeFormatError: If the provided date_time_str is invalid.
        NoChangesProvidedError: If no actual changes were made to the event.
    """
    # 1. Find Event and Check Archive Status
    event = get_event(event_name)

    if event.archived:
        raise EventArchivedError(event_name, "modify")

    # 2. Parse Inputs and Validate Formats (before checking for changes)
    parsed_deadline: datetime | None = None
    if deadline_str is not None:
        parsed_deadline = parse_event_datetime(deadline_str)

    if date_time_str is not None:
        # This will raise InvalidDateTimeFormatError immediately if parsing fails
        parsed_datetime = parse_event_datetime(date_time_str)
        validate_event_datetime(parsed_datetime)
        validate_event_deadline(parsed_datetime, parsed_deadline)
    else:
        validate_event_deadline(event.event_datetime, parsed_deadline)

    parsed_drinks: list[str] = []
    if drinks_str is not None:
        # Assuming parse_drinks doesn't raise errors, just returns a list
        parsed_drinks = parse_drinks(drinks_str)

    # Validate max_capacity changes
    if max_capacity is not None and event.max_capacity != max_capacity:
        # Get current attendee count and waitlist
        responses = get_responses(event_name)
        current_count = sum(1 + r.extra_people for r in responses)
        waitlist = get_waitlist(event_name)

        # If reducing capacity, validate constraints
        if max_capacity < (event.max_capacity or 0):
            if max_capacity < current_count:
                raise CapacityReductionError(event_name, max_capacity, current_count)
            if len(waitlist) > 0:
                raise CapacityReductionWithWaitlistError(event_name)

    # 3. Determine if Any Changes Would Occur
    modified = False
    if venue is not None and event.venue != venue:
        modified = True
    if address is not None and event.address != address:
        modified = True
    if google_maps_link is not None and event.google_maps_link != google_maps_link:
        modified = True
    # Check parsed datetime only if input string was provided
    if date_time_str is not None and event.event_datetime != parsed_datetime:
        modified = True
    if deadline_str is not None and event.event_deadline != parsed_deadline:
        modified = True
    # Check parsed drinks only if input string was provided
    if drinks_str is not None and set(event.drinks) != set(parsed_drinks):  # Use set comparison
        modified = True
    # Check max_capacity
    if max_capacity is not None and event.max_capacity != max_capacity:
        modified = True

    # 4. Raise Error if No Changes Detected
    if not modified:
        raise NoChangesProvidedError()

    # 5. Apply Changes (only if validation passed and changes exist)
    if venue is not None:
        event.venue = venue
    if address is not None:
        event.address = address
    if google_maps_link is not None:
        event.google_maps_link = google_maps_link
    if date_time_str is not None:  # Apply the parsed datetime
        event.event_datetime = parsed_datetime
    if deadline_str is not None:  # Apply the parsed deadline
        event.event_deadline = parsed_deadline
    if drinks_str is not None:  # Apply the parsed drinks
        event.drinks = parsed_drinks
    if max_capacity is not None:  # Apply the max_capacity
        event.max_capacity = max_capacity

    # 6. Log and Return
    _log.info(f"Event '{event_name}' details updated in cache.")
    return event


def set_event_open_status(event_name: str, target_open_status: bool) -> Event:
    """
    Finds an event by name, validates its status, and sets its 'open' status.

    Modifies the event object directly within the EVENT_DATA_CACHE.
    Does NOT save the data to disk.

    Args:
        event_name: The name of the event.
        target_open_status: True to open the event, False to close it.

    Raises:
        EventNotFoundError: If the event cannot be found.
        EventArchivedError: If the event is already archived.
        EventAlreadyOpenError: If trying to open an already open event.
        EventAlreadyClosedError: If trying to close an already closed event.
    """
    event = get_event(event_name)

    if event.archived:
        action = "open" if target_open_status else "close"
        raise EventArchivedError(event_name, action)

    # Check if already in the desired state
    if target_open_status and event.open:
        raise EventAlreadyOpenError(event_name)
    if not target_open_status and not event.open:
        raise EventAlreadyClosedError(event_name)

    # Apply the change
    event.open = target_open_status

    # Handle closed_attendance_count
    if target_open_status:
        # Reopening the event - clear the closed attendance count
        event.closed_attendance_count = None
        _log.info(f"Event '{event_name}' reopened, cleared closed_attendance_count.")
    else:
        # Closing the event - capture current attendance count
        responses = get_responses(event_name)
        event.closed_attendance_count = sum(1 + r.extra_people for r in responses)
        _log.info(f"Event '{event_name}' closed with {event.closed_attendance_count} attendees.")

    status_text = "open" if target_open_status else "closed"
    _log.info(f"Event '{event_name}' marked as {status_text} in cache.")
    return event


def archive_event(event_name: str) -> Event:
    """
    Finds an event by name, validates its status, and marks it as archived.
    Also ensures the event is marked as closed.

    Modifies the event object directly within the EVENT_DATA_CACHE.
    Does NOT save the data to disk.

    Raises:
        EventNotFoundError: If the event cannot be found.
        EventAlreadyArchivedError: If the event is already archived.
    """
    event = get_event(event_name)

    if event.archived:
        # Raise specific error even if just checking status
        raise EventAlreadyArchivedError(event_name)

    event.archived = True
    event.open = False  # Archiving always closes the event
    _log.info(f"Event '{event_name}' marked as archived (and closed) in cache.")
    return event
