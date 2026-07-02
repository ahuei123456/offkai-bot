# src/offkai_bot/data/response.py
import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypedDict

# Use relative imports for sibling modules within the package
from offkai_bot.config import get_config
from offkai_bot.data.atomic import atomic_write_json, backup_corrupted_file
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.errors import (
    DuplicateResponseError,
    NoResponsesFoundError,
    NoWaitlistEntriesFoundError,
    ResponseNotFoundError,
)

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
    extras_names: list[str] = field(default_factory=list)
    display_name: str | None = None
    attendee_number: int | None = None
    extras_attendee_numbers: list[int] = field(default_factory=list)


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
    extras_names: list[str] = field(default_factory=list)
    display_name: str | None = None


@dataclass(frozen=True)
class AttendeeReportRow:
    attendee_number: int
    name: str
    type: str
    registered_by_username: str
    registered_by_display_name: str
    registered_by_user_id: int
    guest_index: int | None
    drink: str


# --- Type Definitions ---
class EventData(TypedDict):
    attendees: list[Response]
    waitlist: list[WaitlistEntry]


class NumberedAttendeeName(str):
    attendee_number: int | None

    def __new__(cls, value: str, attendee_number: int | None = None):
        obj = str.__new__(cls, value)
        obj.attendee_number = attendee_number
        return obj


# --- Response Data Handling ---

RESPONSE_DATA_CACHE: dict[str, EventData] | None = None


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _parse_required_int(value)


def _parse_int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [_parse_required_int(item) for item in value]


def _parse_required_int(value: object) -> int:
    if not isinstance(value, int | str):
        raise TypeError(f"Expected int-compatible attendee number, got {type(value).__name__}")
    return int(value)


def _group_attendee_numbers(response: Response) -> list[int]:
    numbers = []
    if response.attendee_number is not None:
        numbers.append(response.attendee_number)
    numbers.extend(response.extras_attendee_numbers)
    return numbers


def _event_has_attendee_numbers(event_data: EventData) -> bool:
    return any(_group_attendee_numbers(response) for response in event_data["attendees"])


def _next_attendee_number(event_data: EventData) -> int:
    assigned_numbers = [number for response in event_data["attendees"] for number in _group_attendee_numbers(response)]
    return max(assigned_numbers, default=0) + 1


def _max_attendee_number(event_data: EventData) -> int:
    assigned_numbers = [number for response in event_data["attendees"] for number in _group_attendee_numbers(response)]
    return max(assigned_numbers, default=0)


def _assign_group_numbers(response: Response, start_number: int) -> int:
    response.attendee_number = start_number
    response.extras_attendee_numbers = list(range(start_number + 1, start_number + 1 + response.extra_people))
    return start_number + 1 + response.extra_people


def _clear_group_numbers(response: Response) -> None:
    response.attendee_number = None
    response.extras_attendee_numbers = []


def _number_for_extra(response: Response, index: int) -> int | None:
    if index < len(response.extras_attendee_numbers):
        return response.extras_attendee_numbers[index]
    return None


def _has_complete_attendee_numbers(responses: list[Response]) -> bool:
    expected_count = sum(1 + response.extra_people for response in responses)
    actual_numbers = [number for response in responses for number in _group_attendee_numbers(response)]
    return (
        len(actual_numbers) == expected_count
        and len(set(actual_numbers)) == expected_count
        and all(number > 0 for number in actual_numbers)
    )


