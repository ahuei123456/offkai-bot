# src/offkai_bot/data/response.py
import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypedDict

from offkai_bot.errors import DuplicateResponseError, NoResponsesFoundError, ResponseNotFoundError

# Use relative imports for sibling modules within the package
from ..config import get_config
from .encoders import DataclassJSONEncoder

_log = logging.getLogger(__name__)


# --- Response Dataclass ---
@dataclass
class Response:
    user_id: int
    username: str
    extra_people: int
    behavior_confirmed: bool
    arrival_confirmed: bool
    event_name: str
    timestamp: datetime
    drinks: list[str] = field(default_factory=list)


# --- Waitlist Entry Dataclass ---
@dataclass
class WaitlistEntry:
    user_id: int
    username: str
    extra_people: int
    behavior_confirmed: bool
    arrival_confirmed: bool
    event_name: str
    timestamp: datetime
    drinks: list[str] = field(default_factory=list)


# --- Type Definitions ---
class EventData(TypedDict):
    attendees: list[Response]
    waitlist: list[WaitlistEntry]


# --- Response Data Handling ---

RESPONSE_DATA_CACHE: dict[str, EventData] | None = None


def _migrate_old_format_to_new(
    old_responses: dict[str, list], old_waitlist: dict[str, list] | None
) -> dict[str, EventData]:
    """
    Migrates old format (separate responses and waitlist dicts) to new unified format.

    Args:
        old_responses: Old responses dict format: {"event_name": [Response, ...]}
        old_waitlist: Old waitlist dict format: {"event_name": [WaitlistEntry, ...]} or None

    Returns:
        New unified format: {"event_name": {"attendees": [...], "waitlist": [...]}}
    """
    new_data: dict[str, EventData] = {}

    # Migrate responses to attendees
    for event_name, responses in old_responses.items():
        new_data[event_name] = EventData(attendees=responses, waitlist=[])

    # Migrate waitlist if it exists
    if old_waitlist:
        for event_name, waitlist_entries in old_waitlist.items():
            if event_name not in new_data:
                new_data[event_name] = EventData(attendees=[], waitlist=waitlist_entries)
            else:
                new_data[event_name]["waitlist"] = waitlist_entries

    return new_data


def _parse_response_from_dict(resp_dict: dict, event_name: str) -> Response | None:
    """Parse a Response object from a dictionary."""
    try:
        ts = None
        if "timestamp" in resp_dict and resp_dict["timestamp"]:
            try:
                ts = datetime.fromisoformat(resp_dict["timestamp"])
            except (ValueError, TypeError):
                _log.warning(
                    f"Could not parse ISO timestamp '{resp_dict.get('timestamp')}' for {event_name}, "
                    f"user {resp_dict.get('user_id')}"
                )
                ts = None

        drinks = resp_dict.get("drinks", [])
        extra_people = int(resp_dict.get("extra_people", 0))
        behavior_confirmed_raw = resp_dict.get("behavior_confirmed", False)
        arrival_confirmed_raw = resp_dict.get("arrival_confirmed", False)
        behavior_confirmed = str(behavior_confirmed_raw).lower() == "yes" or behavior_confirmed_raw is True
        arrival_confirmed = str(arrival_confirmed_raw).lower() == "yes" or arrival_confirmed_raw is True

        return Response(
            user_id=int(resp_dict.get("user_id", 0)),
            username=resp_dict.get("username", "Unknown User"),
            extra_people=extra_people,
            behavior_confirmed=behavior_confirmed,
            arrival_confirmed=arrival_confirmed,
            event_name=resp_dict.get("event_name", event_name),
            timestamp=(ts if ts is not None else datetime.now()),
            drinks=drinks,
        )
    except (TypeError, ValueError) as e:
        _log.error(f"Error creating Response object for event {event_name} from dict {resp_dict}: {e}")
        return None


