import os
import re
import asyncio
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
from threading import Thread
import time
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))
DOWNLOAD_DIR = "downloads"

# Create download directory if it doesn't exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Flask app for webhook
app = Flask(__name__)

# Global bot application
bot_app = None

def is_youtube_url(url: str) -> bool:
    """Check if the URL is a valid YouTube URL"""
    youtube_regex = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    return bool(re.match(youtube_regex, url))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start command is issued"""
    welcome_message = (
        "🎬 *YouTube Downloader Bot*\n\n"
        "Send me any YouTube URL and I'll download it for you!\n\n"
        "✨ *Features:*\n"
        "• Multiple quality options\n"
        "• Audio extraction\n"
        "• Smart file handling\n\n"
        "Just paste a YouTube link to get started!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    text = update.message.text
    
    if is_youtube_url(text):
        await download_video(text, update.message)
    else:
        await update.message.reply_text(
            "⚠️ Please send a valid YouTube URL.\n\n"
            "Example: https://youtube.com/watch?v=...\n"
            "Example: https://youtu.be/dQw4w9WgXcQ"
        )

async def download_video(url: str, message):
    """Download video from YouTube"""
    chat_id = message.chat.id
    
    # Send initial status message
    status_msg = await message.reply_text("🔍 Processing your request...")
    
    try:
        # Get video info
        ydl_opts_info = {'quiet': True, 'no_warnings': True}
        
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', 'video')
        
        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '', video_title)[:50]
        output_template = f'{DOWNLOAD_DIR}/{safe_title}_%(id)s.%(ext)s'
        
        await status_msg.edit_text("📥 Downloading video...")
        
        # Download configuration
        ydl_opts = {
            'format': 'best[ext=mp4]/best[height<=720]',
            'outtmpl': output_template,
            'quiet': True,
        }
        
        # Download the file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find the downloaded file
        downloaded_files = [
            f for f in os.listdir(DOWNLOAD_DIR) 
            if safe_title in f or info.get('id', '') in f
        ]
        
        if not downloaded_files:
            await status_msg.edit_text("❌ Download failed. Please try again.")
            return
        
        # Get the most recently modified file
        filepath = os.path.join(DOWNLOAD_DIR, max(
            downloaded_files,
            key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x))
        ))
        
        file_size = os.path.getsize(filepath)
        file_size_mb = file_size / (1024 * 1024)
        
        await status_msg.edit_text(f"📤 Uploading... ({file_size_mb:.1f}MB)")
        
        # Send file based on size
        with open(filepath, 'rb') as file:
            if file_size < 50 * 1024 * 1024:  # 50MB
                await message.reply_video(
                    video=file,
                    caption=f"🎬 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                    supports_streaming=True
                )
            else:
                await message.reply_document(
                    document=file,
                    caption=f"📄 {video_title}\n📦 Size: {file_size_mb:.1f}MB"
                )
        
        # Clean up
        await status_msg.delete()
        os.remove(filepath)
        
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        await status_msg.edit_text(
            f"❌ Error: {str(e)[:200]}\n\nPlease check the URL and try again."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    help_text = (
        "🆘 *Help*\n\n"
        "*How to use:*\n"
        "1. Send any YouTube URL\n"
        "2. Wait for download\n"
        "3. Receive your file!\n\n"
        "*File handling:*\n"
        "• <50MB → Video file\n"
        "• >50MB → Document\n\n"
        "Send a YouTube link to start!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Flask routes
@app.route('/')
def index():
    return "Bot is running! 🤖", 200

@app.route('/health')
def health():
    return "OK", 200

@app.route(f'/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhooks from Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.run(bot_app.process_update(update))
    return "OK", 200

def keep_alive():
    """Keep Render service alive"""
    if not WEBHOOK_URL:
        return
    
    while True:
        try:
            time.sleep(50)
            requests.get(f"{WEBHOOK_URL}/health", timeout=10)
        except:
            pass

async def setup_bot():
    """Initialize and setup the bot"""
    global bot_app
    
    # Create the Application
    bot_app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Initialize
    await bot_app.initialize()
    await bot_app.start()
    
    # Set webhook
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await bot_app.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    # Setup bot
    asyncio.run(setup_bot())
    
    # Start keep-alive thread
    Thread(target=keep_alive, daemon=True).start()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == '__main__':
    main()
