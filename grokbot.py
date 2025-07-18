import discord
from discord.ext import commands
from discord import app_commands
from discord.app_commands import checks
from typing import Dict, List
import time
import aiohttp
import asyncio
import logging
import traceback
import re
import os
import sys
import json
import aiofiles
import signal
from ddgs import DDGS
import datetime
from collections import deque

# Load general environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 5000))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 5))  # Dynamic worker count

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

# Custom filter to suppress specific discord ConnectionClosed errors (console only)
class SuppressConnectionClosedFilter(logging.Filter):
    def filter(self, record):
        # Suppress ERROR logs from discord or discord.gateway containing "ConnectionClosed" with code 1000
        if record.levelno == logging.ERROR and 'ConnectionClosed' in record.getMessage():
            if 'WebSocket closed with 1000' in record.getMessage():
                return False  # Suppress this log
        return True  # Allow all other log

# Only suppress ConnectionClosed in the console, not in the file
console_handler.addFilter(SuppressConnectionClosedFilter())

# Set discord loggers to WARNING, but do not add suppression filter here
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.WARNING)

gateway_logger = logging.getLogger("discord.gateway")
gateway_logger.setLevel(logging.WARNING)

# Set up Discord bot with command prefix and intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.AutoShardedBot(command_prefix="!", intents=intents)

# Log disconnects and reconnects to avoid error spam
@bot.event
async def on_disconnect():
    logging.warning("Bot disconnected from Discord (WebSocket closed). Waiting for automatic reconnect...")

@bot.event
async def on_resumed():
    logging.info("Bot connection to Discord resumed after disconnect.")

@bot.event
async def on_shard_ready(shard_id):
    logging.info(f"Shard {shard_id} has connected")

# Message queue for handling concurrent questions
message_queue = asyncio.Queue()

# Store user API selections
user_api_selection = {}

# Regex caches for performance
_re_bot_mention = None
_re_bot_name = None
_re_bot_nick = None
_re_user_mention = {}

# Batch user preference writes
user_pref_dirty = False
user_pref_last_write = 0
USER_PREF_WRITE_INTERVAL = 10  # seconds

# Create a single aiohttp session for reuse
aiohttp_session = None

# Define tool definitions for function calling
tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Perform a web search to get current information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Define tool functions
async def web_search(query):
    def sync_search():
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
            if results:
                summary = f"Here are some search results for '{query}':\n"
                for i, r in enumerate(results, 1):
                    summary += f"{i}. {r['title']}\n   {r['body']}\n\n"
                return summary.strip()
            else:
                return f"No results found for '{query}'"
    try:
        return await asyncio.to_thread(sync_search)
    except Exception as e:
        return f"Error performing search for '{query}': {str(e)}"

# Tools map for function calling
tools_map = {
    "web_search": web_search
}

# Helper function to read the last N lines of a file asynchronously
async def tail(filename, n):
    loop = asyncio.get_running_loop()
    def read_tail():
        try:
            with open(filename, 'r') as f:
                return list(deque(f, n))
        except FileNotFoundError:
            return ["Log file not found."]
        except Exception as e:
            return [f"Error reading log file: {str(e)}"]
    return await loop.run_in_executor(None, read_tail)

