const { Telegraf } = require('telegraf');
const ytdl = require('ytdl-core');
const ffmpeg = require('fluent-ffmpeg');
const fs = require('fs-extra');
const path = require('path');

// Check for required environment variable
if (!process.env.BOT_TOKEN) {
    console.error('❌ ERROR: BOT_TOKEN environment variable is required!');
    console.log('💡 Get your token from @BotFather on Telegram');
    process.exit(1);
}

const bot = new Telegraf(process.env.BOT_TOKEN);

// Create temp directory
const tempDir = path.join(__dirname, 'temp');
fs.ensureDirSync(tempDir);

// Store active downloads to prevent duplicates
const activeDownloads = new Set();

bot.start((ctx) => {
    ctx.reply(
        '🎬 *YouTube Downloader Bot* 🎬\n\n' +
        'Send me a YouTube URL and I will download it for you!\n\n' +
        '✨ *Features:*\n' +
        '• Download videos in multiple qualities\n' +
        '• Extract audio as MP3\n' +
        '• Fast and reliable downloads\n\n' +
        '📝 *How to use:*\n' +
        '1. Send a YouTube URL\n' +
        '2. Choose video quality or audio\n' +
        '3. Wait for processing\n' +
        '4. Download your file!',
        { parse_mode: 'Markdown' }
    );
});

bot.help((ctx) => {
    ctx.reply(
        '🤖 *Bot Commands:*\n\n' +
        '/start - Start the bot\n' +
        '/help - Show this help message\n\n' +
        '📥 *Just send any YouTube URL to download it!*',
        { parse_mode: 'Markdown' }
    );
});

bot.on('text', async (ctx) => {
    const message = ctx.message.text;
    const userId = ctx.from.id;
    
    // Validate YouTube URL
    if (!ytdl.validateURL(message)) {
        return ctx.reply('❌ Please send a valid YouTube URL.');
    }
    
    // Check if already downloading
    if (activeDownloads.has(userId)) {
        return ctx.reply('⏳ You already have a download in progress. Please wait.');
    }
    
    try {
        activeDownloads.add(userId);
        
        const processingMsg = await ctx.reply('🔄 Processing your video... Please wait.');
        
        // Get video info
        const info = await ytdl.getInfo(message);
        const videoTitle = info.videoDetails.title;
        
        await ctx.telegram.editMessageText(
            ctx.chat.id,
            processingMsg.message_id,
            null,
            `🎬 *${videoTitle}*\n\nChoose download option:`,
            {
                parse_mode: 'Markdown',
                reply_markup: {
                    inline_keyboard: [
                        [
                            { text: '🎥 Best Quality', callback_data: `quality_best_${message}` },
                            { text: '🎥 Medium Quality', callback_data: `quality_medium_${message}` }
                        ],
                        [
                            { text: '🎵 MP3 Audio', callback_data: `audio_${message}` }
                        ]
                    ]
                }
            }
        );
        
    } catch (error) {
        console.error('Error:', error);
        ctx.reply('❌ Failed to process the video. Please try again with a different URL.');
    } finally {
        activeDownloads.delete(userId);
    }
});

// Handle quality selection
bot.on('callback_query', async (ctx) => {
    const data = ctx.callbackQuery.data;
    const [type, quality, ...urlParts] = data.split('_');
    const url = urlParts.join('_');
    
    await ctx.answerCbQuery();
    
    try {
        if (type === 'quality') {
            await downloadVideo(ctx, url, quality);
        } else if (type === 'audio') {
            await downloadAudio(ctx, url);
        }
    } catch (error) {
        console.error('Download error:', error);
        ctx.reply('❌ Download failed. Please try again.');
    }
});

async function downloadVideo(ctx, url, quality) {
    const message = await ctx.editMessageText('⏬ Downloading video... This may take a few minutes.');
    
    const tempFilePath = path.join(tempDir, `video_${Date.now()}.mp4`);
    
    try {
        const info = await ytdl.getInfo(url);
        let format;
        
        if (quality === 'best') {
            format = ytdl.chooseFormat(info.formats, { 
                quality: 'highest',
                filter: 'audioandvideo'
            });
        } else {
            format = ytdl.chooseFormat(info.formats, { 
                quality: 'lowest',
                filter: 'audioandvideo'
            });
        }
        
        if (!format) {
            throw new Error('No suitable format found');
        }
        
        const videoReadable = ytdl.downloadFromInfo(info, { format });
        const writeStream = fs.createWriteStream(tempFilePath);
        
        await new Promise((resolve, reject) => {
            videoReadable.pipe(writeStream)
                .on('finish', resolve)
                .on('error', reject);
        });
        
        // Check file size (Telegram limit: 50MB)
        const stats = await fs.stat(tempFilePath);
        if (stats.size > 50 * 1024 * 1024) {
            await fs.unlink(tempFilePath);
            throw new Error('Video is too large (max 50MB). Try lower quality.');
        }
        
        await ctx.replyWithVideo({
            source: tempFilePath,
            filename: `${info.videoDetails.title}.mp4`
        });
        
        await ctx.deleteMessage();
        
    } catch (error) {
        throw error;
    } finally {
        // Cleanup
        if (await fs.pathExists(tempFilePath)) {
            await fs.unlink(tempFilePath);
        }
    }
}

async function downloadAudio(ctx, url) {
    const message = await ctx.editMessageText('🎵 Converting to MP3... This may take a few minutes.');
    
    const tempVideoPath = path.join(tempDir, `audio_video_${Date.now()}.mp4`);
    const tempAudioPath = path.join(tempDir, `audio_${Date.now()}.mp3`);
    
    try {
        const info = await ytdl.getInfo(url);
        const audioFormat = ytdl.chooseFormat(info.formats, {
            quality: 'highestaudio'
        });
        
        if (!audioFormat) {
            throw new Error('No audio format available');
        }
        
        const audioReadable = ytdl.downloadFromInfo(info, { format: audioFormat });
        const writeStream = fs.createWriteStream(tempVideoPath);
        
        await new Promise((resolve, reject) => {
            audioReadable.pipe(writeStream)
                .on('finish', resolve)
                .on('error', reject);
        });
        
        // Convert to MP3
        await new Promise((resolve, reject) => {
            ffmpeg(tempVideoPath)
                .audioBitrate(128)
                .toFormat('mp3')
                .on('end', resolve)
                .on('error', reject)
                .save(tempAudioPath);
        });
        
        await ctx.replyWithAudio({
            source: tempAudioPath,
            filename: `${info.videoDetails.title}.mp3`,
            title: info.videoDetails.title
        });
        
        await ctx.deleteMessage();
        
    } catch (error) {
        throw error;
    } finally {
        // Cleanup
        if (await fs.pathExists(tempVideoPath)) await fs.unlink(tempVideoPath);
        if (await fs.pathExists(tempAudioPath)) await fs.unlink(tempAudioPath);
    }
}

// Error handling
bot.catch((err, ctx) => {
    console.error('Bot error:', err);
    ctx.reply('❌ An unexpected error occurred. Please try again later.');
});

// Start bot
bot.launch()
    .then(() => {
        console.log('🤖 Bot started successfully!');
        console.log('🚀 Ready to download YouTube videos!');
    })
    .catch(err => {
        console.error('❌ Failed to start bot:', err);
        process.exit(1);
    });

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
