"""Private organizer draft UI; publication uses the normal event creation path."""

from collections.abc import Awaitable, Callable

import discord
from discord import ui

PAYMENT_METHODS = ("PayPay", "Wise/Revolut", "PayID", "PayNow", "GCash", "PayPal", "Interac")
NO_SHOW_POLICY = "No-show payments are not refunded."


class ActionSelect(ui.Select):
    handler: Callable[[discord.Interaction], Awaitable[None]] | None = None

    async def callback(self, interaction: discord.Interaction):
        if self.handler:
            await self.handler(interaction)


class InstructionModal(ui.Modal):
    def __init__(self, setup: "SignupSetup", method: str):
        super().__init__(title=f"Instructions: {method}")
        self.setup = setup
        self.method = method
        self.instructions = ui.TextInput(
            label="Your payment instructions",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
            default=setup.instructions.get(method, ""),
        )
        self.add_item(self.instructions)

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        value = self.instructions.value.strip()
        if not value or len(value) > 1000:
            await interaction.response.send_message("Payment instructions are required.", ephemeral=True)
            return
        self.setup.instructions[self.method] = value
        await interaction.response.send_message(f"Saved instructions for {self.method}.", ephemeral=True)


class SignupSetup(ui.View):
    def __init__(
        self,
        owner_id: int,
        drinks: list[str],
        create: Callable[[dict | None, discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.create = create
        self.fields = ["preferred_name", "guests", "no_show"] + (["drinks"] if drinks else [])
        self.methods: list[str] = []
        self.instructions: dict[str, str] = {}
        self.finished = False
        presets = [
            ("preferred_name", "Preferred name"),
            ("guests", "Guest count and names"),
            ("payment_method", "Payment method"),
            ("no_show", "No-show / no-refund agreement"),
        ]
        if drinks:
            presets.append(("drinks", "Drinks"))
        fields = ActionSelect(
            placeholder="Enabled preset fields",
            min_values=0,
            max_values=len(presets),
            options=[
                discord.SelectOption(label=label, value=value, default=value in self.fields) for value, label in presets
            ],
            row=0,
        )

        async def choose_fields(interaction: discord.Interaction):
            self.fields = fields.values.copy()
            await interaction.response.defer()

        fields.handler = choose_fields
        self.add_item(fields)
        methods = ActionSelect(
            placeholder="Enabled payment methods",
            min_values=0,
            max_values=len(PAYMENT_METHODS),
            options=[discord.SelectOption(label=m) for m in PAYMENT_METHODS],
            row=1,
        )

        async def choose_methods(interaction: discord.Interaction):
            self.methods = methods.values.copy()
            await interaction.response.defer()

        methods.handler = choose_methods
        self.add_item(methods)
        editor = ActionSelect(
            placeholder="Edit instructions for a method",
            row=2,
            options=[discord.SelectOption(label=m) for m in PAYMENT_METHODS],
        )

        async def edit(interaction: discord.Interaction):
            await interaction.response.send_modal(InstructionModal(self, editor.values[0]))

        editor.handler = edit
        self.add_item(editor)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        organizer = isinstance(interaction.user, discord.Member) and any(
            role.name == "Offkai Organizer" for role in interaction.user.roles
        )
        if interaction.user.id == self.owner_id and organizer and not self.finished:
            return True
        await interaction.response.send_message(
            "This draft is unavailable or belongs to another organizer.", ephemeral=True
        )
        return False

    def configuration(self) -> dict:
        enabled = self.methods if "payment_method" in self.fields else []
        if "payment_method" in self.fields and not enabled:
            raise ValueError("Enable at least one payment method.")
        if any(not self.instructions.get(method) for method in enabled):
            raise ValueError("Enter instructions for every enabled payment method.")
        return {"fields": self.fields.copy(), "payment_methods": {m: self.instructions[m] for m in enabled}}

    @ui.button(label="Preview", row=3)
    async def preview(self, interaction: discord.Interaction, button: ui.Button):
        try:
            config = self.configuration()
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        # Each method stays within one Discord embed field; seven methods can exceed a text message.
        embeds = [
            discord.Embed(
                title="Signup preview",
                description="Fields: "
                + ", ".join(config["fields"])
                + "\nBehavior and on-time arrival: required Yes"
                + ("\n" + NO_SHOW_POLICY if "no_show" in self.fields else ""),
            )
        ]
        await interaction.response.send_message(embed=embeds[0], ephemeral=True)
        for method, instructions in config["payment_methods"].items():
            await interaction.followup.send(embed=discord.Embed(title=method, description=instructions), ephemeral=True)

    @ui.button(label="Create", style=discord.ButtonStyle.success, row=3)
    async def publish(self, interaction: discord.Interaction, button: ui.Button):
        try:
            config = self.configuration()
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        self.finished = True
        await self.create(config, interaction)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.finished = True
        await interaction.response.edit_message(content="Draft cancelled. No event was created.", view=None)
        self.stop()
