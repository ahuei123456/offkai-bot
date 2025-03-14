import config
import datetime
import discord
import logging

from datetime import datetime
from discord import app_commands
from interactions import load_and_update_events, update_event_message, OpenEvent
from util import (
    load_event_data,
    save_event_data,
    load_event_data_cached,
    get_event,
    get_responses,
)

_log = logging.getLogger(__name__)


OFFKAI_MESSAGE = (
    "Please take note of the following:\n"
    "1. We will not accomodate any allergies or dietary restrictions.\n"
    "2. Please register yourself and all your +1s by the deadline if you are planning on attending. Anyone who shows up uninvited or with uninvited guests can and will be turned away.\n"
    "3. Please show up on time. Restaurants tend to be packed after live events and we have been asked to give up table space in the past.\n"
    "4. To simplify accounting, we will split the bill evenly among all participants, regardless of how much you eat or drink. Expect to pay around 4000 yen, maybe more if some people decide to drink a lot.\n"
    "5. Depending on turnout or venue restrictions, we might need to change the location of the offkai.\n"
    "6. Please pay attention to this thread for day-of announcements before the offkai starts.\n"
)


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
    guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.",
    venue="The offkai venue.",
    address="The address of the offkai venue",
    google_maps_link="A link to the venue on Google Maps.",
    date_time="The date and time of the event.",
)
@app_commands.checks.has_role("Offkai Organizer")
async def create_offkai(
    interaction: discord.Interaction,
    event_name: str,
    venue: str,
    address: str,
    google_maps_link: str,
    date_time: str,
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
        f"🍽️ **Venue**: {venue}\n"
        f"📍 **Address**: {address}\n"
        f"🌎 **Google Maps Link**: {google_maps_link}\n"
        f"🕑 **Date and Time**: {event_datetime.strftime(r'%Y-%m-%d %H:%M')} JST\n\n"
        f"{OFFKAI_MESSAGE}\n"
        "Click the button below to confirm your attendance!"
    )
    view = OpenEvent(event_name=event_name)
    message = await thread.send(event_details, view=view)
    events = load_event_data()
    events.append(
        {
            "event_name": event_name,
            "message": event_details,
            "channel_id": str(thread.id),
            "message_id": str(message.id),
            "open": True,
            "archived": False,
        }
    )
    save_event_data(events)
    await interaction.response.send_message(
        f"# Offkai: {event_name}\n\n" f"More info in the thread {thread.mention}."
    )


@client.tree.command(
    name="close_offkai",
    description="Close responses for an offkai.",
    guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.",
)
@app_commands.checks.has_role("Offkai Organizer")
async def close_offkai(interaction: discord.Interaction, event_name: str):
    events = load_event_data()
    for event in events:
        if event["event_name"].lower() == event_name.lower():
            event["open"] = False
            await update_event_message(client, event)

    save_event_data(events)

    await interaction.response.send_message(
        f"✅ Responses for '{event_name}' have been closed."
    )


@client.tree.command(
    name="reopen_offkai",
    description="Reopen responses for an offkai.",
    guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.",
)
@app_commands.checks.has_role("Offkai Organizer")
async def reopen_offkai(interaction: discord.Interaction, event_name: str):
    events = load_event_data()
    for event in events:
        if event["event_name"].lower() == event_name.lower():
            event["open"] = True
            await update_event_message(client, event)

    save_event_data(events)

    await interaction.response.send_message(
        f"✅ Responses for '{event_name}' have been reopened."
    )


@client.tree.command(
    name="archive_offkai",
    description="Archive an offkai.",
    guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.",
)
@app_commands.checks.has_role("Offkai Organizer")
async def archive_offkai(interaction: discord.Interaction, event_name: str):
    events = load_event_data()
    for event in events:
        if event["event_name"].lower() == event_name.lower():
            event["archived"] = True

    save_event_data(events)

    await interaction.response.send_message(f"✅ '{event_name}' has been archived.")


@client.tree.command(
    name="broadcast",
    description="Sends a message to the offkai channel.",
    guilds=config.GUILDS,
)
@app_commands.describe(
    event_name="The name of the event.", message="Message to broadcast."
)
@app_commands.checks.has_role("Offkai Organizer")
async def broadcast(interaction: discord.Interaction, event_name: str, message: str):
    event = get_event(event_name)
    channel = client.get_channel(int(event["channel_id"]))
    try:
        await channel.send(f"{message}")
        await interaction.response.send_message(
            f"📣 Sent broadcast to channel {channel.mention}.", ephemeral=True
        )
    except AttributeError:
        await interaction.response.send_message(f"❌ Channel not found", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Unable to broadcast message.", ephemeral=True
        )


@client.tree.command(
    name="attendance",
    description="Gets a list of attendees.",
    guilds=config.GUILDS,
)
@app_commands.describe(event_name="The name of the event.")
@app_commands.checks.has_role("Offkai Organizer")
async def attendance(interaction: discord.Interaction, event_name: str):
    responses = get_responses(event_name)

    gen = lambda response: [
        f"{response["username"]}{f" +{i}" if i > 0 else ""}"
        for i in range(int(response["extra_people"]) + 1)
    ]

    attendees = [item for response in responses for item in gen(response)]

    await interaction.response.send_message(
        f"Total attendees: **{len(attendees)}**\n\n"
        f'{"\n".join(f"{i+1}. {v}" for i, v in enumerate(attendees))}',
        ephemeral=True,
    )


@close_offkai.error
@reopen_offkai.error
@create_offkai.error
@archive_offkai.error
@attendance.error
@broadcast.error
async def on_offkai_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(
            "❌ You do not have offkai organizing permissions.", ephemeral=True
        )
    else:
        await interaction.response.send_message(str(error), ephemeral=True)


@close_offkai.autocomplete("event_name")
@reopen_offkai.autocomplete("event_name")
@archive_offkai.autocomplete("event_name")
@attendance.autocomplete("event_name")
@broadcast.autocomplete("event_name")
async def offkai_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    events = load_event_data_cached()
    event_names = [event["event_name"] for event in events if not event["archived"]]
    return [
        app_commands.Choice(name=event_name, value=event_name)
        for event_name in event_names
        if current.lower() in event_name.lower()
    ]


# Event to run when the client is ready
@client.event
async def on_ready():
    _log.info(f"Logged in as {client.user}")

    await client.tree.sync()

    # Load and update events from data/events.json
    await load_and_update_events(client)


client.run(config.DISCORD_TOKEN)
