import os
import re
import asyncio
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import requests
from threading import Thread
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)
bot_app = None

def is_youtube_url(url: str) -> bool:
    youtube_regex = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'
    return bool(re.match(youtube_regex, url))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 YouTube Downloader Bot\nSend me a YouTube URL to download!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if is_youtube_url(text):
        await update.message.reply_text("📥 Downloading... (Feature coming soon)")
    else:
        await update.message.reply_text("⚠️ Please send a valid YouTube URL")

@app.route('/')
def index():
    return "Bot is running! 🤖", 200

@app.route('/health')
def health():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.run(bot_app.process_update(update))
    return "OK", 200

def keep_alive():
    while True:
        try:
            time.sleep(50)
            requests.get(f"{WEBHOOK_URL}/health", timeout=10)
        except:
            pass

async def setup_bot():
    global bot_app
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await bot_app.initialize()
    await bot_app.start()
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await bot_app.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    asyncio.run(setup_bot())
    Thread(target=keep_alive, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == '__main__':
    main()
