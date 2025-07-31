import os
import logging
import sys
from pathlib import Path

# Load environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 5000))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 5))
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", 248083498433380352))
API_TIMEOUT = int(os.getenv("API_TIMEOUT", 60))

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3-mini")
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_VOICE_URL = "https://api.openai.com/v1/audio/speech"

USER_PREF_FILE = Path("/app/user_prefs/user_preferences.json")
USER_PREF_WRITE_INTERVAL = 10  # seconds

# Logging setup
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
log_dir = Path('/app/logs')
log_dir.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(log_dir / 'bot.log')
console_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

class SuppressConnectionClosedFilter(logging.Filter):
    def filter(self, record):
        if record.levelno == logging.ERROR and 'ConnectionClosed' in record.getMessage():
            if 'WebSocket closed with 1000' in record.getMessage():
                return False
        return True

console_handler.addFilter(SuppressConnectionClosedFilter())

discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.WARNING)

gateway_logger = logging.getLogger("discord.gateway")
gateway_logger.setLevel(logging.WARNING)