import config
import json


# Load event data from the JSON file
def load_event_data():
    try:
        with open(config.EVENTS_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# Function to save the events data back to the JSON file
def save_event_data(events):
    with open(config.EVENTS_FILE, "w") as file:
        json.dump(events, file, indent=4)
