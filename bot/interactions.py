import config
import discord
import json
from discord import ui
from datetime import datetime, UTC
from util import (
    save_event_data,
    load_event_data,
    load_event_data_cached,
    load_response_data,
    load_response_data_cached,
    save_response_data,
)


# Class to handle the modal for event attendance
class GatheringModal(ui.Modal):
    def __init__(
        self,
        *,
        title="Event Attendance Confirmation",
        timeout=None,
        custom_id="",
        event_name="Default Event",
    ):
        super().__init__(title=title, timeout=timeout, custom_id=custom_id)
        self.event_name = event_name

    extra_people = ui.TextInput(
        label="🧑 I am bringing extra people (0-5)",
        placeholder="Enter a number between 0-5",
        required=True,
        max_length=1,
    )
    behave_checkbox = ui.TextInput(
        label="✔ I will behave", placeholder="You must type 'Yes'", required=True
    )
    arrival_checkbox = ui.TextInput(
        label="✔ I will arrive 5 minutes early",
        placeholder="You must type 'Yes'",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Validate the extra people input
        if not self.extra_people.value.isdigit() or not (
            0 <= int(self.extra_people.value) <= 5
        ):
            await interaction.response.send_message(
                "❌ Please enter a number between 0 and 5.", ephemeral=True
            )
            return

        if (
            self.behave_checkbox.value.lower() != "yes"
            or self.arrival_checkbox.value.lower() != "yes"
        ):
            await interaction.response.send_message(
                "❌ You must type 'Yes' in the required fields.", ephemeral=True
            )
            return

        # Prepare the response data to log
        response_data = {
            "user_id": str(interaction.user.id),  # Store the user ID as a string
            "username": interaction.user.name,
            "extra_people": self.extra_people.value,
            "behavior_confirmed": self.behave_checkbox.value,
            "arrival_confirmed": self.arrival_checkbox.value,
            "event_name": self.event_name,  # Store the event name
            "timestamp": datetime.now(
                UTC
            ).isoformat(),  # Save the timestamp in ISO format
        }

        data = load_response_data()

        # Append the new response to the list
        try:
            # Check if the user_id already exists in the responses for the current event
            existing_responses = data[self.event_name]

            # Check if the user_id exists in the current event responses
            if any(
                response["user_id"] == str(interaction.user.id)
                for response in existing_responses
            ):
                await interaction.response.send_message(
                    "❌ You have already submitted a response for this event.",
                    ephemeral=True,
                )
                return  # Prevent further processing if the user already submitted a response

            # If the user hasn't submitted yet, append the new response
            existing_responses.append(response_data)
            data[self.event_name] = (
                existing_responses  # Save the updated responses back to the event
            )
        except KeyError:
            data[self.event_name] = [response_data]

        save_response_data(data)

        # Confirm submission with a response message
        await interaction.response.send_message(
            f"✅ You confirmed attendance!\n"
            f"👥 Extra people: {self.extra_people.value}\n"
            f"✔ Behavior confirmed: {self.behave_checkbox.value}\n"
            f"✔ Arrival confirmed: {self.arrival_checkbox.value}",
            ephemeral=True,
        )
        await interaction.channel.add_user(interaction.user)


class EventView(ui.View):
    def __init__(self, event_name: str):
        super().__init__(timeout=None)
        self.event_name = event_name

    @discord.ui.button(
        label="Attendance Count", style=discord.ButtonStyle.primary, row=1
    )
    async def count(self, interaction: discord.Interaction, button: discord.ui.Button):
        responses = load_response_data_cached()

        try:
            num = sum(
                1 + int(response["extra_people"])
                for response in responses[self.event_name]
            )
        except KeyError:
            num = 0

        await interaction.response.send_message(
            f"📝 Registration count: {num}", ephemeral=True
        )


# Class to create a button that opens the modal
class OpenEvent(EventView):
    @discord.ui.button(
        label="Confirm Attendance", style=discord.ButtonStyle.primary, row=0
    )
    async def respond(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(
            GatheringModal(title=self.event_name, event_name=self.event_name)
        )


# Class to create a button that opens the modal
class ClosedEvent(EventView):
    @discord.ui.button(
        label="Responses Closed",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        row=0,
    )
    async def respond(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(
            GatheringModal(title=self.event_name, event_name=self.event_name)
        )


# Function to send the event message with button interaction
async def send_event_message(channel: discord.Thread, event):
    if event["open"]:
        view = OpenEvent(event["event_name"])
    else:
        view = ClosedEvent(event["event_name"])
    message = await channel.send(event["message"], view=view)
    event["message_id"] = str(message.id)  # Save the message ID back to event data
    save_event_data(load_event_data())  # Save the updated event data


# Function to update the event message if the message ID exists
async def update_event_message(client: discord.Client, event):
    channel = client.get_channel(int(event["channel_id"]))
    if channel:
        try:
            message = await channel.fetch_message(int(event["message_id"]))
            if event["open"]:
                view = OpenEvent(event["event_name"])
            else:
                view = ClosedEvent(event["event_name"])
            await message.edit(content=event["message"], view=view)
        except discord.errors.NotFound:
            print(
                f"Message with ID {event['message_id']} not found, sending a new message."
            )
            await send_event_message(channel, event)


# Function to load events on bot startup
async def load_and_update_events(client: discord.Client):
    events = load_event_data()  # Load event data from file
    for event in events:
        if "message_id" in event:  # If message ID exists, update the message
            await update_event_message(client, event)
        else:  # If message ID does not exist, send a message and save it
            channel = client.get_channel(int(event["channel_id"]))
            if channel:
                await send_event_message(channel, event)  # Send the message

                save_event_data(events)
