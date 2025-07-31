import discord
from discord.ext import commands
import asyncio
import logging
import traceback
import re
import datetime
import json
from grokbot.api import send_api_request, tool_definitions, tools_map
from grokbot.utils import split_message
from grokbot.config import WORKER_COUNT

class MessageHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._re_bot_mention = None
        self._re_bot_name = None
        self._re_bot_nick = None
        self._re_user_mention = {}
        for _ in range(WORKER_COUNT):
            self.bot.loop.create_task(self.worker())

    async def worker(self):
        while True:
            message = await self.bot.message_queue.get()
            try:
                await self.handle_message(message)
            except Exception as e:
                logging.error(f"Error in worker for message {message.id}: {e}\n{traceback.format_exc()}")
                try:
                    await message.reply("An error occurred while processing your request. Please try again.")
                except discord.DiscordException as reply_error:
                    logging.error(f"Failed to send error reply for message {message.id}: {reply_error}")
            finally:
                self.bot.message_queue.task_done()

    @commands.Cog.listener()
    async def on_message(self, message):
        if self.bot.react_user_id is not None and message.author.id == self.bot.react_user_id:
            try:
                await message.add_reaction("🏳️‍🌈")
            except discord.Forbidden:
                logging.warning(f"Cannot react to message in {message.channel}")
            except discord.HTTPException:
                logging.error(f"Error reacting to message {message.id}")

        if message.author != self.bot.user and self.bot.user in message.mentions:
            await self.bot.message_queue.put(message)

    async def handle_message(self, message):
        logging.info(f"Handling message {message.id} from user {message.author.id}")
        raw_content = message.content
        question = raw_content

        if self._re_bot_mention is None and self.bot.user:
            self._re_bot_mention = re.compile(f"<@!?{self.bot.user.id}>")
        if self._re_bot_name is None and self.bot.user and self.bot.user.name:
            self._re_bot_name = re.compile(f"@{re.escape(self.bot.user.name.lower())}", re.IGNORECASE)
        bot_member = message.guild.get_member(self.bot.user.id) if message.guild else None
        bot_nick = bot_member.nick.lower() if bot_member and bot_member.nick else None
        if self._re_bot_nick is None and bot_nick:
            self._re_bot_nick = re.compile(f"@{re.escape(bot_nick)}", re.IGNORECASE)

        if self._re_bot_mention:
            question = self._re_bot_mention.sub("", question).strip()
        if self._re_bot_name:
            question = self._re_bot_name.sub("", question).strip()
        if self._re_bot_nick:
            question = self._re_bot_nick.sub("", question).strip()

        for user in message.mentions:
            if user != self.bot.user:
                if user.id not in self._re_user_mention:
                    self._re_user_mention[user.id] = re.compile(f"<@!?{user.id}>")
                display_name = user.display_name if message.guild and message.guild.get_member(user.id) else user.name
                question = self._re_user_mention[user.id].sub(display_name, question).strip()

        if not question:
            await message.reply(f"Please ask a question or use slash commands.")
            return

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
            logging.warning(f"Could not fetch reply chain for message {message.id}: {str(e)}")

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

        context = f"Conversation history:\n" + "\n".join(reply_chain) + f"\nCurrent question from {message.author.display_name}: {question}" if reply_chain else question

        mentions = [f"<@!{user.id}>" for user in message.mentions if user != self.bot.user]
        mention_text = " ".join(mentions) + " " if mentions else ""

        logging.info(f"Context sent to API for message {message.id}: {context}")

        selected_api = self.bot.user_api_selection.get(message.author.id, "openai")
        logging.info(f"Selected API for message {message.id}: {selected_api}")

        current_time = datetime.datetime.now()
        offset_str = current_time.strftime("%z")
        offset_hours = offset_str[:3] if offset_str else "+00"
        formatted_time = current_time.strftime(f"%I:%M %p {offset_hours} on %A, %B %d, %Y")

        if selected_api == "xai":
            if not self.bot.XAI_API_KEY:
                await message.reply(f"Sorry, the xAI API is not configured.")
                return
            if image_urls:
                await message.reply(f"Sorry, image input is only supported with OpenAI at the moment.")
                return
            api_url = self.bot.XAI_CHAT_URL
            api_key = self.bot.XAI_API_KEY
            model = self.bot.XAI_MODEL
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot/1.0"
            }
        else:
            if not self.bot.OPENAI_API_KEY:
                await message.reply(f"Sorry, the OpenAI API is not configured.")
                return
            api_url = self.bot.OPENAI_CHAT_URL
            api_key = self.bot.OPENAI_API_KEY
            model = self.bot.OPENAI_MODEL
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot/1.0"
            }

        async with message.channel.typing():
            try:
                session = self.bot.session
                if selected_api == "openai" and image_urls:
                    content_list = [{"type": "text", "text": context}]
                    for url in image_urls:
                        content_list.append({"type": "image_url", "image_url": {"url": url}})
                    messages = [
                        {"role": "system", "content": f"Today's date and time is {formatted_time}."},
                        {"role": "user", "content": content_list}
                    ]
                    payload = {
                        "model": model,
                        "messages": messages,
                        "max_tokens": self.bot.MAX_TOKENS
                    }
                    response_data = await send_api_request(session, api_url, headers, payload, self.bot.API_TIMEOUT)
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
                            "max_tokens": self.bot.MAX_TOKENS
                        }
                        response_data = await send_api_request(session, api_url, headers, payload, self.bot.API_TIMEOUT)
                        if "choices" not in response_data or not response_data["choices"]:
                            answer = "Invalid response from API"
                            break
                        response_message = response_data["choices"][0]["message"]
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
                logging.error(f"Unexpected error ({selected_api}) for message {message.id}: {str(e)}\n{traceback.format_exc()}")
                await message.reply(f"Unexpected error from {selected_api.upper()}: {str(e)}")

async def setup(bot):
    await bot.add_cog(MessageHandler(bot))