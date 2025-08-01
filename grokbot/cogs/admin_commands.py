from discord import app_commands
from discord.ext import commands
import discord
import aiohttp
import asyncio
from grokbot.utils import tail, split_log_lines
from grokbot.config import BOT_OWNER_ID

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_authorized_user():
        async def predicate(interaction: discord.Interaction) -> bool:
            if interaction.user.id != BOT_OWNER_ID:
                await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
                return False
            return True
        return app_commands.check(predicate)

    @app_commands.command(name="checklog", description="Post the last 50 lines of the bot.log file")
    @app_commands.checks.cooldown(1, 30)
    @is_authorized_user()
    async def checklog(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            log_lines = await tail('/app/logs/bot.log', 50)
            if log_lines and isinstance(log_lines[0], str) and "Error" in log_lines[0]:
                await interaction.followup.send(log_lines[0])
                return
            chunks = split_log_lines(log_lines, 1960)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(f"Last 50 lines of bot.log:\n```\n{chunk}```")
                else:
                    await interaction.followup.send(f"```\n{chunk}```")
                await asyncio.sleep(0.5)
        except Exception as e:
            await interaction.followup.send(f"Error retrieving log file: {str(e)}")

    @app_commands.command(name="setreactuser", description="Set the user whose messages will be reacted with 🌈")
    @is_authorized_user()
    async def set_react_user(self, interaction: discord.Interaction, user: discord.User):
        self.bot.react_user_id = user.id
        self.bot.user_pref_dirty = True
        await interaction.response.send_message(f"Set to react to messages from {user.mention}", ephemeral=True)

    @app_commands.command(name="disablereact", description="Disable the message reaction feature")
    @is_authorized_user()
    async def disable_react(self, interaction: discord.Interaction):
        self.bot.react_user_id = None
        self.bot.user_pref_dirty = True
        await interaction.response.send_message("Disabled the message reaction feature", ephemeral=True)
    
    @app_commands.command(name="transcribe_audio", description="Transcribe an audio file using OpenAI. Supports mp3, wav, m4a, and ogg formats (up to 25MB).")
    @app_commands.describe(audio_file="The audio file to transcribe")
    @is_authorized_user()
    async def transcribe_audio(self, interaction: discord.Interaction, audio_file: discord.Attachment):
        if not audio_file.content_type.startswith("audio/"):
            await interaction.response.send_message("Please upload an audio file.", ephemeral=True)
            return
        if audio_file.size > 25 * 1024 * 1024:
            await interaction.response.send_message("The audio file is too large. Maximum size is 25MB.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            audio_data = await audio_file.read()
            headers = {
                "Authorization": f"Bearer {self.bot.OPENAI_API_KEY}",
            }
            form = aiohttp.FormData()
            form.add_field('file', audio_data, filename=audio_file.filename, content_type=audio_file.content_type)
            form.add_field('model', 'gpt-4o-transcribe')
            form.add_field('response_format', 'verbose_json')
            form.add_field('timestamp_granularities[]', 'segment')
            async with self.bot.session.post(self.bot.OPENAI_TRANSCRIPTION_URL, headers=headers, data=form, timeout=60) as response:
                response.raise_for_status()
                transcription_data = await response.json()
            segments = transcription_data.get("segments", [])
            if not segments:
                await interaction.followup.send("No transcription available.")
                return
            formatted_transcription = ""
            for segment in segments:
                start = segment["start"]
                end = segment["end"]
                text = segment["text"]
                formatted_transcription += f"[{start:.2f} - {end:.2f}] {text}\n"
            # Split the transcription if necessary
            max_length = 2000
            chunks = [formatted_transcription[i:i+max_length] for i in range(0, len(formatted_transcription), max_length)]
            await interaction.followup.send("Transcription of the audio file:\nNote: Speaker differentiation is not currently supported.")
            for chunk in chunks:
                await interaction.followup.send(chunk)
                await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Error in transcribe_audio command: {e}")
            await interaction.followup.send("Sorry, I couldn't transcribe the audio at this time.")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))