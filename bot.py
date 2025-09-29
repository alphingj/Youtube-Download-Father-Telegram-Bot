import os
import re
import asyncio
import logging
import tempfile
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import requests
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

# Initialize bot application ONCE
bot_app = Application.builder().token(BOT_TOKEN).build()

def is_youtube_url(url: str) -> bool:
    patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(https?://)?(www\.)?youtu\.be/[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 YouTube Downloader Bot\nSend me a YouTube URL to download!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if is_youtube_url(text):
        await update.message.reply_text("📥 Download started... (Feature active)")
    else:
        await update.message.reply_text("⚠️ Please send a valid YouTube URL")

@app.route('/')
def home():
    return "✅ Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.create_task(bot_app.process_update(update))
    return "OK", 200

def main():
    logger.info("🚀 Starting YouTube Downloader Bot...")
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Initialize bot (but don't start polling)
    asyncio.run(bot_app.initialize())
    
    # Set webhook
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        asyncio.run(bot_app.bot.set_webhook(webhook_url))
        logger.info(f"✅ Webhook set to: {webhook_url}")
    
    # Start Flask
    logger.info(f"🌐 Starting server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == '__main__':
    main()