def _drink_for(response: Response, index: int) -> str:
    if index < len(response.drinks):
        return response.drinks[index]
    return "N/A"


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
                    "Could not parse ISO timestamp '%s' for %s, user %s",
                    resp_dict.get("timestamp"),
                    event_name,
                    resp_dict.get("user_id"),
                )
                ts = None

        drinks = resp_dict.get("drinks", [])
        extra_people = int(resp_dict.get("extra_people", 0))
        behavior_confirmed_raw = resp_dict.get("behavior_confirmed", False)
        arrival_confirmed_raw = resp_dict.get("arrival_confirmed", False)
        behavior_confirmed = str(behavior_confirmed_raw).lower() == "yes" or behavior_confirmed_raw is True
        arrival_confirmed = str(arrival_confirmed_raw).lower() == "yes" or arrival_confirmed_raw is True
        extras_names = resp_dict.get("extras_names", [])
        display_name = resp_dict.get("display_name")
        attendee_number = _parse_optional_int(resp_dict.get("attendee_number"))
        extras_attendee_numbers = _parse_int_list(resp_dict.get("extras_attendee_numbers", []))

        return Response(
            user_id=int(resp_dict.get("user_id", 0)),
            username=resp_dict.get("username", "Unknown User"),
            extra_people=extra_people,
            behavior_confirmed=behavior_confirmed,
            arrival_confirmed=arrival_confirmed,
            event_name=resp_dict.get("event_name", event_name),
            timestamp=(ts if ts is not None else datetime.now()),
            drinks=drinks,
            extras_names=extras_names,
            display_name=display_name,
            attendee_number=attendee_number,
            extras_attendee_numbers=extras_attendee_numbers,
        )
    except (TypeError, ValueError) as e:
        _log.error("Error creating Response object for event %s from dict %s: %s", event_name, resp_dict, e)
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
                    "Could not parse ISO timestamp '%s' for %s, user %s",
                    entry_dict.get("timestamp"),
                    event_name,
                    entry_dict.get("user_id"),
                )
                ts = None

        drinks = entry_dict.get("drinks", [])
        extra_people = int(entry_dict.get("extra_people", 0))
        behavior_confirmed_raw = entry_dict.get("behavior_confirmed", False)
        arrival_confirmed_raw = entry_dict.get("arrival_confirmed", False)
        behavior_confirmed = str(behavior_confirmed_raw).lower() == "yes" or behavior_confirmed_raw is True
        arrival_confirmed = str(arrival_confirmed_raw).lower() == "yes" or arrival_confirmed_raw is True
        extras_names = entry_dict.get("extras_names", [])
        display_name = entry_dict.get("display_name")

        return WaitlistEntry(
            user_id=int(entry_dict.get("user_id", 0)),
            username=entry_dict.get("username", "Unknown User"),
            extra_people=extra_people,
            behavior_confirmed=behavior_confirmed,
            arrival_confirmed=arrival_confirmed,
            event_name=entry_dict.get("event_name", event_name),
            timestamp=(ts if ts is not None else datetime.now()),
            drinks=drinks,
            extras_names=extras_names,
            display_name=display_name,
        )
    except (TypeError, ValueError) as e:
        _log.error("Error creating WaitlistEntry object for event %s from dict %s: %s", event_name, entry_dict, e)
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
                "Invalid format in %s: Expected a JSON object (dict), got %s. Loading empty responses.",
                file_path,
                type(raw_data),
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
                        "Invalid format for event '%s' in %s: "
                        "Expected a dict with 'attendees'/'waitlist', got %s. Skipping.",
                        event_name,
                        file_path,
                        type(event_data),
                    )
                    continue

                # Parse attendees
                attendees_list = []
                attendees_raw = event_data.get("attendees", [])
                if not isinstance(attendees_raw, list):
                    _log.warning("Attendees for '%s' is not a list. Skipping attendees.", event_name)
                else:
                    for resp_dict in attendees_raw:
                        if not isinstance(resp_dict, dict):
                            _log.warning("Invalid attendee item in '%s': Expected dict. Skipping.", event_name)
                            continue
                        response = _parse_response_from_dict(resp_dict, event_name)
                        if response:
                            attendees_list.append(response)

                # Parse waitlist
                waitlist_list = []
                waitlist_raw = event_data.get("waitlist", [])
                if not isinstance(waitlist_raw, list):
                    _log.warning("Waitlist for '%s' is not a list. Skipping waitlist.", event_name)
                else:
                    for entry_dict in waitlist_raw:
                        if not isinstance(entry_dict, dict):
                            _log.warning("Invalid waitlist item in '%s': Expected dict. Skipping.", event_name)
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
                        "Invalid format for event '%s' in %s: Expected a list, got %s. Skipping.",
                        event_name,
                        file_path,
                        type(response_list),
                    )
                    continue

                for resp_dict in response_list:
                    if not isinstance(resp_dict, dict):
                        _log.warning(
                            "Invalid response item for event '%s' in %s: Expected a dict. Skipping.",
                            event_name,
                            file_path,
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
                _log.info("Found old waitlist file at %s. Migrating...", waitlist_file)
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
                    _log.warning("Could not load old waitlist file: %s", e)

            # Migrate to new format
            responses_dict = _migrate_old_format_to_new(old_responses, old_waitlist)

            # Save in new format immediately
            RESPONSE_DATA_CACHE = responses_dict
            save_responses()
            _log.info("Migration complete. Saved to new format.")

    except FileNotFoundError:
        _log.warning("%s not found or empty. Creating default empty file.", file_path)
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump({}, file, indent=4)
            _log.info("Created empty responses file at %s", file_path)
        except OSError as e:
            _log.error("Could not create default responses file at %s: %s", file_path, e)
        RESPONSE_DATA_CACHE = {}
        return {}
    except json.JSONDecodeError:
        _log.error(
            "Error decoding JSON from %s. File might be corrupted or invalid. Loading empty responses.", file_path
        )
        backup_corrupted_file(file_path)
        RESPONSE_DATA_CACHE = {}
        return {}
    except Exception as e:
        _log.exception("An unexpected error occurred loading response data from %s: %s", file_path, e)
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
        atomic_write_json(
            settings["RESPONSES_FILE"],
            RESPONSE_DATA_CACHE,
            indent=4,
            cls=DataclassJSONEncoder,
            ensure_ascii=False,
        )
    except OSError as e:
        _log.error("Error writing response data to %s: %s", settings["RESPONSES_FILE"], e)
    except Exception as e:
        _log.exception("An unexpected error occurred saving response data: %s", e)


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


def has_complete_attendee_numbers(event_name: str) -> bool:
    """Return True when every current attendee slot has a unique stored number."""
    return _has_complete_attendee_numbers(get_responses(event_name))


def get_max_attendee_number(event_name: str) -> int:
    """Return the highest currently stored attendee number for an event."""
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))
    return _max_attendee_number(event_data)


