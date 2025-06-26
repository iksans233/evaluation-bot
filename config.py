import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Konfigurasi untuk Webhook
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
# Menggunakan token bot sebagai path rahasia adalah praktik yang baik untuk keamanan.
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", BOT_TOKEN)
PORT = int(os.getenv("PORT", 6000))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///evaluations.db")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "1254951912")) # ID chat Anda

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set. Check .env file.")