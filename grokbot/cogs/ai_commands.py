from discord import app_commands
from discord.ext import commands
import discord
import datetime
import logging
import io
from grokbot.api import send_api_request
from grokbot.config import BOT_OWNER_ID

class AICommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="selectapi", description="Select the AI API (xAI or OpenAI)")
    @app_commands.describe(api="API to use (xAI or OpenAI)")
    @app_commands.choices(api=[
        app_commands.Choice(name="xAI", value="xai"),
        app_commands.Choice(name="OpenAI", value="openai")
    ])
    async def selectapi(self, interaction: discord.Interaction, api: app_commands.Choice[str]):
        if api.value == "xai" and not self.bot.XAI_API_KEY:
            await interaction.response.send_message("xAI API is not configured.", ephemeral=True)
            return
        elif api.value == "openai" and not self.bot.OPENAI_API_KEY:
            await interaction.response.send_message("OpenAI API is not configured.", ephemeral=True)
            return

        async with self.bot.user_pref_lock:
            self.bot.user_api_selection[interaction.user.id] = api.value
            self.bot.user_pref_dirty = True

        await interaction.response.send_message(f"Selected {api.name} for your questions.", ephemeral=True)

    @app_commands.command(name="airoast", description="Roast a user in a funny way")
    @app_commands.describe(member="The user to roast", context="Optional additional context about the user")
    @app_commands.checks.cooldown(1, 10)
    async def airoast(self, interaction: discord.Interaction, member: discord.Member, context: str = None):
        await interaction.response.defer()
        try:
            display_name = member.global_name
            avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
            prompt = f"Roast this user in a funny way based on their nickname '{display_name}' and their avatar. Make it humorous and don't be afraid of offensive jokes since it's a roast between friends and should not be taken seriously."
            if context and context.strip():
                context = context.strip()[:500]
                prompt += f" Additional context: {context}"
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            messages = [
                {"role": "system", "content": f"The current date and time is {current_time}."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": avatar_url}}
                ]}
            ]
            payload = {
                "model": self.bot.OPENAI_MODEL,
                "messages": messages,
                "max_tokens": self.bot.MAX_TOKENS,
            }
            headers = {
                "Authorization": f"Bearer {self.bot.OPENAI_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "GrokBot/1.0"
            }
            response = await send_api_request(self.bot.session, self.bot.OPENAI_CHAT_URL, headers, payload, self.bot.API_TIMEOUT)
            answer = response["choices"][0]["message"]["content"]
            await interaction.followup.send(f"Roast for {member.mention}: {answer}")
        except Exception as e:
            logging.error(f"Error in airoast command: {e}")
            await interaction.followup.send("Sorry, I couldn't generate a roast at this time.")

    @app_commands.command(name="aimotivate", description="Give cheesy and over-the-top motivational advice to a user")
    @app_commands.describe(member="The user to motivate", context="Optional additional context about the user")
    @app_commands.checks.cooldown(1, 10)
    async def aimotivate(self, interaction: discord.Interaction, member: discord.Member, context: str = None):
        await interaction.response.defer()
        try:
            display_name = member.global_name
            avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
            prompt = f"Give this user, {display_name}, some extremely cheesy and over-the-top motivational advice based on their nickname and their avatar. Make it as exaggerated and uplifting as possible. Don't hold back on the enthusiasm!"
            if context:
                context = context.strip()[:500]
                prompt += f" Additional context: {context}"
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            messages = [
                {"role": "system", "content": f"The current date and time is {current_time}."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": avatar_url}}
                ]}
            ]
            payload = {
                "model": self.bot.OPENAI_MODEL,
                "messages": messages,
                "max_tokens": self.bot.MAX_TOKENS,
            }
            headers = {
                "Authorization": f"Bearer {self.bot.OPENAI_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "GrokBot/1.0"
            }
            response = await send_api_request(self.bot.session, self.bot.OPENAI_CHAT_URL, headers, payload, self.bot.API_TIMEOUT)
            answer = response["choices"][0]["message"]["content"]
            await interaction.followup.send(f"Motivational advice for {member.mention}: {answer}")
        except Exception as e:
            logging.error(f"Error in aimotivate command: {e}")
            await interaction.followup.send("Sorry, I couldn't generate motivational advice at this time.")

    @app_commands.command(name="aitts", description="Send a voice message using AI text-to-speech")
    @app_commands.describe(
        text="The text for the AI to say",
        voice="The voice to use for the speech",
        context="Optional additional context"
    )
    @app_commands.choices(voice=[
        app_commands.Choice(name="Alloy", value="alloy"),
        app_commands.Choice(name="Ash", value="ash"),
        app_commands.Choice(name="Ballad", value="ballad"),
        app_commands.Choice(name="Coral", value="coral"),
        app_commands.Choice(name="Echo", value="echo"),
        app_commands.Choice(name="Fable", value="fable"),
        app_commands.Choice(name="Nova", value="nova"),
        app_commands.Choice(name="Onyx", value="onyx"),
        app_commands.Choice(name="Sage", value="sage"),
        app_commands.Choice(name="Shimmer", value="shimmer")
    ])
    @app_commands.checks.cooldown(1, 10)
    async def aitts(self, interaction: discord.Interaction, text: str, voice: app_commands.Choice[str], context: str = None):
        await interaction.response.defer()
        try:
            text = text.strip()
            if len(text) > 4096:
                await interaction.followup.send("The text is too long. Please limit it to 4096 characters.")
                return
            payload = {
                "model": "gpt-4o-mini-tts",
                "input": text,
                "voice": voice.value
            }
            headers = {
                "Authorization": f"Bearer {self.bot.OPENAI_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "GrokBot/1.0"
            }
            async with self.bot.session.post(self.bot.OPENAI_VOICE_URL, headers=headers, json=payload) as response:
                response.raise_for_status()
                audio_data = await response.read()
            file_size = len(audio_data)
            if file_size > 8 * 1024 * 1024:
                await interaction.followup.send("The generated voice message is too large to send (over 8MB). Try shorter text.")
                return
            audio_file = io.BytesIO(audio_data)
            audio_file.name = f"voice_message_{voice.value}.mp3"
            text_preview = text[:1800] + "..." if len(text) > 1800 else text
            await interaction.followup.send(
                f"Here is your voice message (voice: {voice.name}):\nYour prompt: {text_preview}",
                file=discord.File(audio_file, filename=f"voice_message_{voice.value}.mp3")
            )
        except Exception as e:
            logging.error(f"Error in aitts command: {e}")
            await interaction.followup.send("Sorry, I couldn't generate the voice message at this time.")

def setup(bot):
    bot.add_cog(AICommands(bot))