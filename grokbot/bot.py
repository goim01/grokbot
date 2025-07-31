import discord
from discord.ext import commands
import asyncio
import logging
import signal
import json
import aiofiles
import sys
from grokbot.config import *
from grokbot.utils import *
from grokbot.api import *

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
        # Replace with your guild ID for testing
        self.test_guild_id = None  # e.g., 123456789012345678

    async def on_ready(self):
        if self.user:
            logging.info(f"Logged in as {self.user.name} ({self.user.id})")
        else:
            logging.info("Logged in, but bot user is None somehow?")
        try:
            if USER_PREF_FILE.exists():
                async with aiofiles.open(USER_PREF_FILE, 'r') as f:
                    content = await f.read()
                    if content:
                        prefs = json.loads(content)
                        for user_id_str, api_choice in prefs.items():
                            try:
                                user_id = int(user_id_str)
                                self.user_api_selection[user_id] = api_choice
                            except ValueError:
                                continue
                        logging.info(f"Loaded user preferences for {len(self.user_api_selection)} users.")
        except Exception as e:
            logging.error(f"Error loading user preferences: {str(e)}")

        if self.session is None:
            self.session = aiohttp.ClientSession()
            logging.info("Created new aiohttp ClientSession")

        # Load cogs
        try:
            await self.load_extension("grokbot.cogs.message_handler")
            await self.load_extension("grokbot.cogs.ai_commands")
            await self.load_extension("grokbot.cogs.admin_commands")
            logging.info("All cogs loaded successfully")
        except Exception as e:
            logging.error(f"Failed to load cogs: {str(e)}")

        # Sync commands
        try:
            if self.test_guild_id:
                guild = discord.Object(id=self.test_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logging.info(f"Synced {len(synced)} commands to guild {self.test_guild_id}")
            else:
                synced = await self.tree.sync()
                logging.info(f"Synced {len(synced)} commands globally")
        except Exception as e:
            logging.error(f"Failed to sync commands: {str(e)}")

        self.loop.create_task(self.save_user_prefs_periodically())
        def _register_shutdown():
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
                except NotImplementedError:
                    pass
        _register_shutdown()

    async def on_disconnect(self):
        logging.warning("Bot disconnected from Discord (WebSocket closed). Waiting for automatic reconnect...")

    async def on_resumed(self):
        logging.info("Bot connection to Discord resumed after disconnect.")

    async def on_shard_ready(self, shard_id):
        logging.info(f"Shard {shard_id} has connected")

    async def save_user_prefs_periodically(self):
        while True:
            await asyncio.sleep(USER_PREF_WRITE_INTERVAL)
            async with self.user_pref_lock:
                if self.user_pref_dirty:
                    try:
                        async with aiofiles.open(USER_PREF_FILE, 'w') as f:
                            prefs_to_save = {str(k): v for k, v in self.user_api_selection.items()}
                            await f.write(json.dumps(prefs_to_save))
                        self.user_pref_dirty = False
                        self.user_pref_last_write = time.time()
                        logging.info("User preferences saved periodically.")
                    except Exception as e:
                        logging.error(f"Failed to save user preferences periodically: {str(e)}")

    async def shutdown(self):
        async with self.user_pref_lock:
            if self.user_pref_dirty:
                try:
                    async with aiofiles.open(USER_PREF_FILE, 'w') as f:
                        prefs_to_save = {str(k): v for k, v in self.user_api_selection.items()}
                        await f.write(json.dumps(prefs_to_save))
                    self.user_pref_dirty = False
                    self.user_pref_last_write = time.time()
                    logging.info("User preferences saved on shutdown.")
                except Exception as e:
                    logging.error(f"Failed to save user preferences on shutdown: {str(e)}")
        if self.session is not None and not self.session.closed:
            try:
                await self.session.close()
                logging.info("Closed aiohttp ClientSession")
            except Exception as e:
                logging.error(f"Failed to close aiohttp session: {str(e)}")
            finally:
                self.session = None

if __name__ == "__main__":
    if DISCORD_TOKEN is None:
        logging.error("DISCORD_TOKEN environment variable is not set. Exiting.")
        sys.exit("DISCORD_TOKEN environment variable is not set.")
    bot = GrokBot()
    bot.run(DISCORD_TOKEN)