def build_attendee_report_rows(event_name: str) -> list[AttendeeReportRow]:
    """Build CSV-ready attendee report rows sorted by stored attendee number."""
    responses = get_responses(event_name)
    rows: list[AttendeeReportRow] = []

    for response in responses:
        if response.attendee_number is not None:
            rows.append(
                AttendeeReportRow(
                    attendee_number=response.attendee_number,
                    name=response.username,
                    type="primary",
                    registered_by_username=response.username,
                    registered_by_display_name=response.display_name or "",
                    registered_by_user_id=response.user_id,
                    guest_index=None,
                    drink=_drink_for(response, 0),
                )
            )

        for index in range(response.extra_people):
            attendee_number = _number_for_extra(response, index)
            if attendee_number is None:
                continue

            raw_name = response.extras_names[index] if index < len(response.extras_names) else ""
            guest_name = raw_name.strip() if isinstance(raw_name, str) else ""
            rows.append(
                AttendeeReportRow(
                    attendee_number=attendee_number,
                    name=guest_name or f"Guest {index + 1}",
                    type="guest",
                    registered_by_username=response.username,
                    registered_by_display_name=response.display_name or "",
                    registered_by_user_id=response.user_id,
                    guest_index=index + 1,
                    drink=_drink_for(response, index + 1),
                )
            )

    return sorted(rows, key=lambda row: row.attendee_number)


def assign_attendee_numbers(event_name: str) -> int:
    """Assign close-time attendee numbers for confirmed attendees in the response cache."""
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    next_number = 1
    for response in sorted(event_data["attendees"], key=lambda r: (r.username.casefold(), r.user_id)):
        next_number = _assign_group_numbers(response, next_number)

    all_data[event_name] = event_data
    _log.info("Assigned attendee numbers for event %s.", event_name)
    return next_number - 1


def clear_attendee_numbers(event_name: str) -> None:
    """Clear attendee numbers for an event so the next close can assign them from scratch."""
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    for response in event_data["attendees"]:
        _clear_group_numbers(response)

    all_data[event_name] = event_data
    _log.info("Cleared attendee numbers for event %s.", event_name)


