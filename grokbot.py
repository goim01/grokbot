import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import logging
import traceback
import re
import os
import sys
import json
import aiofiles

# Load general environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 3000))

# xAI env variables
XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3-mini")
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"

# OpenAI env variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
USER_PREF_FILE = "/app/user_prefs/user_preferences.json"

# Set up logging to both file and console
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
log_dir = '/app/logs'
os.makedirs(log_dir, exist_ok=True)
file_handler = logging.FileHandler(os.path.join(log_dir, 'bot.log'))
console_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Set up Discord bot with command prefix and intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Message queue for handling concurrent questions
message_queue = asyncio.Queue()

# Store user API selections
user_api_selection = {}

@bot.event
async def on_ready():
    if bot.user:
        logging.info(f"Logged in as {bot.user.name}")
    else:
        logging.info("Logged in, but bot user is None somehow?")

    # Load user API preferences from file
    try:
        if os.path.exists(USER_PREF_FILE):
            async with aiofiles.open(USER_PREF_FILE, 'r') as f:
                content = await f.read()
                if content:
                    prefs = json.loads(content)
                    for user_id_str, api_choice in prefs.items():
                        try:
                            user_id = int(user_id_str)
                            user_api_selection[user_id] = api_choice
                        except ValueError:
                            continue
                    logging.info(f"Loaded user preferences for {len(user_api_selection)} users.")
    except FileNotFoundError:
        logging.info("User preferences file not found; starting with empty preferences.")
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error in preferences file: {str(e)}; starting with empty preferences.")
    except Exception as e:
        logging.error(f"Error loading user preferences: {str(e)}")

    # Sync slash commands on startup
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")

    bot.loop.create_task(process_message_queue())

# Slash command to select API (xAI or OpenAI)
@bot.tree.command(name="selectapi", description="Select the AI API (xAI or OpenAI)")
@app_commands.describe(api="API to use (xAI or OpenAI)")
@app_commands.choices(api=[
    app_commands.Choice(name="xAI", value="xai"),
    app_commands.Choice(name="OpenAI", value="openai")
])
async def selectapi(interaction: discord.Interaction, api: app_commands.Choice[str]):
    # Check API key configuration
    if api.value == "xai" and not XAI_API_KEY:
        await interaction.response.send_message("xAI API is not configured.", ephemeral=True)
        return
    elif api.value == "openai" and not OPENAI_API_KEY:
        await interaction.response.send_message("OpenAI API is not configured.", ephemeral=True)
        return

    # Update user preference and persist
    user_api_selection[interaction.user.id] = api.value
    try:
        async with aiofiles.open(USER_PREF_FILE, 'w') as f:
            prefs_to_save = {str(k): v for k, v in user_api_selection.items()}
            await f.write(json.dumps(prefs_to_save))
    except Exception as e:
        logging.error(f"Failed to save user preferences: {str(e)}")

    await interaction.response.send_message(f"Selected {api.name} for your questions.", ephemeral=True)

# Helper to split long messages for Discord

def split_message(text, max_length):
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_point = max_length
        search_range = max(0, max_length - 100)
        for i in range(min(max_length, len(text)), search_range, -1):
            if text[i - 1] in "\n.!?":
                split_point = i
                break
        else:
            for i in range(min(max_length, len(text)), search_range, -1):
                if text[i - 1] == " ":
                    split_point = i
                    break
        chunks.append(text[:split_point].rstrip())
        text = text[split_point:].lstrip()
    return [chunk for chunk in chunks if chunk]

# Background task that consumes message queue
async def process_message_queue():
    while True:
        try:
            message = await message_queue.get()
            await handle_message(message)
        except Exception as e:
            logging.error(f"Queue processing error: {str(e)}\n{traceback.format_exc()}")
        finally:
            message_queue.task_done()
        if message_queue.empty():
            await asyncio.sleep(1)

