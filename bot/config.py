import os
import discord
import json
from dotenv import load_dotenv


with open(f"config.json") as f:
    config = json.load(f)


DISCORD_TOKEN = config["DISCORD_TOKEN"]
EVENTS_FILE = config["EVENTS_FILE"]
RESPONSES_FILE = config["RESPONSES_FILE"]
GUILD_IDS = config["GUILDS"]
