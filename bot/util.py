import config
import discord
import json

EVENT_DATA_CACHE = None


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
    EVENT_DATA_CACHE = events

    with open(config.EVENTS_FILE, "w") as file:
        json.dump(events, file, indent=4)