# Helper function to split log lines into chunks for Discord messages
def split_log_lines(lines, max_length):
    chunks = []
    current_chunk = []
    current_length = 0
    for line in lines:
        line_length = len(line)
        if current_length + line_length > max_length:
            if current_chunk:
                chunks.append(''.join(current_chunk))
                current_chunk = []
                current_length = 0
        current_chunk.append(line)
        current_length += line_length
    if current_chunk:
        chunks.append(''.join(current_chunk))
    return chunks

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
    except Exception as e:
        logging.error(f"Error loading user preferences: {str(e)}")

    # Sync slash commands on startup
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")

    # Create lock for user preferences
    global user_pref_lock
    user_pref_lock = asyncio.Lock()

    # Create a single aiohttp session for reuse
    global aiohttp_session
    aiohttp_session = aiohttp.ClientSession()

    # Start multiple worker tasks
    for _ in range(WORKER_COUNT):
        bot.loop.create_task(worker(message_queue))

    # Start periodic user preference saver
    bot.loop.create_task(save_user_prefs_periodically())

    # Register graceful shutdown for aiohttp session and user prefs
    async def shutdown():
        global aiohttp_session, user_pref_dirty, user_pref_last_write
        if aiohttp_session is not None:
            await aiohttp_session.close()
            aiohttp_session = None
        async with user_pref_lock:
            if user_pref_dirty:
                try:
                    async with aiofiles.open(USER_PREF_FILE, 'w') as f:
                        prefs_to_save = {str(k): v for k, v in user_api_selection.items()}
                        await f.write(json.dumps(prefs_to_save))
                    user_pref_dirty = False
                    user_pref_last_write = time.time()
                    logging.info("User preferences saved on shutdown.")
                except Exception as e:
                    logging.error(f"Failed to save user preferences on shutdown: {str(e)}")

    async def on_shutdown():
        await shutdown()

    # Register shutdown handler for SIGTERM/SIGINT
    def _register_shutdown():
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown()))
            except NotImplementedError:
                pass  # Not supported on Windows
    _register_shutdown()

# Slash command to select API (xAI or OpenAI)
@bot.tree.command(name="selectapi", description="Select the AI API (xAI or OpenAI)")
@app_commands.describe(api="API to use (xAI or OpenAI)")
@app_commands.choices(api=[
    app_commands.Choice(name="xAI", value="xai"),
    app_commands.Choice(name="OpenAI", value="openai")
])
async def selectapi(interaction: discord.Interaction, api: app_commands.Choice[str]):
    global user_pref_dirty

    if api.value == "xai" and not XAI_API_KEY:
        await interaction.response.send_message("xAI API is not configured.", ephemeral=True)
        return
    elif api.value == "openai" and not OPENAI_API_KEY:
        await interaction.response.send_message("OpenAI API is not configured.", ephemeral=True)
        return

    # Update user preference and mark as dirty for batch write
    async with user_pref_lock:
        user_api_selection[interaction.user.id] = api.value
        user_pref_dirty = True

    await interaction.response.send_message(f"Selected {api.name} for your questions.", ephemeral=True)

# Slash command to roast a user using AI
@bot.tree.command(name="airoast", description="Roast a user in a funny way")
@app_commands.describe(member="The user to roast", context="Optional additional context about the user")
@checks.cooldown(1, 10)  # Once per 10 seconds per user
async def airoast(interaction: discord.Interaction, member: discord.Member, context: str = None):
    """Slash command to roast a specified user using their nickname, avatar, and optional context."""
    await interaction.response.defer()  # Defer response to handle API call delay
    try:
        # Get user's display name and avatar URL
        display_name = member.global_name
        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
        
        # Construct prompt for the roast
        prompt = f"Roast this user in a funny way based on their nickname '{display_name}' and their avatar. Make it humorous and don't be afraid of offensive jokes since it's a roast between friends and should not be taken seriously."
        if context and context.strip():
            context = context.strip()[:500]  # Limit to 500 characters
            prompt += f" Additional context: {context}"
        
        # Get current time
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Prepare messages for OpenAI API
        messages = [
            {"role": "system", "content": f"The current date and time is {current_time}."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": avatar_url}}
            ]}
        ]
        
        # Construct payload for OpenAI API
        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
        }
        
        # Set headers for OpenAI API
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "GrokBot/1.0"
        }
        
        # Make API request to OpenAI
        response = await send_api_request(aiohttp_session, OPENAI_CHAT_URL, headers, payload)
        
        # Extract the roast from the response
        answer = response["choices"][0]["message"]["content"]
        
        # Send the roast back to the channel
        await interaction.followup.send(f"Roast for {member.mention}: {answer}")
    
    except Exception as e:
        # Log error and inform user
        logging.error(f"Error in airoast command: {e}")
        await interaction.followup.send("Sorry, I couldn't generate a roast at this time.")

