# Grokbot

Grokbot is a fun and interactive Discord bot built with the `discord.py` library. It uses AI-powered features from xAI and OpenAI to answer questions, roast users, give motivational advice, and even create voice messages. Whether you want a laugh, a pep talk, or a quirky reaction, Grokbot brings a unique flair to your Discord server!

## Features

Grokbot comes with a variety of features to keep your server lively:

- **AI Responses**  
  Grokbot can reply to questions or prompts with clever answers powered by either xAI or OpenAI's language models. Users can pick their preferred AI service using the `/selectapi` command—great for experimenting with different AI styles!

- **Slash Commands**  
  These are the main ways to interact with Grokbot:  
  - **`/selectapi`**  
    Lets you choose between xAI or OpenAI for AI responses. For example, pick xAI for a unique twist or OpenAI for a familiar tone.  
  - **`/airoast`**  
    Creates a hilarious, AI-generated roast of a specified user, pulling inspiration from their nickname and avatar. Add optional context for an extra-personalized burn!  
  - **`/aimotivate`**  
    Delivers over-the-top, cheesy motivational advice to a user. Perfect for a dramatic pick-me-up, with optional context to tailor the vibe.  
  - **`/aitts`**  
    Generates a voice message using OpenAI’s text-to-speech. Type your text, pick a voice (like "alloy"), and hear it come to life—optionally with added context.  
  - **`/checklog`**  
    Shows the last 50 lines of the bot’s log file. This is restricted to the bot owner for troubleshooting or monitoring.  
  - **`/setreactuser`**  
    Sets a specific user whose messages will get an automatic rainbow flag emoji reaction (🏳️‍🌈). Only the bot owner can use this to spotlight someone special.

- **Message Reactions**  
  Once a user is set with `/setreactuser`, every message they send gets a rainbow flag emoji reaction. It’s a fun way to highlight a friend—or annoy them playfully!

- **Logging and Error Handling**  
  Grokbot keeps a detailed log of its actions in a file and quietly handles common Discord connection hiccups, so it stays online and reliable.

## Setup and Configuration

Ready to get Grokbot running? Here’s what you need:

1. **A Discord Bot Token**  
   Create a bot on the [Discord Developer Portal](https://discord.com/developers/applications) and grab its token.  
2. **API Keys**  
   Get an API key from xAI and/or OpenAI, depending on which AI services you want to use.  
3. **Python 3.8+**  
   Make sure Python is installed, along with the bot’s dependencies.

### Environment Variables

Set these up in your environment (e.g., in a `.env` file or your system settings):  
- `DISCORD_TOKEN`: Your bot’s token from Discord.  
- `XAI_API_KEY`: Your xAI API key (optional if only using OpenAI).  
- `OPENAI_API_KEY`: Your OpenAI API key (optional if only using xAI).  
- `BOT_OWNER_ID`: Your Discord user ID (default: `248083498433380352`).  
- `MAX_TOKENS`: Max length of AI responses (default: `5000`).  
- `WORKER_COUNT`: Number of tasks for handling messages (default: `5`).  
- `API_TIMEOUT`: Timeout for API calls in seconds (default: `60`).

### Installation

1. **Clone the Repository**  
   ```
   git clone https://github.com/yourusername/grokbot.git
   cd grokbot
   ```

2. **Install Dependencies**  
   ```
   pip install -r requirements.txt
   ```

3. **Set Environment Variables**  
   Add the variables listed above to your setup.

4. **Run the Bot**  
   ```
   python grokbot.py
   ```

Invite Grokbot to your server using the link from the Discord Developer Portal, and you’re good to go!

## Usage

Here’s how to have fun with Grokbot once it’s in your server:

- **Pick an AI Service**  
  ```
  /selectapi api: xai
  ```
  or  
  ```
  /selectapi api: openai
  ```

- **Roast Someone**  
  ```
  /airoast member: @username context: They love pineapple on pizza!
  ```
  Watch Grokbot deliver a savage roast!

- **Get Motivated**  
  ```
  /aimotivate member: @username context: They just lost a game.
  ```
  Expect some hilariously dramatic encouragement.

- **Make a Voice Message**  
  ```
  /aitts text: "You’re awesome!" voice: alloy context: Cheering you up!
  ```
  Grokbot will send an audio file to the channel.

- **Check Logs (Owner Only)**  
  ```
  /checklog
  ```
  See what Grokbot’s been up to behind the scenes.

- **Set a React User (Owner Only)**  
  ```
  /setreactuser user: @username
  ```
  Their messages will now get a rainbow flag reaction.
