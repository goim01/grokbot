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

# Set up logging to both file and console
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

file_handler = logging.FileHandler('/app/logs/bot.log')
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
    if bot.user is not None:
        logging.info(f"Logged in as {bot.user.name}")
    else:
        logging.info("Logged in, but bot user is None somehow?")
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
    if api.value == "xai":
        if not XAI_API_KEY:
            await interaction.response.send_message("xAI API is not configured.", ephemeral=True)
            return
    elif api.value == "openai":
        if not OPENAI_API_KEY:
            await interaction.response.send_message("OpenAI API is not configured.", ephemeral=True)
            return

    # Update user preference and confirm
    user_api_selection[interaction.user.id] = api.value
    await interaction.response.send_message(f"Selected {api.name} for your questions.", ephemeral=True)

# Split text into chunks at newlines or sentence boundaries within max_length
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

# Background task to process messages from the queue
async def process_message_queue():
    while True:
        try:
            message = await message_queue.get()
            await handle_message(message)
        except Exception as e:
            logging.error(f"Queue processing error: {str(e)}\n{traceback.format_exc()}")
        finally:
            message_queue.task_done()
        await asyncio.sleep(1)

# Process a single message
async def handle_message(message):
    raw_content = message.content
    question = raw_content
    if bot.user is not None:
        question = re.sub(f"<@!?{bot.user.id}>", "", question).strip()
    bot_name = bot.user.name.lower() if bot.user and bot.user.name else None
    bot_nickname = message.guild.get_member(bot.user.id).nick.lower() if bot.user and message.guild and message.guild.get_member(bot.user.id) and message.guild.get_member(bot.user.id).nick else None
    if bot_name:
        question = re.sub(f"@{re.escape(bot_name)}", "", question, flags=re.IGNORECASE).strip()
    if bot_nickname:
        question = re.sub(f"@{re.escape(bot_nickname)}", "", question, flags=re.IGNORECASE).strip()
    for user in message.mentions:
        if user != bot.user:
            display_name = user.display_name if message.guild and message.guild.get_member(user.id) else user.name
            question = re.sub(f"<@!?{user.id}>", display_name, question).strip()

    # If no question text remains, prompt the user
    if not question:
        await message.channel.send(f"{message.author.mention} Please ask a question or use slash commands.")
        return

    # Check for replied-to original message
    original_content = None
    if message.reference:
        try:
            original_message = await message.channel.fetch_message(message.reference.message_id)
            if original_message and original_message.content:
                original_content = original_message.content
        except (discord.NotFound, discord.Forbidden):
            pass

    # Build prompt context
    if original_content:
        context = f"Original message: {original_content}\nUser question: {question}"
        logging.info(f"Included original message: {original_content}")
    else:
        context = question

    # Make sure other users mentioned are tagged in the response

    mentions = [f"<@!{user.id}>" for user in message.mentions if user != bot.user]
    mention_text = " ".join(mentions) + " " if mentions else ""
    logging.info(f"Context sent to API: {context}")

    # Determine which API to use (default to xAI)
    selected_api = user_api_selection.get(message.author.id, "xai")
    logging.info(f"Selected API: {selected_api}")

    # Prepare API request payload
    if selected_api == "xai":
        if not XAI_API_KEY:
            await message.channel.send(f"{message.author.mention} Sorry, the xAI API is not configured.")
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
                        # Open a new request to get error details, since 'response' may not be defined
                        async with session.post(api_url, headers=headers, json=payload, timeout=15) as error_response:
                            error_details = await error_response.text()
                        logging.error(f"API error ({selected_api}): HTTP {e.status}: {error_details}")
                        await message.channel.send(f"{message.author.mention} Sorry, there was an error contacting the {selected_api.upper()} API: HTTP {e.status}")
                        return
                    except aiohttp.ClientConnectionError as e:
                        if attempt < retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        logging.error(f"API connection error ({selected_api}): {str(e)}")
                        await message.channel.send(f"{message.author.mention} Sorry, there was a connection error with the {selected_api.upper()} API")
                        return
                    except asyncio.TimeoutError:
                        if attempt < retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        logging.error(f"API timeout ({selected_api})")
                        await message.channel.send(f"{message.author.mention} Sorry, the {selected_api.upper()} API request timed out")
                        return
            
            if not isinstance(response_data, dict) or "choices" not in response_data or not response_data["choices"]:
                logging.error(f"Invalid API response format ({selected_api}): {response_data}")
                await message.channel.send(f"{message.author.mention} Sorry, the {selected_api.upper()} API returned an invalid response")
                return
            
            answer = response_data["choices"][0]["message"]["content"]
            if selected_api:
                api_name = "xAI" if selected_api == "xai" else "OpenAI"
                answer += f"\n(answered by {api_name})"
            
            max_length = 2000 - len(f"{message.author.mention} {mention_text}")
            chunks = split_message(answer, max_length)
            
            for i, chunk in enumerate(chunks):
                if i == 0:
                    final_message = f"{message.author.mention} {mention_text} {chunk}"
                else:
                    final_message = chunk
                if final_message.strip():
                    logging.info(f"Sending chunk {i + 1}/{len(chunks)}, length: {len(final_message)}")
                    try:
                        await message.channel.send(final_message)
                    except discord.errors.HTTPException as e:
                        if e.status == 429:
                            await asyncio.sleep(2)  # Fixed backoff since 'attempt' is not defined here
                            await message.channel.send(final_message)
                        else:
                            raise
                    await asyncio.sleep(0.5)
        
        except (KeyError, IndexError) as e:
            logging.error(f"Error parsing API response ({selected_api}): {str(e)}\n{traceback.format_exc()}")
            await message.channel.send(f"{message.author.mention} Sorry, there was an error processing the {selected_api.upper()} API response")
        except Exception as e:
            logging.error(f"Unexpected error ({selected_api}): {str(e)}\n{traceback.format_exc()}")
            await message.channel.send(f"{message.author.mention} Sorry, an unexpected error occurred with the {selected_api.upper()} API: {str(e)}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if bot.user not in message.mentions:
        return
    await message_queue.put(message)
    await bot.process_commands(message)

# Run the bot
if DISCORD_TOKEN is None:
    logging.error("DISCORD_TOKEN environment variable is not set. Exiting.")
    sys.exit("DISCORD_TOKEN environment variable is not set.")
bot.run(DISCORD_TOKEN)