@airoast.error
async def airoast_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Please wait {error.retry_after:.2f} seconds before using this command again.", ephemeral=True
        )
    else:
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

# Slash command to motivate a user using AI
@bot.tree.command(name="aimotivate", description="Give cheesy and over-the-top motivational advice to a user")
@app_commands.describe(member="The user to motivate", context="Optional additional context about the user")
@checks.cooldown(1, 10)  # Once per 10 seconds per user
async def aimotivate(interaction: discord.Interaction, member: discord.Member, context: str = None):
    """Slash command to give cheesy and over-the-top motivational advice to a specified user using their nickname, avatar, and optional context."""
    await interaction.response.defer()  # Defer response to handle API call delay
    try:
        # Get user's display name and avatar URL
        display_name = member.global_name
        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
        
        # Construct prompt for motivational advice
        prompt = f"Give this user, {display_name}, some extremely cheesy and over-the-top motivational advice based on their nickname and their avatar. Make it as exaggerated and uplifting as possible. Don't hold back on the enthusiasm!"
        if context:
            context = context.strip()[:500]  # Limit to 500 characters
            prompt += f" Additional context: {context}"
        
        # Get current time
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Prepare messages for OpenAI API
        messages = [
            {"role": "system", "content": f"The current date and time is {current_time}."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": avatar_url}}
            ]}
        ]
        
        # Construct payload for OpenAI API
        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
        }
        
        # Set headers for OpenAI API
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "GrokBot/1.0"
        }
        
        # Make API request to OpenAI
        response = await send_api_request(aiohttp_session, OPENAI_CHAT_URL, headers, payload)
        
        # Extract the motivational advice from the response
        answer = response["choices"][0]["message"]["content"]
        
        # Send the motivational advice back to the channel
        await interaction.followup.send(f"Motivational advice for {member.mention}: {answer}")
    
    except Exception as e:
        # Log error and inform user
        logging.error(f"Error in aimotivate command: {e}")
        await interaction.followup.send("Sorry, I couldn't generate motivational advice at this time.")

@aimotivate.error
async def aimotivate_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Please wait {error.retry_after:.2f} seconds before using this command again.", ephemeral=True
        )
    else:
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

# Slash command to check the last 100 lines of the bot.log file
@bot.tree.command(name="checklog", description="Post the last 100 lines of the bot.log file")
@checks.cooldown(1, 30)  # Limit to prevent abuse
async def checklog(interaction: discord.Interaction):
    await interaction.response.defer()  # Defer the response to handle potential delays
    try:
        log_lines = await tail('/app/logs/bot.log', 100)
        if log_lines and isinstance(log_lines[0], str) and "Error" in log_lines[0]:
            await interaction.followup.send(log_lines[0])
            return
        # Split the log lines into chunks that fit within Discord's message limit
        chunks = split_log_lines(log_lines, 1960)  # 1960 to account for additional characters
        for i, chunk in enumerate(chunks):
            if i == 0:
                await interaction.followup.send(f"Last 100 lines of bot.log:\n```\n{chunk}```")
            else:
                await interaction.followup.send(f"```\n{chunk}```")
            await asyncio.sleep(0.5)  # Small delay to prevent rate limiting
    except Exception as e:
        await interaction.followup.send(f"Error retrieving log file: {str(e)}")

@checklog.error
async def checklog_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Please wait {error.retry_after:.2f} seconds before using this command again.", ephemeral=True
        )
    else:
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

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

# Worker function to process messages from the queue
async def worker(queue):
    while True:
        message = await queue.get()
        try:
            await handle_message(message)
        except Exception as e:
            logging.error(f"Error in worker: {e}\n{traceback.format_exc()}")
        finally:
            queue.task_done()

# Periodic task to save user preferences
async def save_user_prefs_periodically():
    while True:
        await asyncio.sleep(USER_PREF_WRITE_INTERVAL)
        async with user_pref_lock:
            if user_pref_dirty:
                try:
                    async with aiofiles.open(USER_PREF_FILE, 'w') as f:
                        prefs_to_save = {str(k): v for k, v in user_api_selection.items()}
                        await f.write(json.dumps(prefs_to_save))
                    user_pref_dirty = False
                    user_pref_last_write = time.time()
                    logging.info("User preferences saved periodically.")
                except Exception as e:
                    logging.error(f"Failed to save user preferences periodically: {str(e)}")

