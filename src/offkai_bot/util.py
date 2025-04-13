import json
import logging
import os
from dataclasses import asdict, is_dataclass  # Import asdict and is_dataclass
from datetime import datetime

from .config import get_config
from .event import Event, Response  # Import the dataclasses

EVENT_DATA_CACHE: list[Event] | None = None
RESPONSE_DATA_CACHE: dict[str, list[Response]] | None = None
DATETIME_FORMAT = r"%Y-%m-%d %H:%M"  # Define the expected format in JSON message
DATETIME_ISO_FORMAT = "isoformat"  # How we'll store datetimes in JSON going forward

OFFKAI_MESSAGE = (
    "Please take note of the following:\n"
    "1. We will not accomodate any allergies or dietary restrictions.\n"
    "2. Please register yourself and all your +1s by the deadline if you are planning on attending. Anyone who shows up uninvited or with uninvited guests can and will be turned away.\n"
    "3. Please show up on time. Restaurants tend to be packed after live events and we have been asked to give up table space in the past.\n"
    "4. To simplify accounting, we will split the bill evenly among all participants, regardless of how much you eat or drink. Expect to pay around 4000 yen, maybe more if some people decide to drink a lot.\n"
    "5. Depending on turnout or venue restrictions, we might need to change the location of the offkai.\n"
    "6. Please pay attention to this thread for day-of announcements before the offkai starts.\n"
)


# --- Helper for JSON serialization ---
class DataclassJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if is_dataclass(o):
            data = asdict(o)
            # Convert datetime objects to ISO strings
            for key, value in data.items():
                if isinstance(value, datetime):
                    data[key] = value.isoformat()
            return data
        return super().default(o)


# --- Event Data Handling ---


# Load raw event data from the JSON file
def _load_event_data() -> list[Event]:
    """
    Loads event data from JSON, converts to Event dataclasses,
    and handles missing or empty files.
    """
    settings = get_config()
    global EVENT_DATA_CACHE
    events_list = []
    file_path = settings["EVENTS_FILE"]

    try:
        # Check if file exists and is not empty before trying to load
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise FileNotFoundError  # Treat empty file like a missing one for initial creation

        with open(file_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)

        # Proceed with parsing if raw_data is a list (basic validation)
        if not isinstance(raw_data, list):
            logging.error(
                f"Invalid format in {file_path}: Expected a JSON list, got {type(raw_data)}. Loading empty list."
            )
            raw_data = []  # Treat as empty

        for event_dict in raw_data:
            # --- Compatibility & Type Conversion ---
            dt = None
            if "event_datetime" in event_dict and event_dict["event_datetime"]:
                try:
                    dt = datetime.fromisoformat(event_dict["event_datetime"])
                except (ValueError, TypeError):
                    logging.warning(
                        f"Could not parse ISO datetime '{event_dict.get('event_datetime')}' for {event_dict.get('event_name')}"
                    )
                    dt = None

            # ... (rest of the parsing logic for datetime fallback, drinks, etc.) ...
            drinks = event_dict.get("drinks", [])

            # Create Event instance
            try:
                event = Event(
                    event_name=event_dict.get("event_name", "Unknown Event"),
                    venue=event_dict.get("venue", "Unknown Venue"),
                    address=event_dict.get("address", "Unknown Address"),
                    google_maps_link=event_dict.get("google_maps_link", ""),
                    event_datetime=dt,
                    message=event_dict.get("message"),
                    channel_id=event_dict.get("channel_id"),
                    message_id=event_dict.get("message_id"),
                    open=event_dict.get("open", False),
                    archived=event_dict.get("archived", False),
                    drinks=drinks,
                )
                events_list.append(event)
            except TypeError as e:
                logging.error(f"Error creating Event object from dict {event_dict}: {e}")

    except FileNotFoundError:
        logging.warning(f"{file_path} not found or empty. Creating default empty file.")
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump([], file, indent=4)  # Create with empty list
            logging.info(f"Created empty events file at {file_path}")
        except OSError as e:
            logging.error(f"Could not create default events file at {file_path}: {e}")
        # Set cache and return empty list even if creation failed
        EVENT_DATA_CACHE = []
        return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {file_path}. File might be corrupted or invalid. Loading empty list.")
        EVENT_DATA_CACHE = []  # Set cache to empty
        return []
    except Exception as e:
        logging.exception(f"An unexpected error occurred loading event data from {file_path}: {e}")
        EVENT_DATA_CACHE = []  # Set cache to empty
        return []

    EVENT_DATA_CACHE = events_list  # Cache the loaded dataclasses
    return events_list