def add_response(
    event_name: str,
    response: Response,
    *,
    force_attendee_number: bool = False,
    attendee_number_start: int | None = None,
) -> int | None:
    """Adds a response to the specified event's attendees.

    Raises:
        DuplicateResponseError: If the user has already responded to this event or is on the waitlist.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    # Check for duplicate response in attendees
    if any(r.user_id == response.user_id for r in event_data["attendees"]):
        _log.warning("User %s already responded to event %s. Raising error.", response.user_id, event_name)
        raise DuplicateResponseError(event_name, response.user_id)

    # Check if user is on waitlist
    if any(e.user_id == response.user_id for e in event_data["waitlist"]):
        _log.warning("User %s is on waitlist for event %s. Cannot add to responses.", response.user_id, event_name)
        raise DuplicateResponseError(event_name, response.user_id)

    # If no duplicate, proceed with adding
    assigned_max_number = None
    if force_attendee_number or _event_has_attendee_numbers(event_data):
        start_number = attendee_number_start if attendee_number_start is not None else _next_attendee_number(event_data)
        assigned_max_number = _assign_group_numbers(response, start_number) - 1

    event_data["attendees"].append(response)
    all_data[event_name] = event_data
    save_responses()
    _log.info("Added response from user %s to event %s.", response.user_id, event_name)
    return assigned_max_number


def remove_response(event_name: str, user_id: int) -> None:
    """Removes a response for a given user from the specified event's attendees.

    Raises:
        ResponseNotFoundError: If no response is found for the given user and event.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    removed_response = next((r for r in event_data["attendees"] if r.user_id == user_id), None)

    # Check if any response was actually removed
    if removed_response is None:
        # No response found for the user, raise error
        _log.warning("No response found for user %s in event %s to remove. Raising error.", user_id, event_name)
        raise ResponseNotFoundError(event_name, user_id)
    else:
        # Response found and removed, update the cache and save
        event_data["attendees"] = [r for r in event_data["attendees"] if r.user_id != user_id]
        all_data[event_name] = event_data
        save_responses()
        _log.info("Removed response from user %s for event %s.", user_id, event_name)


