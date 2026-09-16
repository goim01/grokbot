import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import logging
import signal
import json
import aiofiles
import sys
import time
from grokbot.config import (
    DISCORD_TOKEN,
    MAX_TOKENS,
    WORKER_COUNT,
    BOT_OWNER_ID,
    API_TIMEOUT,
    XAI_API_KEY,
    OPENAI_API_KEY,
    XAI_MODEL,
    OPENAI_MODEL,
    XAI_CHAT_URL,
    OPENAI_CHAT_URL,
    OPENAI_VOICE_URL,
    USER_PREF_FILE,
    USER_PREF_WRITE_INTERVAL,
)


class GrokBot(commands.AutoShardedBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.session = None
        self.message_queue = asyncio.Queue()
        self.user_api_selection = {}
        self.react_user_id = None
        self.user_pref_lock = asyncio.Lock()
        self.user_pref_dirty = False
        self.user_pref_last_write = 0
        self.MAX_TOKENS = MAX_TOKENS
        self.WORKER_COUNT = WORKER_COUNT
        self.BOT_OWNER_ID = BOT_OWNER_ID
        self.API_TIMEOUT = API_TIMEOUT
        self.XAI_API_KEY = XAI_API_KEY
        self.OPENAI_API_KEY = OPENAI_API_KEY
        self.XAI_MODEL = XAI_MODEL
        self.OPENAI_MODEL = OPENAI_MODEL
        self.XAI_CHAT_URL = XAI_CHAT_URL
        self.OPENAI_CHAT_URL = OPENAI_CHAT_URL
        self.OPENAI_VOICE_URL = OPENAI_VOICE_URL
        self.test_guild_id = None  # Replace with your guild ID or None for global sync
        self.last_sync_time = 0
        self.sync_interval = 3600  # Sync every hour if needed
        self._bg_tasks = []
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self):
        # One-time startup: session, prefs, cogs, command sync, background tasks.
        # setup_hook runs once per process, unlike on_ready which can fire on reconnect.
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50))
            logging.info("Created new aiohttp ClientSession")

        await self.load_user_prefs()

        try:
            await self.load_extension("grokbot.cogs.message_handler")
            await self.load_extension("grokbot.cogs.ai_commands")
            await self.load_extension("grokbot.cogs.admin_commands")
            logging.info("All cogs loaded successfully")
        except Exception as e:
            logging.error(f"Failed to load cogs: {str(e)}")

        current_time = time.time()
        if current_time - self.last_sync_time > self.sync_interval:
            retries = 3
            for attempt in range(retries):
                try:
                    if self.test_guild_id:
                        guild = discord.Object(id=self.test_guild_id)
                        self.tree.copy_global_to(guild=guild)
                        synced = await self.tree.sync(guild=guild)
                        logging.info(f"Synced {len(synced)} commands to guild {self.test_guild_id}")
                    else:
                        synced = await self.tree.sync()
                        logging.info(f"Synced {len(synced)} commands globally")
                    self.last_sync_time = current_time
                    break
                except Exception as e:
                    if attempt < retries - 1:
                        logging.warning(f"Sync attempt {attempt + 1} failed: {str(e)}. Retrying...")
                        await asyncio.sleep(2 ** attempt)
                    else:
                        logging.error(f"Failed to sync commands after {retries} attempts: {str(e)}")

        self._bg_tasks.append(asyncio.create_task(self.save_user_prefs_periodically()))
        self._register_shutdown()

    async def on_ready(self):
        if self.user:
            logging.info(f"Logged in as {self.user.name} ({self.user.id})")
        else:
            logging.info("Logged in, but bot user is None somehow?")

    async def on_disconnect(self):
        logging.warning("Bot disconnected from Discord (WebSocket closed). Waiting for automatic reconnect...")

    async def on_resumed(self):
        logging.info("Bot connection to Discord resumed after disconnect.")

    async def on_shard_ready(self, shard_id):
        logging.info(f"Shard {shard_id} has connected")

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"This command is on cooldown. Try again in {error.retry_after:.1f}s."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "You are not authorized to use this command."
        else:
            logging.error(f"App command error in {getattr(interaction.command, 'name', '?')}: {error}")
            msg = "Something went wrong running that command."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            logging.error("Failed to send app command error message")

    def _register_shutdown(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass

    def _prefs_payload(self):
        return {
            "apis": {str(k): v for k, v in self.user_api_selection.items()},
            "react_user_id": self.react_user_id,
        }

    def _apply_prefs(self, prefs):
        # New format: {"apis": {...}, "react_user_id": ...}
        # Old format: {user_id: api_choice}
        if isinstance(prefs, dict) and "apis" in prefs:
            apis = prefs.get("apis") or {}
            react = prefs.get("react_user_id")
        else:
            apis = prefs if isinstance(prefs, dict) else {}
            react = None
        for user_id_str, api_choice in apis.items():
            try:
                user_id = int(user_id_str)
                self.user_api_selection[user_id] = api_choice
            except (ValueError, TypeError):
                continue
        if react is not None:
            try:
                self.react_user_id = int(react)
            except (ValueError, TypeError):
                self.react_user_id = None

    async def load_user_prefs(self):
        try:
            if USER_PREF_FILE.exists():
                async with aiofiles.open(USER_PREF_FILE, "r") as f:
                    content = await f.read()
                    if content:
                        self._apply_prefs(json.loads(content))
                        logging.info(
                            f"Loaded user preferences for {len(self.user_api_selection)} users "
                            f"(react_user_id={self.react_user_id})."
                        )
        except Exception as e:
            logging.error(f"Error loading user preferences: {str(e)}")

    async def _write_user_prefs(self, reason):
        try:
            USER_PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(USER_PREF_FILE, "w") as f:
                await f.write(json.dumps(self._prefs_payload()))
            self.user_pref_dirty = False
            self.user_pref_last_write = time.time()
            logging.info(f"User preferences saved {reason}.")
        except Exception as e:
            logging.error(f"Failed to save user preferences {reason}: {str(e)}")

    async def save_user_prefs_periodically(self):
        while True:
            await asyncio.sleep(USER_PREF_WRITE_INTERVAL)
            async with self.user_pref_lock:
                if self.user_pref_dirty:
                    await self._write_user_prefs("periodically")

    async def shutdown(self):
        async with self.user_pref_lock:
            if self.user_pref_dirty:
                await self._write_user_prefs("on shutdown")
        for task in self._bg_tasks:
            task.cancel()
        if self.session is not None and not self.session.closed:
            try:
                await self.session.close()
                logging.info("Closed aiohttp ClientSession")
            except Exception as e:
                logging.error(f"Failed to close aiohttp session: {str(e)}")
            finally:
                self.session = None
        try:
            await self.close()
        except Exception:
            pass


def main():
    if DISCORD_TOKEN is None:
        logging.error("DISCORD_TOKEN environment variable is not set. Exiting.")
        sys.exit("DISCORD_TOKEN environment variable is not set.")
    bot = GrokBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()