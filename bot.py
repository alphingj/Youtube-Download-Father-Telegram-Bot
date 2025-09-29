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
from datetime import datetime, timedelta
import hashlib
import json

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
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

# Create download directory if it doesn't exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Rate limiting storage
user_requests = {}
MAX_REQUESTS_PER_MINUTE = 3

# Flask app for webhook
app = Flask(__name__)

# Global bot application
bot_app = None

def is_rate_limited(user_id: int) -> bool:
    """Check if user is exceeding rate limits"""
    now = time.time()
    user_id_str = str(user_id)
    
    if user_id_str not in user_requests:
        user_requests[user_id_str] = []
    
    # Clean old requests (older than 1 minute)
    user_requests[user_id_str] = [
        req_time for req_time in user_requests[user_id_str] 
        if now - req_time < 60
    ]
    
    # Check if user exceeded limit
    if len(user_requests[user_id_str]) >= MAX_REQUESTS_PER_MINUTE:
        return True
    
    user_requests[user_id_str].append(now)
    return False

def is_youtube_url(url: str) -> bool:
    """Check if the URL is a valid YouTube URL"""
    youtube_regex = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    return bool(re.match(youtube_regex, url))

def get_file_size(filepath: str) -> int:
    """Get file size in bytes"""
    return os.path.getsize(filepath)

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe filesystem use"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)[:100]

def format_duration(seconds: int) -> str:
    """Format seconds into HH:MM:SS or MM:SS"""
    if seconds < 3600:
        return time.strftime('%M:%S', time.gmtime(seconds))
    return time.strftime('%H:%M:%S', time.gmtime(seconds))

