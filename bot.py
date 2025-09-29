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
from threading import Thread
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration - CRITICAL: Get PORT from environment
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))  # Render provides PORT automatically

# Flask app
app = Flask(__name__)
bot_app = None

# Rate limiting
user_requests = {}

def is_rate_limited(user_id: int) -> bool:
    """Basic rate limiting - 3 requests per minute"""
    now = time.time()
    user_id_str = str(user_id)
    
    if user_id_str not in user_requests:
        user_requests[user_id_str] = []
    
    user_requests[user_id_str] = [t for t in user_requests[user_id_str] if now - t < 60]
    
    if len(user_requests[user_id_str]) >= 3:
        return True
    
    user_requests[user_id_str].append(now)
    return False

def is_youtube_url(url: str) -> bool:
    """Validate YouTube URL"""
    patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(https?://)?(www\.)?youtu\.be/[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = """
🎬 *YouTube Downloader Bot*

Send me a YouTube URL and I'll download it for you!

✨ *Features:*
• Video downloads (MP4)
• Audio extraction (MP3)  
• Smart file size handling
• Fast and reliable

Just send me a YouTube link to get started!
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🆘 *Help Guide*

*How to use:*
1. Send any YouTube URL
2. Wait for processing
3. Receive your file!

*Supported URLs:*
• youtube.com/watch?v=...
• youtu.be/...

*Commands:*
/start - Start the bot
/help - Show this help
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def download_video(url: str, update: Update):
    """Download and send YouTube video"""
    user_id = update.effective_user.id
    
    # Rate limiting check
    if is_rate_limited(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait 1 minute before your next download.")
        return
    
    # Create temporary directory for downloads
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Send initial status
            status_msg = await update.message.reply_text("🔍 Analyzing video...")
            
            # Get video info
            ydl_info = yt_dlp.YoutubeDL({'quiet': True})
            info = ydl_info.extract_info(url, download=False)
            video_title = info.get('title', 'video')
            
            await status_msg.edit_text("📥 Starting download...")
            
            # Download configuration
            ydl_opts = {
                'format': 'best[height<=720][ext=mp4]/best[ext=mp4]/best',
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
            }
            
            # Download file
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find downloaded file
            downloaded_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
            if not downloaded_files:
                await status_msg.edit_text("❌ Download failed - no file found")
                return
            
            file_path = os.path.join(temp_dir, downloaded_files[0])
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            await status_msg.edit_text(f"📤 Uploading... ({file_size_mb:.1f} MB)")
            
            # Send file based on size
            with open(file_path, 'rb') as file:
                if file_size < 50 * 1024 * 1024:  # 50MB
                    await update.message.reply_video(
                        video=file,
                        caption=f"🎬 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                        supports_streaming=True,
                        reply_to_message_id=update.message.message_id
                    )
                else:
                    await update.message.reply_document(
                        document=file,
                        caption=f"📄 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                        reply_to_message_id=update.message.message_id
                    )
            
            await status_msg.delete()
            
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error: {e}")
            await status_msg.edit_text("❌ Download failed. Video may be unavailable or restricted.")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    text = update.message.text.strip()
    
    if is_youtube_url(text):
        await download_video(text, update)
    else:
        await update.message.reply_text(
            "❓ Please send a valid YouTube URL.\n\n"
            "Examples:\n"
            "• https://youtube.com/watch?v=...\n"
            "• https://youtu.be/...\n\n"
            "Use /help for more information."
        )

# Flask Routes
@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>YouTube Downloader Bot</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .status { color: #22c55e; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 YouTube Downloader Telegram Bot</h1>
            <p class="status">✅ Bot is running successfully!</p>
            <p>This bot allows you to download YouTube videos directly in Telegram.</p>
            <p><strong>Bot is live and ready to use!</strong></p>
        </div>
    </body>
    </html>
    """, 200

@app.route('/health')
def health():
    return {"status": "healthy", "timestamp": time.time()}, 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.run(bot_app.process_update(update))
    return "OK", 200

def keep_alive():
    """Keep the service alive on Render free tier"""
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL not set - keep_alive disabled")
        return
        
    while True:
        try:
            time.sleep(45)
            response = requests.get(f"{WEBHOOK_URL}/health", timeout=10)
            logger.debug(f"Keep-alive ping: {response.status_code}")
        except Exception as e:
            logger.error(f"Keep-alive failed: {e}")

async def setup_bot():
    """Initialize the bot application"""
    global bot_app
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is not set!")
        return
    
    # Create bot application
    bot_app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Initialize
    await bot_app.initialize()
    await bot_app.start()
    
    # Set webhook
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        await bot_app.bot.set_webhook(webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
    else:
        logger.warning("⚠️ WEBHOOK_URL not set - webhook not configured")

def run_flask_app():
    """Run Flask app separately to ensure port binding"""
    logger.info(f"🌐 Starting Flask server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def main():
    """Main application entry point"""
    logger.info("🚀 Starting YouTube Downloader Bot...")
    
    # Validate required environment variables
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is required!")
        return
    
    if not WEBHOOK_URL:
        logger.warning("⚠️ WEBHOOK_URL not set - bot may not work properly")
    
    # Setup bot in a separate thread to avoid blocking
    import threading
    bot_thread = threading.Thread(target=lambda: asyncio.run(setup_bot()))
    bot_thread.daemon = True
    bot_thread.start()
    
    # Start keep-alive thread
    keep_alive_thread = Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    logger.info("✅ Keep-alive thread started")
    
    # Start Flask server - THIS IS CRITICAL FOR PORT BINDING
    run_flask_app()

if __name__ == '__main__':
    main()