def _parse_waitlist_entry_from_dict(entry_dict: dict, event_name: str) -> WaitlistEntry | None:
    """Parse a WaitlistEntry object from a dictionary."""
    try:
        ts = None
        if "timestamp" in entry_dict and entry_dict["timestamp"]:
            try:
                ts = datetime.fromisoformat(entry_dict["timestamp"])
            except (ValueError, TypeError):
                _log.warning(
                    f"Could not parse ISO timestamp '{entry_dict.get('timestamp')}' for {event_name}, "
                    f"user {entry_dict.get('user_id')}"
                )
                ts = None

        drinks = entry_dict.get("drinks", [])
        extra_people = int(entry_dict.get("extra_people", 0))
        behavior_confirmed_raw = entry_dict.get("behavior_confirmed", False)
        arrival_confirmed_raw = entry_dict.get("arrival_confirmed", False)
        behavior_confirmed = str(behavior_confirmed_raw).lower() == "yes" or behavior_confirmed_raw is True
        arrival_confirmed = str(arrival_confirmed_raw).lower() == "yes" or arrival_confirmed_raw is True

        return WaitlistEntry(
            user_id=int(entry_dict.get("user_id", 0)),
            username=entry_dict.get("username", "Unknown User"),
            extra_people=extra_people,
            behavior_confirmed=behavior_confirmed,
            arrival_confirmed=arrival_confirmed,
            event_name=entry_dict.get("event_name", event_name),
            timestamp=(ts if ts is not None else datetime.now()),
            drinks=drinks,
        )
    except (TypeError, ValueError) as e:
        _log.error(f"Error creating WaitlistEntry object for event {event_name} from dict {entry_dict}: {e}")
        return None


def _load_responses() -> dict[str, EventData]:
    """
    Loads response data from JSON, converts to Response dataclasses,
    and handles missing or empty files. Supports both old and new formats. (Internal use)
    """
    global RESPONSE_DATA_CACHE
    settings = get_config()
    responses_dict: dict[str, EventData] = {}
    file_path = settings["RESPONSES_FILE"]

    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise FileNotFoundError

        with open(file_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)

        if not isinstance(raw_data, dict):
            _log.error(
                f"Invalid format in {file_path}: "
                f"Expected a JSON object (dict), got {type(raw_data)}. Loading empty responses."
            )
            raw_data = {}

        # Detect format: new format has nested dict with "attendees"/"waitlist" keys
        # Old format has lists directly
        is_new_format = False
        if raw_data:
            first_value = next(iter(raw_data.values()))
            is_new_format = isinstance(first_value, dict) and ("attendees" in first_value or "waitlist" in first_value)

        if is_new_format:
            # New format: {"event_name": {"attendees": [...], "waitlist": [...]}}
            for event_name, event_data in raw_data.items():
                if not isinstance(event_data, dict):
                    _log.warning(
                        f"Invalid format for event '{event_name}' in {file_path}: "
                        f"Expected a dict with 'attendees'/'waitlist', got {type(event_data)}. Skipping."
                    )
                    continue

                # Parse attendees
                attendees_list = []
                attendees_raw = event_data.get("attendees", [])
                if not isinstance(attendees_raw, list):
                    _log.warning(f"Attendees for '{event_name}' is not a list. Skipping attendees.")
                else:
                    for resp_dict in attendees_raw:
                        if not isinstance(resp_dict, dict):
                            _log.warning(f"Invalid attendee item in '{event_name}': Expected dict. Skipping.")
                            continue
                        response = _parse_response_from_dict(resp_dict, event_name)
                        if response:
                            attendees_list.append(response)

                # Parse waitlist
                waitlist_list = []
                waitlist_raw = event_data.get("waitlist", [])
                if not isinstance(waitlist_raw, list):
                    _log.warning(f"Waitlist for '{event_name}' is not a list. Skipping waitlist.")
                else:
                    for entry_dict in waitlist_raw:
                        if not isinstance(entry_dict, dict):
                            _log.warning(f"Invalid waitlist item in '{event_name}': Expected dict. Skipping.")
                            continue
                        entry = _parse_waitlist_entry_from_dict(entry_dict, event_name)
                        if entry:
                            waitlist_list.append(entry)

                responses_dict[event_name] = EventData(attendees=attendees_list, waitlist=waitlist_list)

        else:
            # Old format: {"event_name": [Response, ...]}
            # Need to migrate - also check for old waitlist file
            _log.info("Detected old format responses file. Migrating to new format...")

            old_responses: dict[str, list[Response]] = {}
            for event_name, response_list in raw_data.items():
                processed_responses = []
                if not isinstance(response_list, list):
                    _log.warning(
                        f"Invalid format for event '{event_name}' in {file_path}: "
                        f"Expected a list, got {type(response_list)}. Skipping."
                    )
                    continue

                for resp_dict in response_list:
                    if not isinstance(resp_dict, dict):
                        _log.warning(
                            f"Invalid response item for event '{event_name}' in {file_path}: Expected a dict. Skipping."
                        )
                        continue
                    response = _parse_response_from_dict(resp_dict, event_name)
                    if response:
                        processed_responses.append(response)

                old_responses[event_name] = processed_responses

            # Try to load old waitlist file if it exists
            old_waitlist: dict[str, list[WaitlistEntry]] | None = None
            waitlist_file = settings.get("WAITLIST_FILE")
            if waitlist_file and os.path.exists(waitlist_file) and os.path.getsize(waitlist_file) > 0:
                _log.info(f"Found old waitlist file at {waitlist_file}. Migrating...")
                try:
                    with open(waitlist_file, "r", encoding="utf-8") as wf:
                        waitlist_raw = json.load(wf)

                    if isinstance(waitlist_raw, dict):
                        old_waitlist = {}
                        for event_name, waitlist_list in waitlist_raw.items():
                            processed_entries = []
                            if not isinstance(waitlist_list, list):
                                continue

                            for entry_dict in waitlist_list:
                                if not isinstance(entry_dict, dict):
                                    continue
                                entry = _parse_waitlist_entry_from_dict(entry_dict, event_name)
                                if entry:
                                    processed_entries.append(entry)

                            old_waitlist[event_name] = processed_entries
                except Exception as e:
                    _log.warning(f"Could not load old waitlist file: {e}")

            # Migrate to new format
            responses_dict = _migrate_old_format_to_new(old_responses, old_waitlist)

            # Save in new format immediately
            RESPONSE_DATA_CACHE = responses_dict
            save_responses()
            _log.info("Migration complete. Saved to new format.")

    except FileNotFoundError:
        _log.warning(f"{file_path} not found or empty. Creating default empty file.")
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump({}, file, indent=4)
            _log.info(f"Created empty responses file at {file_path}")
        except OSError as e:
            _log.error(f"Could not create default responses file at {file_path}: {e}")
        RESPONSE_DATA_CACHE = {}
        return {}
    except json.JSONDecodeError:
        _log.error(
            f"Error decoding JSON from {file_path}. File might be corrupted or invalid. Loading empty responses."
        )
        RESPONSE_DATA_CACHE = {}
        return {}
    except Exception as e:
        _log.exception(f"An unexpected error occurred loading response data from {file_path}: {e}")
        RESPONSE_DATA_CACHE = {}
        return {}

    RESPONSE_DATA_CACHE = responses_dict
    return responses_dict