def load_event_data() -> list[Event]:
    """Returns cached event data or loads it if cache is empty."""
    if EVENT_DATA_CACHE is not None:  # Check if cache is populated (even if empty list)
        return EVENT_DATA_CACHE
    else:
        # Load data and populate cache (handles errors internally)
        return _load_event_data()


# Function to save the events data back to the JSON file
def save_event_data():
    """Saves the current state of EVENT_DATA_CACHE to the JSON file."""
    global EVENT_DATA_CACHE
    settings = get_config()
    if EVENT_DATA_CACHE is None:
        logging.error("Attempted to save event data before loading.")
        return  # Avoid saving None

    try:
        with open(settings["EVENTS_FILE"], "w", encoding="utf-8") as file:
            # Use the custom encoder to handle dataclasses and datetime
            # Dump the global cache directly
            json.dump(
                EVENT_DATA_CACHE,
                file,
                indent=4,
                cls=DataclassJSONEncoder,
                ensure_ascii=False,
            )
    except OSError as e:
        logging.error(f"Error writing event data to {settings['EVENTS_FILE']}: {e}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred saving event data: {e}")


def get_event(event_name: str) -> Event | None:
    """Gets a specific event by name from the cached data."""
    events = load_event_data()
    for event in events:
        if event_name.lower() == event.event_name.lower():
            return event
    return None


# --- Response Data Handling ---


def _load_responses() -> dict[str, list[Response]]:
    """
    Loads response data from JSON, converts to Response dataclasses,
    and handles missing or empty files.
    """
    global RESPONSE_DATA_CACHE
    settings = get_config()
    responses_dict: dict[str, list[Response]] = {}
    file_path = settings["RESPONSES_FILE"]

    try:
        # Check if file exists and is not empty before trying to load
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise FileNotFoundError  # Treat empty file like a missing one

        with open(file_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)

        # Proceed with parsing if raw_data is a dict (basic validation)
        if not isinstance(raw_data, dict):
            logging.error(
                f"Invalid format in {file_path}: Expected a JSON object (dict), got {type(raw_data)}. Loading empty responses."
            )
            raw_data = {}  # Treat as empty

        for event_name, response_list in raw_data.items():
            processed_responses = []
            # Ensure response_list is actually a list
            if not isinstance(response_list, list):
                logging.warning(
                    f"Invalid format for event '{event_name}' in {file_path}: Expected a list of responses, got {type(response_list)}. Skipping."
                )
                continue

            for resp_dict in response_list:
                # Ensure resp_dict is a dictionary
                if not isinstance(resp_dict, dict):
                    logging.warning(
                        f"Invalid response item for event '{event_name}' in {file_path}: Expected a dict, got {type(resp_dict)}. Skipping."
                    )
                    continue

                # --- Compatibility & Type Conversion ---
                ts = None
                if "timestamp" in resp_dict and resp_dict["timestamp"]:
                    try:
                        ts = datetime.fromisoformat(resp_dict["timestamp"])
                    except (ValueError, TypeError):
                        logging.warning(
                            f"Could not parse ISO timestamp '{resp_dict.get('timestamp')}' for {event_name}, user {resp_dict.get('user_id')}"
                        )
                        ts = None

                drinks = resp_dict.get("drinks", [])

                # Create Response instance
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
                        timestamp=ts if ts is not None else datetime.now(),  # Allow None if parsing failed
                        drinks=drinks,
                    )
                    processed_responses.append(response)
                except (TypeError, ValueError) as e:
                    logging.error(f"Error creating Response object for event {event_name} from dict {resp_dict}: {e}")

            responses_dict[event_name] = processed_responses

    except FileNotFoundError:
        logging.warning(f"{file_path} not found or empty. Creating default empty file.")
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump({}, file, indent=4)  # Create with empty object
            logging.info(f"Created empty responses file at {file_path}")
        except OSError as e:
            logging.error(f"Could not create default responses file at {file_path}: {e}")
        # Set cache and return empty dict even if creation failed
        RESPONSE_DATA_CACHE = {}
        return {}
    except json.JSONDecodeError:
        logging.error(
            f"Error decoding JSON from {file_path}. File might be corrupted or invalid. Loading empty responses."
        )
        RESPONSE_DATA_CACHE = {}  # Set cache to empty
        return {}
    except Exception as e:
        logging.exception(f"An unexpected error occurred loading response data from {file_path}: {e}")
        RESPONSE_DATA_CACHE = {}  # Set cache to empty
        return {}

    RESPONSE_DATA_CACHE = responses_dict  # Cache the loaded dataclasses
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
        logging.error("Attempted to save response data before loading.")
        return  # Avoid saving None

    try:
        with open(settings["RESPONSES_FILE"], "w", encoding="utf-8") as file:
            # Use the custom encoder to handle dataclasses and datetime
            # Dump the global cache directly
            json.dump(
                RESPONSE_DATA_CACHE,
                file,
                indent=4,
                cls=DataclassJSONEncoder,
                ensure_ascii=False,
            )
    except OSError as e:
        logging.error(f"Error writing response data to {settings['RESPONSES_FILE']}: {e}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred saving response data: {e}")


