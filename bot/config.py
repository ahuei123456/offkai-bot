import os
import discord
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEFAULT_CHANNEL_ID = int(os.getenv("DEFAULT_CHANNEL_ID"))
EVENTS_FILE = os.getenv("EVENTS_FILE")
RESPONSES_FILE = os.getenv("RESPONSES_FILE")

guilds = [discord.Object(id=171931647883608065)]