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
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # Your Render.com URL
PORT = int(os.environ.get("PORT", 10000))
DOWNLOAD_DIR = "downloads"

# Create download directory if it doesn't exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# File size thresholds (in bytes)
SIZE_50MB = 50 * 1024 * 1024
SIZE_2GB = 2 * 1024 * 1024 * 1024

# Flask app for webhook
app = Flask(__name__)

# Global bot application
bot_app = None

def is_youtube_url(url: str) -> bool:
    """Check if the URL is a valid YouTube URL"""
    youtube_regex = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'
    return bool(re.match(youtube_regex, url))

def get_file_size(filepath: str) -> int:
    """Get file size in bytes"""
    return os.path.getsize(filepath)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start command is issued"""
    welcome_message = (
        "🎬 *YouTube Downloader Bot*\n\n"
        "Send me any YouTube URL and I'll download it for you!\n\n"
        "📊 *File Handling:*\n"
        "• <50MB → Sent as video\n"
        "• 50MB-2GB → Sent as document\n"
        "• >2GB → Sent as audio only\n\n"
        "Just paste a YouTube link to get started!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def download_video(url: str, update: Update):
    """Download video from YouTube"""
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    
    # Send initial status message
    status_msg = await update.message.reply_text("⏳ Processing your request...")
    
    try:
        # First, get video info to check size
        ydl_opts_info = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', 'video')
            filesize = info.get('filesize') or info.get('filesize_approx', 0)
        
        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '', video_title)[:50]
        
        # Determine download format based on estimated size
        if filesize and filesize > SIZE_2GB:
            # Download audio only for large files
            await status_msg.edit_text("📥 File is large (>2GB). Downloading audio only...")
            output_template = f'{DOWNLOAD_DIR}/{safe_title}_%(id)s.%(ext)s'
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
            }
        else:
            # Download video
            await status_msg.edit_text("📥 Downloading video...")
            output_template = f'{DOWNLOAD_DIR}/{safe_title}_%(id)s.%(ext)s'
            
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
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
        
        file_size = get_file_size(filepath)
        file_size_mb = file_size / (1024 * 1024)
        
        await status_msg.edit_text(f"📤 Uploading... ({file_size_mb:.1f}MB)")
        
        # Send file based on size
        with open(filepath, 'rb') as file:
            if file_size < SIZE_50MB:
                # Send as video
                await update.message.reply_video(
                    video=file,
                    caption=f"🎬 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                    supports_streaming=True,
                    reply_to_message_id=message_id
                )
            elif file_size < SIZE_2GB:
                # Send as document
                await update.message.reply_document(
                    document=file,
                    caption=f"📄 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                    reply_to_message_id=message_id
                )
            else:
                # Send as audio (should only happen if size estimate was wrong)
                await update.message.reply_audio(
                    audio=file,
                    caption=f"🎵 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                    reply_to_message_id=message_id
                )
        
        # Delete status message
        await status_msg.delete()
        
        # Clean up downloaded file
        os.remove(filepath)
        
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        await status_msg.edit_text(
            f"❌ Error: {str(e)}\n\nPlease check the URL and try again."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    text = update.message.text
    
    if is_youtube_url(text):
        await download_video(text, update)
    else:
        await update.message.reply_text(
            "⚠️ Please send a valid YouTube URL.\n\n"
            "Example: https://youtube.com/watch?v=..."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message when /help command is issued"""
    help_text = (
        "🆘 *Help*\n\n"
        "*How to use:*\n"
        "1. Send any YouTube URL\n"
        "2. Wait for the download to complete\n"
        "3. Receive your file!\n\n"
        "*Supported formats:*\n"
        "• youtube.com/watch?v=...\n"
        "• youtu.be/...\n\n"
        "*File size handling:*\n"
        "• <50MB → Video file\n"
        "• 50MB-2GB → Document\n"
        "• >2GB → Audio only\n\n"
        "Need help? Just send me a YouTube link!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Flask routes
@app.route('/')
def index():
    """Health check endpoint"""
    return "Bot is running! 🤖", 200

@app.route('/health')
def health():
    """Health check for Render"""
    return "OK", 200

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Handle incoming webhooks from Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.run(bot_app.process_update(update))
    return "OK", 200

def keep_alive():
    """Ping the service every 14 minutes to prevent spindown"""
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL not set. Self-ping disabled.")
        return
    
    while True:
        try:
            time.sleep(840)  # 14 minutes
            response = requests.get(f"{WEBHOOK_URL}/health", timeout=10)
            logger.info(f"Self-ping: {response.status_code}")
        except Exception as e:
            logger.error(f"Self-ping failed: {e}")

async def setup_bot():
    """Initialize and setup the bot"""
    global bot_app
    
    # Create the Application
    bot_app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Initialize the application
    await bot_app.initialize()
    await bot_app.start()
    
    # Set webhook
    webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    await bot_app.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL environment variable not set!")
        return
    
    # Setup bot
    asyncio.run(setup_bot())
    
    # Start self-ping thread
    ping_thread = Thread(target=keep_alive, daemon=True)
    ping_thread.start()
    logger.info("Self-ping thread started")
    
    # Run Flask app
    logger.info(f"Starting Flask server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    main()