def add_to_waitlist(event_name: str, entry: WaitlistEntry) -> None:
    """Adds an entry to the waitlist for the specified event.

    Raises:
        DuplicateResponseError: If the user is already on the waitlist or has already responded to this event.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    # Check for duplicate entry in waitlist
    if any(e.user_id == entry.user_id for e in event_data["waitlist"]):
        _log.warning("User %s already on waitlist for event %s. Raising error.", entry.user_id, event_name)
        raise DuplicateResponseError(event_name, entry.user_id)

    # Check if user has already responded
    if any(r.user_id == entry.user_id for r in event_data["attendees"]):
        _log.warning("User %s already responded to event %s. Cannot add to waitlist.", entry.user_id, event_name)
        raise DuplicateResponseError(event_name, entry.user_id)

    # If no duplicate, proceed with adding
    event_data["waitlist"].append(entry)
    all_data[event_name] = event_data
    save_responses()
    _log.info("Added user %s to waitlist for event %s.", entry.user_id, event_name)


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
        _log.warning("No waitlist entry found for user %s in event %s. Raising error.", user_id, event_name)
        raise ResponseNotFoundError(event_name, user_id)
    else:
        all_data[event_name] = event_data
        save_responses()
        _log.info("Removed user %s from waitlist for event %s.", user_id, event_name)


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
    _log.info("Promoted user %s from waitlist for event %s.", first_entry.user_id, event_name)

    return first_entry


def promote_specific_from_waitlist(event_name: str, user_id: int) -> WaitlistEntry:
    """
    Removes and returns a specific user from the waitlist by user_id.

    Raises:
        ResponseNotFoundError: If the user is not found on the waitlist.
    """
    all_data = load_responses()
    event_data = all_data.get(event_name, EventData(attendees=[], waitlist=[]))

    for i, entry in enumerate(event_data["waitlist"]):
        if entry.user_id == user_id:
            promoted_entry = event_data["waitlist"].pop(i)
            all_data[event_name] = event_data
            save_responses()
            _log.info("Promoted specific user %s from waitlist for event %s.", user_id, event_name)
            return promoted_entry

    raise ResponseNotFoundError(event_name, user_id)


def calculate_attendance(
    event_name: str, *, nicknames: bool = False, drinks: bool = False, sort: bool = False
) -> tuple[int, list[str]]:
    """
    Calculates the total attendance count and generates a list of attendee names
    (including extras) for a given event.

    Args:
        event_name: The name of the event.
        nicknames: If True, show display names alongside usernames when they differ.
        drinks: If True, append each attendee's drink choice.
        sort: If True, sort based on the main user and bundle extras after them.
            Ignored for completely numbered events so stored numbers display in sequence.

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

    has_complete_attendee_numbers = _has_complete_attendee_numbers(responses)
    if sort and not has_complete_attendee_numbers:
        responses = sorted(responses, key=lambda r: r.username.lower())

    attendee_names: list[str] = []
    total_count = 0
    for response in responses:
        # Add the main person
        name = response.username
        if nicknames and response.display_name and response.display_name != response.username:
            name = f"{response.username} ({response.display_name})"
        if drinks:
            drink = response.drinks[0] if response.drinks else "N/A"
            name = f"{name} - {drink}"
        attendee_names.append(NumberedAttendeeName(name, response.attendee_number))
        total_count += 1

        # Add extra people
        for i in range(response.extra_people):
            raw_name = response.extras_names[i] if i < len(response.extras_names) else ""
            stripped_name = raw_name.strip() if isinstance(raw_name, str) else ""
            name = stripped_name or " "
            name += f" ({response.username} +{i + 1})"
            if drinks:
                drink_index = i + 1
                drink = response.drinks[drink_index] if drink_index < len(response.drinks) else "N/A"
                name = f"{name} - {drink}"
            attendee_names.append(NumberedAttendeeName(name, _number_for_extra(response, i)))
            total_count += 1

    if has_complete_attendee_numbers:
        attendee_names = sorted(attendee_names, key=lambda name: getattr(name, "attendee_number"))

    _log.info("Calculated attendance for '%s': %s attendees.", event_name, total_count)
    return total_count, attendee_names


def calculate_waitlist(event_name: str, *, nicknames: bool = False, sort: bool = False) -> tuple[int, list[str]]:
    """
    Calculates the total waitlist count and generates a list of waitlisted names
    (including extras) for a given event.

    Args:
        event_name: The name of the event.
        nicknames: If True, show display names alongside usernames when they differ.
        sort: If True, sort based on the main user and bundle extras after them.

    Returns:
        A tuple containing:
            - total_count (int): The total number of waitlisted people including extras.
            - waitlisted_names (list[str]): A list of formatted waitlisted names.

    Raises:
        NoWaitlistEntriesFoundError: If no waitlist entries are found for the event.
    """
    entries = get_waitlist(event_name)
    if not entries:
        raise NoWaitlistEntriesFoundError(event_name)

    if sort:
        entries = sorted(entries, key=lambda e: e.username.lower())

    waitlisted_names = []
    total_count = 0
    for entry in entries:
        name = entry.username
        if nicknames and entry.display_name and entry.display_name != entry.username:
            name = f"{entry.username} ({entry.display_name})"
        waitlisted_names.append(name)
        total_count += 1

        for i in range(entry.extra_people):
            raw_name = entry.extras_names[i] if i < len(entry.extras_names) else ""
            stripped_name = raw_name.strip() if isinstance(raw_name, str) else ""
            name = stripped_name or " "
            name += f" ({entry.username} +{i + 1})"
            waitlisted_names.append(name)
            total_count += 1

    _log.info("Calculated waitlist for '%s': %s waitlisted.", event_name, total_count)
    return total_count, waitlisted_names


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

        _log.info("Calculated %s drink(s) for '%s'.", len(drinks), event_name)

        return len(drinks), drinks_count
    else:
        _log.info("No drinks found for '%s'.", event_name)
        return 0, {}