def load_responses() -> dict[str, EventData]:
    """Returns cached response data or loads it if cache is empty."""
    if RESPONSE_DATA_CACHE is not None:
        return RESPONSE_DATA_CACHE
    else:
        return _load_responses()


def save_responses():
    """Saves the current state of RESPONSE_DATA_CACHE to the JSON file in new format."""
    global RESPONSE_DATA_CACHE
    settings = get_config()
    if RESPONSE_DATA_CACHE is None:
        _log.error("Attempted to save response data before loading.")
        return

    try:
        with open(settings["RESPONSES_FILE"], "w", encoding="utf-8") as file:
            json.dump(
                RESPONSE_DATA_CACHE,
                file,
                indent=4,
                cls=DataclassJSONEncoder,
                ensure_ascii=False,
            )
    except OSError as e:
        _log.error(f"Error writing response data to {settings['RESPONSES_FILE']}: {e}")
    except Exception as e:
        _log.exception(f"An unexpected error occurred saving response data: {e}")


def get_responses(event_name: str) -> list[Response]:
    """Gets the list of Response objects (attendees) for a specific event from cache."""
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))
    return event_data["attendees"]


def get_waitlist(event_name: str) -> list[WaitlistEntry]:
    """Gets the list of WaitlistEntry objects for a specific event from cache."""
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))
    return event_data["waitlist"]


def add_response(event_name: str, response: Response) -> None:
    """Adds a response to the specified event's attendees.

    Raises:
        DuplicateResponseError: If the user has already responded to this event or is on the waitlist.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    # Check for duplicate response in attendees
    if any(r.user_id == response.user_id for r in event_data["attendees"]):
        _log.warning(f"User {response.user_id} already responded to event {event_name}. Raising error.")
        raise DuplicateResponseError(event_name, response.user_id)

    # Check if user is on waitlist
    if any(e.user_id == response.user_id for e in event_data["waitlist"]):
        _log.warning(f"User {response.user_id} is on waitlist for event {event_name}. Cannot add to responses.")
        raise DuplicateResponseError(event_name, response.user_id)

    # If no duplicate, proceed with adding
    event_data["attendees"].append(response)
    all_data[event_name] = event_data
    save_responses()
    _log.info(f"Added response from user {response.user_id} to event {event_name}.")


def remove_response(event_name: str, user_id: int) -> None:
    """Removes a response for a given user from the specified event's attendees.

    Raises:
        ResponseNotFoundError: If no response is found for the given user and event.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    initial_count = len(event_data["attendees"])
    # Filter out the response matching the user_id
    event_data["attendees"] = [r for r in event_data["attendees"] if r.user_id != user_id]

    # Check if any response was actually removed
    if len(event_data["attendees"]) == initial_count:
        # No response found for the user, raise error
        _log.warning(f"No response found for user {user_id} in event {event_name} to remove. Raising error.")
        raise ResponseNotFoundError(event_name, user_id)
    else:
        # Response found and removed, update the cache and save
        all_data[event_name] = event_data
        save_responses()
        _log.info(f"Removed response from user {user_id} for event {event_name}.")