# Helper function to send API request with retries
class APIRetriesExceededError(Exception):
    """Raised when API request fails after maximum retries."""

async def send_api_request(session, api_url, headers, payload):
    retries = 3
    for attempt in range(retries):
        response = None
        try:
            async with session.post(api_url, headers=headers, json=payload, timeout=30) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 429 and attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                error_body = ""
                if response is not None:
                    try:
                        error_body = await response.text()
                        error_body = error_body[:500]  # Limit to first 500 chars
                    except Exception:
                        error_body = "<unable to read response body>"
                logging.error(f"API error: HTTP {e.status}: {error_body}")
                raise
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                logging.error(f"Connection error: {str(e)}")
                raise
    raise APIRetriesExceededError("Failed to get response after retries")

# Handle each tagged message with or without image
async def handle_message(message):
    global user_pref_dirty, aiohttp_session, _re_bot_mention, _re_bot_name, _re_bot_nick, _re_user_mention
    raw_content = message.content
    question = raw_content

    # Pre-compile regexes
    if _re_bot_mention is None and bot.user:
        _re_bot_mention = re.compile(f"<@!?{bot.user.id}>")
    if _re_bot_name is None and bot.user and bot.user.name:
        _re_bot_name = re.compile(f"@{re.escape(bot.user.name.lower())}", re.IGNORECASE)
    bot_member = message.guild.get_member(bot.user.id) if message.guild else None
    bot_nick = bot_member.nick.lower() if bot_member and bot_member.nick else None
    if _re_bot_nick is None and bot_nick:
        _re_bot_nick = re.compile(f"@{re.escape(bot_nick)}", re.IGNORECASE)

    if _re_bot_mention:
        question = _re_bot_mention.sub("", question).strip()
    if _re_bot_name:
        question = _re_bot_name.sub("", question).strip()
    if _re_bot_nick:
        question = _re_bot_nick.sub("", question).strip()

    for user in message.mentions:
        if user != bot.user:
            if user.id not in _re_user_mention:
                _re_user_mention[user.id] = re.compile(f"<@!?{user.id}>")
            display_name = user.display_name if message.guild and message.guild.get_member(user.id) else user.name
            question = _re_user_mention[user.id].sub(display_name, question).strip()

    if not question:
        await message.reply(f"Please ask a question or use slash commands.")
        return

    # Limit reply chain fetches and cache recent messages (simple cache)
    reply_chain = []
    current_message = message
    max_chain_length = 5
    try:
        for _ in range(max_chain_length):
            if not current_message.reference:
                break
            current_message = await current_message.channel.fetch_message(current_message.reference.message_id)
            if current_message:
                author_name = current_message.author.display_name if message.guild and message.guild.get_member(current_message.author.id) else current_message.author.name
                content = current_message.content if current_message.content else "<no text content>"
                reply_chain.append(f"{author_name}: {content}")
            else:
                break
        reply_chain.reverse()
    except (discord.NotFound, discord.Forbidden) as e:
        logging.warning(f"Could not fetch reply chain: {str(e)}")

    # Collect all image attachments from the message and its reply chain
    image_urls = []
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            image_urls.append(attachment.url)
    if not image_urls and reply_chain:
        current_message = message
        while current_message.reference:
            found_image = False
            try:
                current_message = await current_message.channel.fetch_message(current_message.reference.message_id)
                for attachment in current_message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        image_urls.append(attachment.url)
                        found_image = True
                if found_image:
                    break
            except (discord.NotFound, discord.Forbidden):
                break

    # Construct context with reply chain
    context = f"Conversation history:\n" + "\n".join(reply_chain) + f"\nCurrent question from {message.author.display_name}: {question}" if reply_chain else question

    mentions = [f"<@!{user.id}>" for user in message.mentions if user != bot.user]
    mention_text = " ".join(mentions) + " " if mentions else ""

    logging.info(f"Context sent to API: {context}")

    # Determine which API to use (default to openai)
    selected_api = user_api_selection.get(message.author.id, "openai")
    logging.info(f"Selected API: {selected_api}")

    # Get current date and time
    current_time = datetime.datetime.now()
    offset_str = current_time.strftime("%z")
    offset_hours = offset_str[:3] if offset_str else "+00"
    formatted_time = current_time.strftime(f"%I:%M %p {offset_hours} on %A, %B %d, %Y")

    if selected_api == "xai":
        if not XAI_API_KEY:
            await message.reply(f"Sorry, the xAI API is not configured.")
            return
        if image_urls:
            await message.reply(f"Sorry, image input is only supported with OpenAI at the moment.")
            return
        api_url = XAI_CHAT_URL
        api_key = XAI_API_KEY
        model = XAI_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot/1.0"
        }
    else:
        if not OPENAI_API_KEY:
            await message.reply(f"Sorry, the OpenAI API is not configured.")
            return
        api_url = OPENAI_CHAT_URL
        api_key = OPENAI_API_KEY
        model = OPENAI_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot/1.0"
        }

    async with message.channel.typing():
        try:
            # Use the global aiohttp session
            session = aiohttp_session
            if selected_api == "openai" and image_urls:
                # Compose the content with all images
                content_list = [
                    {"type": "text", "text": context}
                ]
                for url in image_urls:
                    content_list.append({"type": "image_url", "image_url": {"url": url}})
                messages = [
                    {"role": "system", "content": f"Today's date and time is {formatted_time}."},
                    {
                        "role": "user",
                        "content": content_list
                    }
                ]
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": MAX_TOKENS
                }
                response_data = await send_api_request(session, api_url, headers, payload)
                if "choices" in response_data and response_data["choices"]:
                    answer = response_data["choices"][0]["message"]["content"]
                else:
                    answer = "Invalid response from API"
            else:
                messages = [
                    {"role": "system", "content": f"Today's date and time is {formatted_time}."},
                    {"role": "user", "content": context}
                ]
                max_iterations = 5
                for iteration in range(max_iterations):
                    payload = {
                        "model": model,
                        "messages": messages,
                        "tools": tool_definitions,
                        "tool_choice": "auto",
                        "stream": False,
                        "max_tokens": MAX_TOKENS
                    }
                    response_data = await send_api_request(session, api_url, headers, payload)
                    if "choices" not in response_data or not response_data["choices"]:
                        answer = "Invalid response from API"
                        break
                    response_message = response_data["choices"][0]["message"]
                    # Break early if final answer found, limit tool calls
                    if "tool_calls" not in response_message or not response_message["tool_calls"]:
                        answer = response_message["content"]
                        break
                    else:
                        messages.append(response_message)
                        for tool_call in response_message["tool_calls"]:
                            function_name = tool_call["function"]["name"]
                            arguments = json.loads(tool_call["function"]["arguments"])
                            if function_name in tools_map:
                                result = await tools_map[function_name](**arguments)
                                messages.append({
                                    "role": "tool",
                                    "content": str(result),
                                    "tool_call_id": tool_call["id"]
                                })
                            else:
                                messages.append({
                                    "role": "tool",
                                    "content": "Tool not found",
                                    "tool_call_id": tool_call["id"]
                                })
                else:
                    answer = "Maximum iterations reached without a final answer."

            answer += f"\n(answered by {'xAI' if selected_api == 'xai' else 'OpenAI'})"
            max_length = 2000 - len(mention_text)
            chunks = split_message(answer, max_length)
            for i, chunk in enumerate(chunks):
                final_message = f"{mention_text}{chunk}" if i == 0 else chunk
                if final_message.strip():
                    await message.reply(final_message)
                    await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Unexpected error ({selected_api}): {str(e)}\n{traceback.format_exc()}")
            await message.reply(f"Unexpected error from {selected_api.upper()}: {str(e)}")

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