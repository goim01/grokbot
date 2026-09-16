import os
import logging
import sys
from pathlib import Path

# Optional .env support for local runs (no-op if python-dotenv is missing)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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

# Docker uses /app; local runs use the project root (parent of the grokbot package)
def _default_data_dir() -> Path:
    if Path("/.dockerenv").exists() or Path("/app/grokbot").exists():
        return Path("/app")
    return Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("DATA_DIR", str(_default_data_dir())))
LOG_DIR = Path(os.getenv("LOG_DIR", str(DATA_DIR / "logs")))
USER_PREF_DIR = Path(os.getenv("USER_PREF_DIR", str(DATA_DIR / "user_prefs")))
USER_PREF_FILE = USER_PREF_DIR / "user_preferences.json"
USER_PREF_WRITE_INTERVAL = 30  # Increased to 30 seconds

# Logging setup
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
LOG_DIR.mkdir(parents=True, exist_ok=True)
USER_PREF_DIR.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(LOG_DIR / "bot.log")
console_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)


class SuppressConnectionClosedFilter(logging.Filter):
    def filter(self, record):
        if record.levelno == logging.ERROR and "ConnectionClosed" in record.getMessage():
            if "WebSocket closed with 1000" in record.getMessage():
                return False
        return True


console_handler.addFilter(SuppressConnectionClosedFilter())

discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.WARNING)

gateway_logger = logging.getLogger("discord.gateway")
gateway_logger.setLevel(logging.WARNING)