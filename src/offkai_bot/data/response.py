# src/offkai_bot/data/response.py
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

from offkai_bot.errors import NoResponsesFoundError

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


# --- Response Data Handling ---

RESPONSE_DATA_CACHE: dict[str, list[Response]] | None = None


def _load_responses() -> dict[str, list[Response]]:
    """
    Loads response data from JSON, converts to Response dataclasses,
    and handles missing or empty files. (Internal use)
    """
    global RESPONSE_DATA_CACHE
    settings = get_config()
    responses_dict: dict[str, list[Response]] = {}
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
                        f"Invalid response item for event '{event_name}' in {file_path}: "
                        f"Expected a dict, got {type(resp_dict)}. Skipping."
                    )
                    continue

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

                try:
                    extra_people = int(resp_dict.get("extra_people", 0))
                    behavior_confirmed_raw = resp_dict.get("behavior_confirmed", False)
                    arrival_confirmed_raw = resp_dict.get("arrival_confirmed", False)
                    behavior_confirmed = str(behavior_confirmed_raw).lower() == "yes" or behavior_confirmed_raw is True
                    arrival_confirmed = str(arrival_confirmed_raw).lower() == "yes" or arrival_confirmed_raw is True

                    response = Response(
                        user_id=int(resp_dict.get("user_id", 0)),
                        username=resp_dict.get("username", "Unknown User"),
                        extra_people=extra_people,
                        behavior_confirmed=behavior_confirmed,
                        arrival_confirmed=arrival_confirmed,
                        event_name=resp_dict.get("event_name", event_name),
                        timestamp=(ts if ts is not None else datetime.now()),
                        drinks=drinks,
                    )
                    processed_responses.append(response)
                except (TypeError, ValueError) as e:
                    _log.error(f"Error creating Response object for event {event_name} from dict {resp_dict}: {e}")

            responses_dict[event_name] = processed_responses

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


def load_responses() -> dict[str, list[Response]]:
    """Returns cached response data or loads it if cache is empty."""
    if RESPONSE_DATA_CACHE is not None:
        return RESPONSE_DATA_CACHE
    else:
        return _load_responses()


def save_responses():
    """Saves the current state of RESPONSE_DATA_CACHE to the JSON file."""
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
    """Gets the list of Response objects for a specific event from cache."""
    responses = load_responses()
    return responses.get(event_name, [])


def add_response(event_name: str, response: Response) -> bool:
    """Adds a response to the specified event, checking for duplicates."""
    all_responses = load_responses()
    event_responses = all_responses.get(event_name, [])

    if any(r.user_id == response.user_id for r in event_responses):
        _log.warning(f"User {response.user_id} already responded to event {event_name}.")
        return False

    event_responses.append(response)
    all_responses[event_name] = event_responses
    save_responses()
    _log.info(f"Added response from user {response.user_id} to event {event_name}.")
    return True


def remove_response(event_name: str, user_id: int) -> bool:
    """Removes a response for a given user from the specified event."""
    all_responses = load_responses()
    event_responses = all_responses.get(event_name, [])

    initial_count = len(event_responses)
    new_event_responses = [r for r in event_responses if r.user_id != user_id]

    if len(new_event_responses) < initial_count:
        all_responses[event_name] = new_event_responses
        save_responses()
        _log.info(f"Removed response from user {user_id} for event {event_name}.")
        return True
    else:
        _log.warning(f"No response found for user {user_id} in event {event_name} to remove.")
        return False


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
    total_count = 0
    for response in responses:
        # Add the main person
        attendee_names.append(f"{response.username}")
        total_count += 1
        # Add extra people
        for i in range(response.extra_people):
            attendee_names.append(f"{response.username} +{i + 1}")
            total_count += 1

    _log.info(f"Calculated attendance for '{event_name}': {total_count} attendees.")
    return total_count, attendee_names
