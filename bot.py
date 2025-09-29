import os
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import threading
import yt_dlp
import tempfile

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

# Global bot instance
bot_app = None
bot_loop = None

def is_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube URL"""
    youtube_patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=([^&]+)',
        r'(https?://)?(www\.)?youtu\.be/([^?]+)',
        r'(https?://)?(www\.)?youtube\.com/embed/([^/?]+)'
    ]
    import re
    return any(re.search(pattern, url) for pattern in youtube_patterns)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = """
🎬 *YouTube Downloader Bot*

Welcome! I can download videos from YouTube for you.

✨ *How to use:*
1. Send me any YouTube URL
2. I'll download the video
3. You'll receive it directly in Telegram

📊 *Supported formats:*
• MP4 videos (up to 720p)
• Automatic format selection

*Just send me a YouTube link to get started!*
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

*Examples of supported URLs:*
• https://youtube.com/watch?v=ABC123
• https://youtu.be/ABC123
• https://www.youtube.com/embed/ABC123

*Note:* Videos longer than 1 hour may not be supported.
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
            
            # Check file size (Telegram limit is 2GB for documents, 50MB for videos)
            if file_size > 50 * 1024 * 1024:
                await status_msg.edit_text("📤 Uploading as document (file is large)...")
                with open(file_path, 'rb') as file:
                    await update.message.reply_document(
                        document=file,
                        caption=f"📄 {video_title}"
                    )
            else:
                await status_msg.edit_text("📤 Uploading as video...")
                with open(file_path, 'rb') as file:
                    await update.message.reply_video(
                        video=file,
                        caption=f"🎬 {video_title}",
                        supports_streaming=True
                    )
            
            await status_msg.delete()
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = "❌ Download failed. The video may be unavailable, age-restricted, or private."
        await update.message.reply_text(error_msg)
        logger.error(f"Download error: {e}")
    except Exception as e:
        error_msg = f"❌ Unexpected error: {str(e)[:200]}"
        await update.message.reply_text(error_msg)
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
    """Initialize the bot in a separate thread with its own event loop"""
    global bot_app, bot_loop
    
    logger.info("🤖 Setting up Telegram bot...")
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is not set!")
        return
    
    try:
        # Create new event loop for this thread
        bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(bot_loop)
        
        # Create bot application
        bot_app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        bot_app.add_handler(CommandHandler("start", start_command))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Initialize application (but don't start polling)
        bot_loop.run_until_complete(bot_app.initialize())
        
        # Set webhook
        if WEBHOOK_URL:
            webhook_url = f"{WEBHOOK_URL}/webhook"
            bot_loop.run_until_complete(bot_app.bot.set_webhook(webhook_url))
            logger.info(f"✅ Webhook set to: {webhook_url}")
        
        logger.info("✅ Bot setup completed successfully!")
        
        # Keep the event loop running
        bot_loop.run_forever()
        
    except Exception as e:
        logger.error(f"❌ Bot setup failed: {e}")

# Start bot in background thread
bot_thread = threading.Thread(target=setup_bot, daemon=True)
bot_thread.start()

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
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 YouTube Downloader Telegram Bot</h1>
            <p class="status">✅ Bot is running successfully!</p>
            <p><strong>Status:</strong> Live and ready to receive requests</p>
            <p><strong>Webhook:</strong> Active</p>
            <p><strong>Service:</strong> https://youtube-download-father-telegram-bot-1.onrender.com</p>
            <p>The bot can download YouTube videos and send them directly to Telegram.</p>
        </div>
    </body>
    </html>
    """, 200

@app.route('/health')
def health():
    return {"status": "healthy", "service": "youtube-bot"}, 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram webhook requests"""
    global bot_app, bot_loop
    
    if request.method == "POST":
        try:
            # Parse update from Telegram
            update = Update.de_json(request.get_json(force=True), bot_app.bot)
            
            # Process update in the bot's event loop
            future = asyncio.run_coroutine_threadsafe(
                bot_app.process_update(update), 
                bot_loop
            )
            
            # Wait for processing to complete
            future.result(timeout=10)
            
            logger.info("✅ Webhook processed successfully")
            return "OK", 200
            
        except Exception as e:
            logger.error(f"❌ Webhook error: {e}")
            return "Error processing update", 500
    
    return "OK", 200

if __name__ == '__main__':
    logger.info("🚀 Starting YouTube Downloader Bot...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
