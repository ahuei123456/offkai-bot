"""Private organizer draft UI; publication uses the normal event creation path."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord
from discord import ui

MAX_PAYMENT_METHODS = 25
NO_SHOW_POLICY = "No-show payments are not refunded."
_log = logging.getLogger(__name__)


@dataclass
class PublicationState:
    resources_may_exist: bool = False


class ActionSelect(ui.Select):
    handler: Callable[[discord.Interaction], Awaitable[None]] | None = None

    async def callback(self, interaction: discord.Interaction):
        if self.handler:
            await self.handler(interaction)


class InstructionModal(ui.Modal):
    def __init__(self, setup: "SignupSetup", method: str | None = None):
        super().__init__(title="Add payment method" if method is None else "Edit payment instructions")
        self.setup = setup
        self.method = method
        self.name_input: ui.TextInput | None = None
        if method is None:
            self.name_input = ui.TextInput(label="Payment method name", max_length=100, required=True)
            self.add_item(self.name_input)
        self.instructions = ui.TextInput(
            label="Your payment instructions",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
            default=setup.instructions.get(method, "") if method is not None else "",
        )
        self.add_item(self.instructions)
        self.jp_payment_info = ui.TextInput(
            label="JP payment info",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False,
            default=setup.jp_instructions.get(method, "") if method is not None else "",
        )
        self.add_item(self.jp_payment_info)

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        value = self.instructions.value.strip()
        jp_value = self.jp_payment_info.value.strip()
        if not value or len(value) > 1000:
            await interaction.response.send_message("Payment instructions are required.", ephemeral=True)
            return
        if len(jp_value) > 1000:
            await interaction.response.send_message("JP payment info must be at most 1000 characters.", ephemeral=True)
            return
        method = self.method
        if self.name_input is not None:
            method = self.name_input.value.strip()
            if not method or len(method) > 100:
                await interaction.response.send_message(
                    "Enter a payment method name of 1–100 characters.", ephemeral=True
                )
                return
            if any(name.casefold() == method.casefold() for name in self.setup.instructions):
                await interaction.response.send_message(
                    "That payment method already exists. Edit its instructions instead.", ephemeral=True
                )
                return
            if len(self.setup.instructions) >= MAX_PAYMENT_METHODS:
                await interaction.response.send_message("You can add up to 25 payment methods.", ephemeral=True)
                return
            self.setup.methods.append(method)
            if "payment_method" not in self.setup.fields:
                self.setup.fields.append("payment_method")
        assert method is not None
        self.setup.instructions[method] = value
        if jp_value:
            self.setup.jp_instructions[method] = jp_value
        else:
            self.setup.jp_instructions.pop(method, None)
        self.setup.refresh_selects()
        await interaction.response.edit_message(view=self.setup)


class SignupSetup(ui.View):
    def __init__(
        self,
        owner_id: int,
        drinks: list[str],
        create: Callable[[dict | None, discord.Interaction, PublicationState], Awaitable[None]],
    ):
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.create = create
        self.fields = ["preferred_name", "guests", "no_show"] + (["drinks"] if drinks else [])
        self.methods: list[str] = []
        self.instructions: dict[str, str] = {}
        self.jp_instructions: dict[str, str] = {}
        self.finished = False
        self.publishing = False
        self.publication = PublicationState()
        self.presets = [
            ("preferred_name", "Preferred name"),
            ("guests", "Guest count and names"),
            ("payment_method", "Payment method"),
            ("no_show", "No-show / no-refund agreement"),
        ]
        if drinks:
            self.presets.append(("drinks", "Drinks"))
        self.refresh_selects()

    def refresh_selects(self):
        for child in self.children:
            if isinstance(child, ActionSelect):
                self.remove_item(child)
        self.add_payment_method.disabled = len(self.instructions) >= MAX_PAYMENT_METHODS
        fields = ActionSelect(
            placeholder="Enabled preset fields",
            min_values=0,
            max_values=len(self.presets),
            options=[
                discord.SelectOption(label=label, value=value, default=value in self.fields)
                for value, label in self.presets
            ],
            row=0,
        )

        async def choose_fields(interaction: discord.Interaction):
            self.fields = fields.values.copy()
            self.refresh_selects()
            await interaction.response.edit_message(view=self)

        fields.handler = choose_fields
        self.add_item(fields)
        if not self.instructions:
            return
        methods = ActionSelect(
            placeholder="Enabled payment methods",
            min_values=0,
            max_values=len(self.instructions),
            options=[discord.SelectOption(label=m, default=m in self.methods) for m in self.instructions],
            row=1,
        )

        async def choose_methods(interaction: discord.Interaction):
            self.methods = methods.values.copy()
            self.refresh_selects()
            await interaction.response.edit_message(view=self)

        methods.handler = choose_methods
        self.add_item(methods)
        editor = ActionSelect(
            placeholder="Edit instructions for a method",
            row=2,
            options=[discord.SelectOption(label=m) for m in self.instructions],
        )

        async def edit(interaction: discord.Interaction):
            await interaction.response.send_modal(InstructionModal(self, editor.values[0]))

        editor.handler = edit
        self.add_item(editor)

    @ui.button(label="Add payment method", row=3)
    async def add_payment_method(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(InstructionModal(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        organizer = isinstance(interaction.user, discord.Member) and any(
            role.name == "Offkai Organizer" for role in interaction.user.roles
        )
        if interaction.user.id == self.owner_id and organizer and not self.finished and not self.publishing:
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
        config = {"fields": self.fields.copy(), "payment_methods": {m: self.instructions[m] for m in enabled}}
        jp = {m: self.jp_instructions[m] for m in enabled if self.jp_instructions.get(m)}
        if jp:
            config["payment_instructions_jp"] = jp
        return config

    @ui.button(label="Preview", row=3)
    async def preview(self, interaction: discord.Interaction, button: ui.Button):
        try:
            config = self.configuration()
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        # Send each method separately so the preview stays within Discord's message limits.
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
            jp = config.get("payment_instructions_jp", {}).get(method, "")
            description = instructions + (f"\n\nJP payment info:\n{jp}" if jp else "")
            await interaction.followup.send(embed=discord.Embed(title=method, description=description), ephemeral=True)

    @ui.button(label="Create", style=discord.ButtonStyle.success, row=3)
    async def publish(self, interaction: discord.Interaction, button: ui.Button):
        try:
            config = self.configuration()
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        if self.publishing or self.finished:
            await interaction.response.send_message("This draft is already publishing or finished.", ephemeral=True)
            return
        self.publishing = True
        try:
            await self.create(config, interaction, self.publication)
        except Exception:
            _log.exception("Custom event publication failed")
            if self.publication.resources_may_exist:
                self.finished = True
                self.stop()
                message = "Publication may have created an event or thread. Check it before starting another draft."
            else:
                message = (
                    "Creation failed before any resources were created. Your draft is saved; you can retry Create."
                )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        else:
            self.finished = True
            self.stop()
        finally:
            self.publishing = False

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.finished = True
        await interaction.response.edit_message(content="Draft cancelled. No event was created.", view=None)
        self.stop()
