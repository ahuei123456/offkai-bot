import config
import discord
import json

from datetime import datetime

EVENT_DATA_CACHE = None
RESPONSE_DATA_CACHE = None


OFFKAI_MESSAGE = (
    "Please take note of the following:\n"
    "1. We will not accomodate any allergies or dietary restrictions.\n"
    "2. Please register yourself and all your +1s by the deadline if you are planning on attending. Anyone who shows up uninvited or with uninvited guests can and will be turned away.\n"
    "3. Please show up on time. Restaurants tend to be packed after live events and we have been asked to give up table space in the past.\n"
    "4. To simplify accounting, we will split the bill evenly among all participants, regardless of how much you eat or drink. Expect to pay around 4000 yen, maybe more if some people decide to drink a lot.\n"
    "5. Depending on turnout or venue restrictions, we might need to change the location of the offkai.\n"
    "6. Please pay attention to this thread for day-of announcements before the offkai starts.\n"
)


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


def create_event_message(
    event_name: str,
    venue: str,
    address: str,
    google_maps_link: str,
    event_datetime: datetime,
):
    return (
        f"📅 **Event Name**: {event_name}\n"
        f"🍽️ **Venue**: {venue}\n"
        f"📍 **Address**: {address}\n"
        f"🌎 **Google Maps Link**: {google_maps_link}\n"
        f"🕑 **Date and Time**: {event_datetime.strftime(r'%Y-%m-%d %H:%M')} JST\n\n"
        f"{OFFKAI_MESSAGE}\n"
        "Click the button below to confirm your attendance!"
    )