# Handle each tagged message with or without image
async def handle_message(message):
    raw_content = message.content
    question = raw_content

    # Remove mention of bot from message content
    if bot.user:
        question = re.sub(f"<@!?{bot.user.id}>", "", question).strip()

    bot_name = bot.user.name.lower() if bot.user and bot.user.name else None
    bot_nickname = message.guild.get_member(bot.user.id).nick.lower() if message.guild and message.guild.get_member(bot.user.id) and message.guild.get_member(bot.user.id).nick else None

    if bot_name:
        question = re.sub(f"@{re.escape(bot_name)}", "", question, flags=re.IGNORECASE).strip()
    if bot_nickname:
        question = re.sub(f"@{re.escape(bot_nickname)}", "", question, flags=re.IGNORECASE).strip()

    for user in message.mentions:
        if user != bot.user:
            display_name = user.display_name if message.guild and message.guild.get_member(user.id) else user.name
            question = re.sub(f"<@!?{user.id}>", display_name, question).strip()

    if not question:
        await message.channel.send(f"{message.author.mention} Please ask a question or use slash commands.")
        return

    original_content = None
    reply_image_url = None
    if message.reference:
        try:
            original_message = await message.channel.fetch_message(message.reference.message_id)
            if original_message:
                if original_message.content:
                    original_content = original_message.content
                for attachment in original_message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        reply_image_url = attachment.url
                        break
        except (discord.NotFound, discord.Forbidden):
            pass

    context = f"Original message: {original_content}\nUser question: {question}" if original_content else question

    mentions = [f"<@!{user.id}>" for user in message.mentions if user != bot.user]
    mention_text = " ".join(mentions) + " " if mentions else ""

    logging.info(f"Context sent to API: {context}")

    # Determine which API to use (default to xAI)
    selected_api = user_api_selection.get(message.author.id, "xai")
    logging.info(f"Selected API: {selected_api}")

    image_url = None
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            image_url = attachment.url
            break

    if not image_url:
        image_url = reply_image_url

    if selected_api == "xai":
        if not XAI_API_KEY:
            await message.channel.send(f"{message.author.mention} Sorry, the xAI API is not configured.")
            return
        if image_url:
            await message.channel.send(f"{message.author.mention} Sorry, image input is only supported with OpenAI at the moment.")
            return
        api_url = XAI_CHAT_URL
        api_key = XAI_API_KEY
        model = XAI_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot/1.0"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": context}],
            "stream": False,
            "max_tokens": MAX_TOKENS
        }
    else:
        if not OPENAI_API_KEY:
            await message.channel.send(f"{message.author.mention} Sorry, the OpenAI API is not configured.")
            return
        api_url = OPENAI_CHAT_URL
        api_key = OPENAI_API_KEY
        model = OPENAI_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        if image_url:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": context},
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]
                    }
                ],
                "max_tokens": MAX_TOKENS
            }
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": context}],
                "max_tokens": MAX_TOKENS
            }

    # Send request to AI API and stream response
    async with message.channel.typing():
        try:
            retries = 3
            response_data = None
            async with aiohttp.ClientSession() as session:
                for attempt in range(retries):
                    try:
                        async with session.post(api_url, headers=headers, json=payload, timeout=15) as response:
                            response.raise_for_status()
                            response_data = await response.json()
                            break
                    except aiohttp.ClientResponseError as e:
                        if e.status == 429 and attempt < retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        async with session.post(api_url, headers=headers, json=payload, timeout=15) as error_response:
                            error_details = await error_response.text()
                        logging.error(f"API error ({selected_api}): HTTP {e.status}: {error_details}")
                        await message.channel.send(f"{message.author.mention} Error from {selected_api.upper()}: HTTP {e.status}")
                        return
                    except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                        if attempt < retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        logging.error(f"Connection error ({selected_api}): {str(e)}")
                        await message.channel.send(f"{message.author.mention} Connection error with {selected_api.upper()}")
                        return
            if not response_data or "choices" not in response_data or not response_data["choices"]:
                logging.error(f"Invalid API response format ({selected_api}): {response_data}")
                await message.channel.send(f"{message.author.mention} Invalid response from {selected_api.upper()}")
                return
            answer = response_data["choices"][0]["message"]["content"]
            answer += f"\n(answered by {'xAI' if selected_api == 'xai' else 'OpenAI'})"
            max_length = 2000 - len(f"{message.author.mention} {mention_text}")
            chunks = split_message(answer, max_length)
            for i, chunk in enumerate(chunks):
                final_message = f"{message.author.mention} {mention_text} {chunk}" if i == 0 else chunk
                if final_message.strip():
                    await message.channel.send(final_message)
                    await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Unexpected error ({selected_api}): {str(e)}\n{traceback.format_exc()}")
            await message.channel.send(f"{message.author.mention} Unexpected error from {selected_api.upper()}: {str(e)}")

# Hook into Discord message events
@bot.event
async def on_message(message):
    if message.author != bot.user and bot.user in message.mentions:
        await message_queue.put(message)
    await bot.process_commands(message)

# Run the bot
if DISCORD_TOKEN is None:
    logging.error("DISCORD_TOKEN environment variable is not set. Exiting.")
    sys.exit("DISCORD_TOKEN environment variable is not set.")

bot.run(DISCORD_TOKEN)
