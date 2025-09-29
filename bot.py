import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

# Download directory
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    welcome_text = (
        "🎵 *YouTube Downloader Bot* 🎥\n\n"
        "Send me a YouTube or YouTube Music link and I'll help you download it!\n\n"
        "Supported formats:\n"
        "• Video (Multiple qualities)\n"
        "• Audio (MP3, M4A)\n\n"
        "File size limits:\n"
        "• Up to 2GB via document upload\n"
        "• Larger files: cloud storage link\n\n"
        "Just paste the link and choose your preferred format!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        "📖 *How to use:*\n\n"
        "1. Send me a YouTube or YouTube Music URL\n"
        "2. Choose video or audio format\n"
        "3. Select quality\n"
        "4. Wait for download\n\n"
        "For large files (>2GB), I'll provide a cloud download link.\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

def get_video_info(url):
    """Extract video information using yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'formats': info.get('formats', [])
            }
    except Exception as e:
        logger.error(f"Error extracting info: {e}")
        return None

def upload_to_gofile(filepath):
    """Upload file to GoFile and return download link."""
    try:
        # Get server
        server_response = requests.get('https://api.gofile.io/getServer')
        server = server_response.json()['data']['server']
        
        # Upload file
        with open(filepath, 'rb') as f:
            response = requests.post(
                f'https://{server}.gofile.io/uploadFile',
                files={'file': f}
            )
        
        if response.status_code == 200:
            data = response.json()
            if data['status'] == 'ok':
                return data['data']['downloadPage']
    except Exception as e:
        logger.error(f"GoFile upload error: {e}")
    return None

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube URL and show format options."""
    url = update.message.text.strip()
    
    # Check if it's a valid YouTube URL
    if not ('youtube.com' in url or 'youtu.be' in url or 'music.youtube.com' in url):
        await update.message.reply_text("❌ Please send a valid YouTube or YouTube Music URL.")
        return
    
    # Send processing message
    msg = await update.message.reply_text("🔍 Processing your link...")
    
    # Get video info
    info = get_video_info(url)
    
    if not info:
        await msg.edit_text("❌ Error: Could not retrieve video information. Please check the URL and try again.")
        return
    
    # Store URL in user data
    context.user_data['url'] = url
    context.user_data['title'] = info['title']
    
    # Create keyboard with options
    keyboard = [
        [InlineKeyboardButton("🎥 Video - Best Quality", callback_data='video_best')],
        [InlineKeyboardButton("🎥 Video - 1080p", callback_data='video_1080')],
        [InlineKeyboardButton("🎥 Video - 720p", callback_data='video_720')],
        [InlineKeyboardButton("🎥 Video - 480p", callback_data='video_480')],
        [InlineKeyboardButton("🎵 Audio - Best (M4A)", callback_data='audio_m4a')],
        [InlineKeyboardButton("🎵 Audio - MP3", callback_data='audio_mp3')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(
        f"✅ Found: *{info['title'][:100]}*\n\nChoose your preferred format:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks for format selection."""
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('url')
    title = context.user_data.get('title', 'video')
    
    if not url:
        await query.edit_message_text("❌ Error: URL not found. Please send the link again.")
        return
    
    # Update message to show download started
    await query.edit_message_text(f"⬇️ Downloading... This may take a few minutes.\n\n*{title[:100]}*", parse_mode='Markdown')
    
    # Parse callback data
    format_type, quality = query.data.split('_')
    
    # Prepare download options
    if format_type == 'video':
        if quality == 'best':
            format_spec = 'bestvideo+bestaudio/best'
        else:
            format_spec = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
        
        ydl_opts = {
            'format': format_spec,
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
        }
    else:  # audio
        if quality == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:  # m4a
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            }
    
    try:
        # Download the file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Handle converted files
            if format_type == 'audio' and quality == 'mp3':
                filename = os.path.splitext(filename)[0] + '.mp3'
        
        # Check file size
        file_size = os.path.getsize(filename)
        max_telegram_size = 2 * 1024 * 1024 * 1024  # 2 GB (Telegram's document limit)
        
        # If file is too large for Telegram, upload to cloud
        if file_size > max_telegram_size:
            await query.edit_message_text(
                f"☁️ File is very large ({file_size / (1024*1024*1024):.2f} GB).\n"
                f"Uploading to cloud storage..."
            )
            
            link = upload_to_gofile(filename)
            
            if link:
                await query.edit_message_text(
                    f"✅ Upload complete!\n\n"
                    f"📦 *{title[:80]}*\n"
                    f"📊 Size: {file_size / (1024*1024):.1f} MB\n\n"
                    f"📥 Download link:\n{link}\n\n"
                    f"⚠️ Link is permanent but hosted on free service.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ File too large ({file_size / (1024*1024*1024):.2f} GB) and cloud upload failed.\n"
                    f"Please try a lower quality."
                )
            
            # Clean up
            os.remove(filename)
            return
        
        # Send the file via Telegram
        await query.edit_message_text(f"📤 Uploading to Telegram... Please wait.")
        
        if format_type == 'video':
            # Try video first, fallback to document if too large
            try:
                if file_size <= 50 * 1024 * 1024:  # 50 MB
                    with open(filename, 'rb') as f:
                        await context.bot.send_video(
                            chat_id=query.message.chat_id,
                            video=f,
                            caption=f"🎥 {title[:100]}",
                            supports_streaming=True
                        )
                else:
                    with open(filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=f,
                            caption=f"🎥 {title[:100]}\n📊 {file_size / (1024*1024):.1f} MB"
                        )
            except Exception as e:
                logger.error(f"Video send error: {e}")
                # If video send fails, try as document
                with open(filename, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=f,
                        caption=f"🎥 {title[:100]}"
                    )
        else:
            if file_size <= 50 * 1024 * 1024:  # 50 MB
                with open(filename, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        caption=f"🎵 {title[:100]}",
                        title=title
                    )
            else:
                with open(filename, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=f,
                        caption=f"🎵 {title[:100]}\n📊 {file_size / (1024*1024):.1f} MB"
                    )
        
        await query.edit_message_text("✅ Download complete!")
        
        # Clean up
        os.remove(filename)
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(f"❌ Error during download: {str(e)[:200]}")

def main():
    """Start the bot."""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Start the bot
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
