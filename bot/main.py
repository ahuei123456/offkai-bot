import config
import datetime
import discord
import logging

from datetime import datetime
from discord import app_commands
from discord.ext import commands
from interactions import load_and_update_events, InteractionView
from util import load_event_data, save_event_data

_log = logging.getLogger(__name__)


class OffkaiClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        for guild in config.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)


intents = discord.Intents.default()
intents.message_content = True

client = OffkaiClient(intents=intents)


@client.tree.command(
    name="create_offkai",
    description="Create a new offkai in the current channel.",
    guilds=config.guilds,
)
@app_commands.describe(
    event_name="The name of the event.",
    address="The addresss of the offkai location",
    date_time="The date and time of the event.",
)
async def create_offkai(
    interaction: discord.Interaction, event_name: str, address: str, date_time: str
):
    try:
        event_datetime = datetime.strptime(date_time, r"%Y-%m-%d %H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid date format. Use YYYY-MM-DD HH:MM.", ephemeral=True
        )
        return
    # Create a new thread for the event using the event_name in the channel
    channel = interaction.guild.get_channel(interaction.channel_id)
    # Create a thread in the channel
    thread = await channel.create_thread(
        name=event_name, type=discord.ChannelType.public_thread
    )  # Create a new channel thread
    event_details = (
        f"📅 **Event Name**: {event_name}\n"
        f"📍 **Address**: {address}\n"
        f"🕑 **Date and Time**: {event_datetime.strftime('%Y-%m-%d %H:%M')}\n\n"
        "Click the button below to confirm your attendance!"
    )
    view = InteractionView(event_name=event_name)
    message = await thread.send(event_details, view=view)
    events = load_event_data()
    events.append(
        {
            "event_name": event_name,
            "message": event_details,
            "channel_id": str(thread.id),
            "message_id": str(message.id),
        }
    )
    save_event_data(events)
    await interaction.response.send_message(
        f"✅ Event '{event_name}' created successfully in thread {thread.mention}."
    )


# Event to run when the client is ready
@client.event
async def on_ready():
    _log.info(f"Logged in as {client.user}")

    await client.tree.sync()

    # Load and update events from data/events.json
    await load_and_update_events(client)


client.run(config.DISCORD_TOKEN)