def get_responses(event_name: str) -> list[Response]:
    """Gets the list of Response objects for a specific event from cache."""
    responses = load_responses()  # Use the public cached loader
    # Return the list for the event, or an empty list if the event has no responses yet
    return responses.get(event_name, [])


def add_response(event_name: str, response: Response) -> bool:
    """
    Adds a response to the specified event.

    Args:
        event_name: The name of the event.
        response: The Response object to add.

    Returns:
        True if the response was added successfully, False if the user already responded.
    """
    all_responses = load_responses()  # Get current data (cached)
    event_responses = all_responses.get(event_name, [])

    # Check if user already exists
    if any(r.user_id == response.user_id for r in event_responses):
        logging.warning(f"User {response.user_id} already responded to event {event_name}.")
        return False  # Indicate failure (already exists)

    # Add the new response object
    event_responses.append(response)
    all_responses[event_name] = event_responses

    # Save the updated data
    save_responses()
    logging.info(f"Added response from user {response.user_id} to event {event_name}.")
    return True  # Indicate success


def remove_response(event_name: str, user_id: int) -> bool:
    """
    Removes a response for a given user from the specified event.

    Args:
        event_name: The name of the event.
        user_id: The ID of the user whose response should be removed.

    Returns:
        True if a response was removed, False otherwise.
    """
    all_responses = load_responses()  # Get current data (cached)
    event_responses = all_responses.get(event_name, [])

    initial_count = len(event_responses)
    # Filter out the response
    new_event_responses = [r for r in event_responses if r.user_id != user_id]

    if len(new_event_responses) < initial_count:
        all_responses[event_name] = new_event_responses
        # If the list becomes empty, consider removing the event key (optional)
        # if not new_event_responses:
        #     del all_responses[event_name]
        save_responses()
        logging.info(f"Removed response from user {user_id} for event {event_name}.")
        return True  # Indicate success
    else:
        logging.warning(f"No response found for user {user_id} in event {event_name} to remove.")
        return False  # Indicate failure (response not found)


# --- Message Creation ---


def create_event_message(event: Event) -> str:
    """Creates the full Discord message content for an event announcement."""
    # Use the format_details method from the Event dataclass
    event_details = event.format_details()

    return (
        f"{event_details}\n\n"  # Event details first
        f"{OFFKAI_MESSAGE}\n"  # Standard rules
        "Click the button below to confirm your attendance!"  # Call to action
    )
