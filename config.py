import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH")
PORT = int(os.getenv("PORT", 8081)) # Default to 8081 if not set
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///evaluations.db")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "1254951912")) # ID chat Anda

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set. Check .env file.")