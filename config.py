import os

# .env dosyasından veya environment variable'dan alınır
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")          # BotFather'dan alınan token
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")  # Grubun chat ID'si (örn: -1001234567890)
TIMEZONE = "Europe/Istanbul"
