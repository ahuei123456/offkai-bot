import discord
from discord import app_commands
from discord.ext import commands


class GeneralCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="hello", description="Says hello!")
    @app_commands.checks.has_role("Offkai Organizer")
    async def hello(self, interaction: discord.Interaction):
        """Says hello!"""
        # Opt in to the user ping past the client-wide AllowedMentions.none() default.
        await interaction.response.send_message(
            f"Hi, {interaction.user.mention}",
            allowed_mentions=discord.AllowedMentions(users=True),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