def get_file_extension(filepath: str) -> str:
    """Get file extension from filepath"""
    return os.path.splitext(filepath)[1].lower()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start command is issued"""
    welcome_message = (
        "🎬 *YouTube Downloader Bot*\n\n"
        "Send me any YouTube URL and I'll download it for you!\n\n"
        "📊 *File Handling:*\n"
        "• <50MB → Sent as video\n"
        "• 50MB-2GB → Sent as document\n"
        "• >2GB → Audio only (auto-convert)\n\n"
        "✨ *New Features:*\n"
        "• Format selection (video/audio)\n"
        "• Video quality options\n"
        "• Download progress updates\n"
        "• Rate limiting (3 requests/min)\n\n"
        "Just paste a YouTube link to get started!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def show_format_options(update: Update, video_info: dict):
    """Show format selection buttons"""
    keyboard = [
        [
            InlineKeyboardButton("🎬 Best Video", callback_data=f"format:best:{video_info['id']}"),
            InlineKeyboardButton("🎵 Audio Only", callback_data=f"format:audio:{video_info['id']}")
        ],
        [
            InlineKeyboardButton("📱 720p", callback_data=f"format:720:{video_info['id']}"),
            InlineKeyboardButton("📺 1080p", callback_data=f"format:1080:{video_info['id']}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    duration = format_duration(video_info.get('duration', 0))
    caption = (
        f"📹 *{video_info['title']}*\n"
        f"⏱️ Duration: {duration}\n"
        f"👀 Views: {video_info.get('view_count', 'N/A'):,}\n\n"
        f"Choose download format:"
    )
    
    await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=reply_markup)

async def handle_format_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle format selection from inline buttons"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(':')
    format_type = data[1]
    video_id = data[2]
    
    # Get original message text (URL)
    original_message = query.message.reply_to_message.text
    
    await query.edit_message_text(f"⏳ Downloading {format_type}...")
    await download_video(original_message, query.message, format_type)

class DownloadProgress:
    """Handle download progress updates"""
    def __init__(self, status_message, chat_id):
        self.status_message = status_message
        self.chat_id = chat_id
        self.last_update = 0
    
    def progress_hook(self, d):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading':
            # Update every 5 seconds to avoid spam
            if time.time() - self.last_update > 5:
                percent = d.get('_percent_str', '0%')
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                
                asyncio.run_coroutine_threadsafe(
                    self.update_status(f"📥 Downloading... {percent} | Speed: {speed} | ETA: {eta}"),
                    asyncio.get_event_loop()
                )
                self.last_update = time.time()
        
        elif d['status'] == 'finished':
            asyncio.run_coroutine_threadsafe(
                self.update_status("🔄 Processing file..."),
                asyncio.get_event_loop()
            )
    
    async def update_status(self, text):
        """Update status message"""
        try:
            await self.status_message.edit_text(text)
        except Exception as e:
            logger.error(f"Error updating status: {e}")

async def download_video(url: str, message, format_choice="best"):
    """Download video from YouTube with format selection"""
    chat_id = message.chat.id
    message_id = message.message_id
    
    # Check rate limiting
    if is_rate_limited(chat_id):
        await message.reply_text("⏳ Too many requests. Please wait 1 minute before your next download.")
        return
    
    # Send initial status message
    status_msg = await message.reply_text("🔍 Fetching video info...")
    
    try:
        # Get video info
        ydl_opts_info = {'quiet': True, 'no_warnings': True}
        
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', 'video')
            duration = info.get('duration', 0)
            filesize = info.get('filesize') or info.get('filesize_approx', 0)
        
        # Show format options if not already chosen
        if format_choice == "ask":
            await status_msg.delete()
            await show_format_options(message, info)
            return
        
        # Sanitize filename
        safe_title = sanitize_filename(video_title)
        output_template = f'{DOWNLOAD_DIR}/{safe_title}_%(id)s.%(ext)s'
        
        # Configure download options based on format choice
        progress = DownloadProgress(status_msg, chat_id)
        
        if format_choice == 'audio':
            await status_msg.edit_text("🎵 Downloading audio...")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'progress_hooks': [progress.progress_hook],
                'quiet': True,
            }
        elif format_choice == '720':
            await status_msg.edit_text("📥 Downloading 720p video...")
            ydl_opts = {
                'format': 'best[height<=720][ext=mp4]',
                'outtmpl': output_template,
                'progress_hooks': [progress.progress_hook],
                'quiet': True,
            }
        elif format_choice == '1080':
            await status_msg.edit_text("📥 Downloading 1080p video...")
            ydl_opts = {
                'format': 'best[height<=1080][ext=mp4]',
                'outtmpl': output_template,
                'progress_hooks': [progress.progress_hook],
                'quiet': True,
            }
        else:  # best
            await status_msg.edit_text("📥 Downloading best quality...")
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': output_template,
                'progress_hooks': [progress.progress_hook],
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
        
        # Send file based on size and format
        with open(filepath, 'rb') as file:
            file_extension = get_file_extension(filepath)
            
            if format_choice == 'audio' or file_extension in ['.mp3', '.m4a']:
                # Send as audio
                await message.reply_audio(
                    audio=file,
                    caption=f"🎵 {video_title}\n📦 Size: {file_size_mb:.1f}MB\n💾 Format: {format_choice.upper()}",
                    reply_to_message_id=message_id
                )
            elif file_size < 50 * 1024 * 1024:  # 50MB
                # Send as video
                await message.reply_video(
                    video=file,
                    caption=f"🎬 {video_title}\n📦 Size: {file_size_mb:.1f}MB\n💾 Format: {format_choice.upper()}",
                    supports_streaming=True,
                    reply_to_message_id=message_id
                )
            else:
                # Send as document
                await message.reply_document(
                    document=file,
                    caption=f"📄 {video_title}\n📦 Size: {file_size_mb:.1f}MB\n💾 Format: {format_choice.upper()}",
                    reply_to_message_id=message_id
                )
        
        # Delete status message
        await status_msg.delete()
        
        # Clean up downloaded file
        os.remove(filepath)
        
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download error: {e}")
        await status_msg.edit_text("❌ Download failed. Video may be too long or unavailable.")
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        await status_msg.edit_text(
            f"❌ Error: {str(e)[:200]}\n\nPlease check the URL and try again."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    text = update.message.text
    
    if is_youtube_url(text):
        await download_video(text, update.message, "ask")
    else:
        await update.message.reply_text(
            "⚠️ Please send a valid YouTube URL.\n\n"
            "Example: https://youtube.com/watch?v=...\n"
            "Example: https://youtu.be/dQw4w9WgXcQ"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message when /help command is issued"""
    help_text = (
        "🆘 *Help*\n\n"
        "*How to use:*\n"
        "1. Send any YouTube URL\n"
        "2. Choose your preferred format\n"
        "3. Wait for the download to complete\n"
        "4. Receive your file!\n\n"
        "*Supported formats:*\n"
        "• Best Video (auto quality)\n"
        "• 720p HD\n"
        "• 1080p HD\n"
        "• Audio Only (MP3)\n\n"
        "*File size handling:*\n"
        "• <50MB → Video file\n"
        "• 50MB-2GB → Document\n"
        "• Audio files → Always as audio\n\n"
        "*Rate Limits:*\n"
        "• 3 downloads per minute\n\n"
        "Need help? Just send me a YouTube link!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    stats_text = (
        "📊 *Bot Statistics*\n\n"
        "• Active users (last hour): Calculating...\n"
        "• Total requests: Calculating...\n"
        "• Uptime: Calculating...\n\n"
        "More stats coming soon!"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# Flask routes
@app.route('/')
def index():
    """Health check endpoint"""
    return """
    <html>
        <head>
            <title>YouTube Downloader Bot</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 800px; margin: 0 auto; }
                .status { color: green; font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎬 YouTube Downloader Telegram Bot</h1>
                <p class="status">✅ Bot is running successfully!</p>
                <p>This bot helps you download YouTube videos directly in Telegram.</p>
                <h3>Features:</h3>
                <ul>
                    <li>Multiple quality options (720p, 1080p, Best)</li>
                    <li>Audio extraction (MP3)</li>
                    <li>Smart file size handling</li>
                    <li>Rate limiting</li>
                    <li>Progress updates</li>
                </ul>
                <p><a href="https://t.me/your_bot_username">Start using the bot</a></p>
            </div>
        </body>
    </html>
    """, 200

@app.route('/health')
def health():
    """Health check for Render"""
    return json.dumps({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "youtube-telegram-bot"
    }), 200, {'Content-Type': 'application/json'}

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Handle incoming webhooks from Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.run(bot_app.process_update(update))
    return "OK", 200

def keep_alive():
    """Ping the service every 49 seconds to prevent spindown"""
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL not set. Self-ping disabled.")
        return
    
    while True:
        try:
            time.sleep(49)
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
    bot_app.add_handler(CommandHandler("stats", stats_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(CallbackQueryHandler(handle_format_selection, pattern="^format:"))
    
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
    app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == '__main__':
    main()
