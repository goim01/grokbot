import asyncio
import discord
from discord import app_commands
import json
import os
import aiohttp
import logging
from datetime import datetime
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/bot.log'),
        logging.StreamHandler()
    ]
)

# Suppress specific Discord connection closed errors on console
class DiscordFilter(logging.Filter):
    def filter(self, record):
        return not (record.levelname == 'WARNING' and 'ConnectionClosed' in record.msg)
logging.getLogger('discord').addFilter(DiscordFilter())

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    logging.error("DISCORD_TOKEN environment variable is not set.")
    sys.exit(1)
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 5000))
WORKER_COUNT = int(os.getenv('WORKER_COUNT', 5))
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID', 248083498433380352))
API_TIMEOUT = int(os.getenv('API_TIMEOUT', 60))
USER_PREF_FILE = '/app/user_prefs/user_preferences.json'
USER_PREF_WRITE_INTERVAL = 10

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
bot.tree = app_commands.CommandTree(bot)

# Global variables
message_queue = asyncio.Queue()
user_api_selection = {}
react_user_id = None
user_pref_lock = asyncio.Lock()
user_pref_dirty = False

# Tool definitions
tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Perform a web search to get up-to-date information or additional context",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to perform"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

async def load_preferences():
    global user_api_selection, react_user_id
    try:
        with open(USER_PREF_FILE, 'r') as f:
            data = json.load(f)
            user_api_selection = data.get("user_api_selection", {})
            bot_settings = data.get("bot_settings", {})
            react_user_id = bot_settings.get("react_user_id", None)
    except FileNotFoundError:
        user_api_selection = {}
        react_user_id = None
    except json.JSONDecodeError:
        logging.error("Error decoding JSON in preferences file.")
        user_api_selection = {}
        react_user_id = None

async def save_preferences():
    global user_pref_dirty
    async with user_pref_lock:
        data = {
            "user_api_selection": user_api_selection,
            "bot_settings": {"react_user_id": react_user_id}
        }
        try:
            with open(USER_PREF_FILE, 'w') as f:
                json.dump(data, f, indent=4)
            user_pref_dirty = False
        except Exception as e:
            logging.error(f"Error saving preferences: {e}")

async def periodic_save():
    global user_pref_dirty
    while True:
        if user_pref_dirty:
            await save_preferences()
        await asyncio.sleep(USER_PREF_WRITE_INTERVAL)

async def send_api_request(context, api_type, image_data=None):
    # Placeholder for API request logic
    pass  # Implement as per existing bot logic

async def handle_message(message):
    # Placeholder for message handling logic
    pass  # Implement as per existing bot logic

async def worker():
    while True:
        message = await message_queue.get()
        try:
            await handle_message(message)
        except Exception as e:
            logging.error(f"Error processing message {message.id}: {e}")
            try:
                await message.channel.send("An error occurred while processing your request.")
            except discord.Forbidden:
                logging.warning(f"Cannot send error message to channel {message.channel}")
        finally:
            message_queue.task_done()

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user}')
    await load_preferences()
    for _ in range(WORKER_COUNT):
        asyncio.create_task(worker())
    asyncio.create_task(periodic_save())
    try:
        await bot.tree.sync()
        logging.info("Slash commands synced.")
    except Exception as e:
        logging.error(f"Error syncing slash commands: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # React to messages from the specified user
    if react_user_id is not None and message.author.id == react_user_id:
        try:
            await message.add_reaction("🌈")
        except discord.Forbidden:
            logging.warning(f"Cannot react to message in {message.channel}")
        except discord.HTTPException:
            logging.error(f"Error reacting to message {message.id}")

    # Existing message handling
    if bot.user in message.mentions:
        await message_queue.put(message)

@bot.tree.command(name="selectapi", description="Select which AI API to use")
async def select_api(interaction: discord.Interaction, api: str):
    # Placeholder for existing command
    pass  # Implement as per existing bot logic

@bot.tree.command(name="airoast", description="Get roasted by the AI")
async def ai_roast(interaction: discord.Interaction, user: discord.User):
    # Placeholder for existing command
    pass  # Implement as per existing bot logic

@bot.tree.command(name="aimotivate", description="Get motivated by the AI")
async def ai_motivate(interaction: discord.Interaction, user: discord.User):
    # Placeholder for existing command
    pass  # Implement as per existing bot logic

@bot.tree.command(name="aitts", description="Generate text-to-speech with AI")
async def ai_tts(interaction: discord.Interaction, text: str):
    # Placeholder for existing command
    pass  # Implement as per existing bot logic

@bot.tree.command(name="checklog", description="Check the bot's logs (owner only)")
async def check_log(interaction: discord.Interaction):
    # Placeholder for existing command
    pass  # Implement as per existing bot logic

@bot.tree.command(name="setreactuser", description="Set the user whose messages will be reacted with :rainbow_flag:")
async def set_react_user(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this command.")
        return
    global react_user_id, user_pref_dirty
    react_user_id = user.id
    user_pref_dirty = True
    await save_preferences()
    await interaction.response.send_message(f"Set to react to messages from {user.mention}")

@bot.tree.command(name="disablereact", description="Disable the message reaction feature")
async def disable_react(interaction: discord.Interaction):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this command.")
        return
    global react_user_id, user_pref_dirty
    react_user_id = None
    user_pref_dirty = True
    await save_preferences()
    await interaction.response.send_message("Disabled the message reaction feature")

def handle_shutdown(loop):
    tasks = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(save_preferences())
    loop.run_until_complete(bot.http.session.close())
    loop.close()

def main():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: handle_shutdown(loop))
    try:
        loop.run_until_complete(bot.start(DISCORD_TOKEN))
    except KeyboardInterrupt:
        logging.info("Received shutdown signal.")
        handle_shutdown(loop)
    except Exception as e:
        logging.error(f"Bot crashed: {e}")
        handle_shutdown(loop)

if __name__ == "__main__":
    main()