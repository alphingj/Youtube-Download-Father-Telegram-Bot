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

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))

# Flask app
app = Flask(__name__)

# Global bot instance
bot_app = None
bot_ready = False

def is_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube URL"""
    youtube_patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=([^&]+)',
        r'(https?://)?(www\.)?youtu\.be/([^?]+)',
        r'(https?://)?(www\.)?youtube\.com/embed/([^/?]+)'
    ]
    return any(re.search(pattern, url) for pattern in youtube_patterns)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = """
🎬 *YouTube Downloader Bot*

Welcome! I can download videos from YouTube for you.

✨ *Features:*
• Download YouTube videos as MP4
• Automatic quality selection (up to 720p)
• Fast and reliable

📊 *File Handling:*
• <50MB → Sent as video
• >50MB → Sent as document

*Just send me any YouTube URL to get started!*
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🆘 *Help Guide*

*Available Commands:*
/start - Start the bot
/help - Show this help message

*How to download:*
1. Copy any YouTube video URL
2. Paste it here and send
3. Wait for the download
4. Receive your video!

*Supported URLs:*
• https://youtube.com/watch?v=ABC123
• https://youtu.be/ABC123
• https://www.youtube.com/embed/ABC123

*Note:* Videos are downloaded in the best available quality up to 720p.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def download_video(url: str, update: Update):
    """Download and send YouTube video"""
    try:
        # Send initial status
        status_msg = await update.message.reply_text("🔍 Analyzing video...")
        
        # Create temporary directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            # Configure yt-dlp
            ydl_opts = {
                'format': 'best[height<=720]/best[ext=mp4]/best',
                'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
                'quiet': True,
            }
            
            # Get video info first
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'video')
                duration = info.get('duration', 0)
                
                # Check if video is too long
                if duration > 3600:  # 1 hour
                    await status_msg.edit_text("❌ Video is too long (max 1 hour supported)")
                    return
                
                await status_msg.edit_text(f"📥 Downloading: {video_title}")
                
                # Download the video
                ydl.download([url])
            
            # Find the downloaded file
            downloaded_files = [f for f in os.listdir(temp_dir) if not f.endswith('.part')]
            if not downloaded_files:
                await status_msg.edit_text("❌ Download failed - no file found")
                return
                
            file_path = os.path.join(temp_dir, downloaded_files[0])
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # Check file size and send accordingly
            await status_msg.edit_text(f"📤 Uploading... ({file_size_mb:.1f}MB)")
            
            if file_size > 50 * 1024 * 1024:  # 50MB
                # Send as document for large files
                with open(file_path, 'rb') as file:
                    await update.message.reply_document(
                        document=file,
                        caption=f"📄 {video_title}\n📦 Size: {file_size_mb:.1f}MB"
                    )
            else:
                # Send as video for small files
                with open(file_path, 'rb') as file:
                    await update.message.reply_video(
                        video=file,
                        caption=f"🎬 {video_title}\n📦 Size: {file_size_mb:.1f}MB",
                        supports_streaming=True
                    )
            
            await status_msg.delete()
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = "❌ Download failed. The video may be unavailable, age-restricted, or private."
        try:
            await update.message.reply_text(error_msg)
        except:
            pass
        logger.error(f"Download error: {e}")
    except Exception as e:
        error_msg = f"❌ Error: {str(e)[:200]}"
        try:
            await update.message.reply_text(error_msg)
        except:
            pass
        logger.error(f"Unexpected error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages"""
    text = update.message.text.strip()
    
    if is_youtube_url(text):
        await download_video(text, update)
    else:
        await update.message.reply_text(
            "⚠️ Please send a valid YouTube URL.\n\n"
            "Examples:\n"
            "• https://youtube.com/watch?v=...\n"
            "• https://youtu.be/...\n\n"
            "Use /help for more information."
        )

def setup_bot():
    """Initialize the bot in a separate thread"""
    global bot_app, bot_ready
    
    logger.info("🤖 Setting up Telegram bot...")
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is not set!")
        return
    
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create bot application
        bot_app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        bot_app.add_handler(CommandHandler("start", start_command))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Initialize application
        loop.run_until_complete(bot_app.initialize())
        
        # Set webhook
        if WEBHOOK_URL:
            webhook_url = f"{WEBHOOK_URL}/webhook"
            loop.run_until_complete(bot_app.bot.set_webhook(webhook_url))
            logger.info(f"✅ Webhook set to: {webhook_url}")
        
        # Mark bot as ready
        bot_ready = True
        logger.info("✅ Bot setup completed successfully!")
        
        # Keep the event loop running
        loop.run_forever()
        
    except Exception as e:
        logger.error(f"❌ Bot setup failed: {e}")
        bot_ready = False

# Start bot in background thread
bot_thread = Thread(target=setup_bot, daemon=True)
bot_thread.start()

# Wait a bit for bot to initialize
import time
time.sleep(3)

# Flask routes
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
            .feature { margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 YouTube Downloader Telegram Bot</h1>
            <p class="status">✅ Bot is running successfully!</p>
            
            <h3>✨ Features:</h3>
            <div class="feature">📹 YouTube video downloads</div>
            <div class="feature">⚡ Automatic quality selection</div>
            <div class="feature">📊 Smart file size handling</div>
            <div class="feature">🎯 Fast and reliable</div>
            
            <h3>🚀 How to use:</h3>
            <ol>
                <li>Start the bot on Telegram</li>
                <li>Send any YouTube URL</li>
                <li>Wait for processing</li>
                <li>Receive your video!</li>
            </ol>
            
            <p><strong>Service URL:</strong> https://youtube-download-father-telegram-bot-1.onrender.com</p>
            <p><strong>Status:</strong> <span class="status">Live and Ready</span></p>
        </div>
    </body>
    </html>
    """, 200

@app.route('/health')
def health():
    return {"status": "healthy", "service": "youtube-bot", "timestamp": time.time()}, 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram webhook requests"""
    global bot_app, bot_ready
    
    if not bot_ready:
        logger.warning("Bot not ready yet - rejecting webhook")
        return "Bot not ready", 503
    
    if request.method == "POST" and bot_app is not None:
        try:
            # Get the update from Telegram
            update = Update.de_json(request.get_json(force=True), bot_app.bot)
            
            # Process the update in the bot's event loop
            future = asyncio.run_coroutine_threadsafe(
                bot_app.process_update(update), 
                asyncio.get_event_loop()
            )
            
            # Wait for processing to complete
            future.result(timeout=10)
            
            logger.info("✅ Webhook processed successfully")
            return "OK", 200
            
        except Exception as e:
            logger.error(f"❌ Webhook error: {e}")
            return "Error processing update", 500
    
    return "OK", 200

def keep_alive():
    """Keep the service alive on Render free tier"""
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL not set - keep_alive disabled")
        return
        
    while True:
        try:
            time.sleep(45)  # 45 seconds
            response = requests.get(f"{WEBHOOK_URL}/health", timeout=10)
            logger.info(f"Keep-alive ping: {response.status_code}")
        except Exception as e:
            logger.error(f"Keep-alive failed: {e}")

def main():
    """Main application entry point"""
    logger.info("🚀 Starting YouTube Downloader Bot...")
    
    # Validate environment variables
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is required!")
        return
    
    if not WEBHOOK_URL:
        logger.warning("⚠️ WEBHOOK_URL not set - bot may not work properly")
    
    # Start keep-alive thread
    keep_alive_thread = Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    logger.info("✅ Keep-alive thread started")
    
    # Start Flask server
    logger.info(f"🌐 Starting server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == '__main__':
    main()
