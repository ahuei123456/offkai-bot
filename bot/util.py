import config
import discord
import json

EVENT_DATA_CACHE = None
RESPONSE_DATA_CACHE = None


# Load event data from the JSON file
def load_event_data():
    try:
        with open(config.EVENTS_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_event_data_cached():
    if EVENT_DATA_CACHE:
        return EVENT_DATA_CACHE
    else:
        return load_event_data()


# Function to save the events data back to the JSON file
def save_event_data(events):
    global EVENT_DATA_CACHE
    EVENT_DATA_CACHE = events

    with open(config.EVENTS_FILE, "w") as file:
        json.dump(events, file, indent=4)


def get_event(event_name: str):
    events = load_event_data_cached()

    for event in events:
        if event_name.lower() == event["event_name"].lower():
            return event

    return None


def replace_event(event_name: str, new_event):
    events = load_event_data_cached()

    events = [
        event if not event["event_name"].lower() == event_name.lower() else new_event
        for event in events
    ]

    save_event_data(events)


def load_response_data():
    try:
        with open(config.RESPONSES_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_response_data_cached():
    if RESPONSE_DATA_CACHE:
        return RESPONSE_DATA_CACHE
    else:
        return load_response_data()


def save_response_data(responses):
    global RESPONSE_DATA_CACHE
    RESPONSE_DATA_CACHE = responses

    with open(config.RESPONSES_FILE, "w") as file:
        json.dump(responses, file, indent=4)


def get_responses(event_name: str):
    responses = load_response_data_cached()

    return responses[event_name]