def add_to_waitlist(event_name: str, entry: WaitlistEntry) -> None:
    """Adds an entry to the waitlist for the specified event.

    Raises:
        DuplicateResponseError: If the user is already on the waitlist or has already responded to this event.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    # Check for duplicate entry in waitlist
    if any(e.user_id == entry.user_id for e in event_data["waitlist"]):
        _log.warning(f"User {entry.user_id} already on waitlist for event {event_name}. Raising error.")
        raise DuplicateResponseError(event_name, entry.user_id)

    # Check if user has already responded
    if any(r.user_id == entry.user_id for r in event_data["attendees"]):
        _log.warning(f"User {entry.user_id} already responded to event {event_name}. Cannot add to waitlist.")
        raise DuplicateResponseError(event_name, entry.user_id)

    # If no duplicate, proceed with adding
    event_data["waitlist"].append(entry)
    all_data[event_name] = event_data
    save_responses()
    _log.info(f"Added user {entry.user_id} to waitlist for event {event_name}.")


def remove_from_waitlist(event_name: str, user_id: int) -> None:
    """Removes an entry from the waitlist for the specified event.

    Raises:
        ResponseNotFoundError: If the user is not found on the waitlist.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    initial_count = len(event_data["waitlist"])
    event_data["waitlist"] = [e for e in event_data["waitlist"] if e.user_id != user_id]

    if len(event_data["waitlist"]) == initial_count:
        _log.warning(f"No waitlist entry found for user {user_id} in event {event_name}. Raising error.")
        raise ResponseNotFoundError(event_name, user_id)
    else:
        all_data[event_name] = event_data
        save_responses()
        _log.info(f"Removed user {user_id} from waitlist for event {event_name}.")


def promote_from_waitlist(event_name: str) -> WaitlistEntry | None:
    """
    Removes and returns the first entry from the waitlist (FIFO).
    Returns None if the waitlist is empty.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    if not event_data["waitlist"]:
        return None

    # Get the first entry (FIFO)
    first_entry = event_data["waitlist"].pop(0)
    all_data[event_name] = event_data
    save_responses()
    _log.info(f"Promoted user {first_entry.user_id} from waitlist for event {event_name}.")

    return first_entry


def calculate_attendance(event_name: str) -> tuple[int, list[str]]:
    """
    Calculates the total attendance count and generates a list of attendee names
    (including extras) for a given event.

    Args:
        event_name: The name of the event.

    Returns:
        A tuple containing:
            - total_count (int): The total number of attendees including extras.
            - attendee_names (list[str]): A list of formatted attendee names.

    Raises:
        NoResponsesFoundError: If no responses are found for the event.
    """
    responses = get_responses(event_name)
    if not responses:
        raise NoResponsesFoundError(event_name)

    attendee_names = []
    drinks = []
    total_count = 0
    for response in responses:
        # Add the main person
        attendee_names.append(f"{response.username}")
        total_count += 1

        # Add extra people
        for i in range(response.extra_people):
            attendee_names.append(f"{response.username} +{i + 1}")
            total_count += 1

        # Add drinks (if required)
        if len(response.drinks) > 0:
            drinks.extend(response.drinks)

    _log.info(f"Calculated attendance for '{event_name}': {total_count} attendees.")
    return total_count, attendee_names


def calculate_drinks(event_name: str) -> tuple[int, dict[str, int]]:
    responses = get_responses(event_name)
    if not responses:
        raise NoResponsesFoundError(event_name)

    drinks = []

    for response in responses:
        # Add drinks (if required)
        if len(response.drinks) > 0:
            drinks.extend(response.drinks)

    if len(drinks) > 0:
        drinks_count = Counter(drinks)

        _log.info(f"Calculated {len(drinks)} drink(s) for '{event_name}'.")

        return len(drinks), drinks_count
    else:
        _log.info(f"No drinks found for '{event_name}'.")
        return 0, {}
