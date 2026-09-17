from discord import app_commands
from discord.ext import commands
import discord
import asyncio
from grokbot.utils import tail, split_log_lines
from grokbot.config import BOT_OWNER_ID, LOG_DIR


def is_authorized_user():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == BOT_OWNER_ID
    return app_commands.check(predicate)


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="checklog", description="Post the last 50 lines of the bot.log file")
    @app_commands.checks.cooldown(1, 30)
    @is_authorized_user()
    async def checklog(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            log_lines = await tail(str(LOG_DIR / "bot.log"), 50)
            if log_lines and isinstance(log_lines[0], str) and "Error" in log_lines[0]:
                await interaction.followup.send(log_lines[0], ephemeral=True)
                return
            chunks = split_log_lines(log_lines, 1960)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(f"Last 50 lines of bot.log:\n```\n{chunk}```", ephemeral=True)
                else:
                    await interaction.followup.send(f"```\n{chunk}```", ephemeral=True)
                await asyncio.sleep(0.5)
        except Exception as e:
            await interaction.followup.send(f"Error retrieving log file: {str(e)}", ephemeral=True)

    @app_commands.command(name="setreactuser", description="Set the user whose messages will be reacted with 🌈")
    @is_authorized_user()
    async def set_react_user(self, interaction: discord.Interaction, user: discord.User):
        async with self.bot.user_pref_lock:
            self.bot.react_user_id = user.id
            self.bot.user_pref_dirty = True
        await interaction.response.send_message(f"Set to react to messages from {user.mention}", ephemeral=True)

    @app_commands.command(name="disablereact", description="Disable the message reaction feature")
    @is_authorized_user()
    async def disable_react(self, interaction: discord.Interaction):
        async with self.bot.user_pref_lock:
            self.bot.react_user_id = None
            self.bot.user_pref_dirty = True
        await interaction.response.send_message("Disabled the message reaction feature", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))