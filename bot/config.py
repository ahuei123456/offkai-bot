import os
import discord
import json
from dotenv import load_dotenv


with open(f"config.json") as f:
    config = json.load(f)


DISCORD_TOKEN = config["DISCORD_TOKEN"]
DEFAULT_CHANNEL_ID = config["DEFAULT_CHANNEL_ID"]
EVENTS_FILE = config["EVENTS_FILE"]
RESPONSES_FILE = config["RESPONSES_FILE"]
GUILDS = [discord.Object(id=id) for id in config["GUILDS"]]
