const { Telegraf, Markup } = require('telegraf');
const ytdl = require('ytdl-core');
const ffmpeg = require('fluent-ffmpeg');
const fs = require('fs-extra');
const path = require('path');
const axios = require('axios');

// Configuration
const config = {
    BOT_TOKEN: process.env.BOT_TOKEN,
    PORT: process.env.PORT || 3000,
    MAX_FILE_SIZE: 50 * 1024 * 1024, // 50MB Telegram limit
    CLEANUP_INTERVAL: 5 * 60 * 1000, // 5 minutes
    DOWNLOAD_TIMEOUT: 10 * 60 * 1000 // 10 minutes
};

// Validate environment
if (!config.BOT_TOKEN) {
    console.error('❌ BOT_TOKEN environment variable is required!');
    process.exit(1);
}

const bot = new Telegraf(config.BOT_TOKEN);

// Store user sessions and download progress
const userSessions = new Map();
const tempFiles = new Set();

// Ensure temp directory exists
const tempDir = path.join(__dirname, 'temp');
fs.ensureDirSync(tempDir);

// Utility functions
class YouTubeDownloader {
    static async getVideoInfo(url) {
        try {
            const info = await ytdl.getInfo(url);
            const videoDetails = info.videoDetails;
            
            const formats = info.formats
                .filter(format => format.hasVideo && format.hasAudio)
                .sort((a, b) => (b.bitrate || 0) - (a.bitrate || 0));

            return {
                title: videoDetails.title,
                duration: this.formatDuration(videoDetails.lengthSeconds),
                thumbnail: videoDetails.thumbnails[0]?.url,
                formats: formats.slice(0, 5), // Top 5 formats
                author: videoDetails.author?.name,
                viewCount: videoDetails.viewCount
            };
        } catch (error) {
            throw new Error('Failed to fetch video info: ' + error.message);
        }
    }

    static formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }

    static async downloadVideo(url, quality, progressCallback = null) {
        return new Promise(async (resolve, reject) => {
            try {
                const info = await ytdl.getInfo(url);
                const format = this.chooseFormat(info.formats, quality);
                
                if (!format) {
                    reject(new Error('No suitable format found'));
                    return;
                }

                const tempFilePath = path.join(tempDir, `video_${Date.now()}.mp4`);
                const writeStream = fs.createWriteStream(tempFilePath);
                tempFiles.add(tempFilePath);

                const videoStream = ytdl.downloadFromInfo(info, { format: format });
                
                let downloadedBytes = 0;
                const contentLength = parseInt(format.contentLength || '0');

                videoStream.on('data', (chunk) => {
                    downloadedBytes += chunk.length;
                    if (progressCallback && contentLength > 0) {
                        const progress = (downloadedBytes / contentLength) * 100;
                        progressCallback(Math.round(progress));
                    }
                });

                videoStream.on('error', reject);
                
                videoStream.pipe(writeStream)
                    .on('finish', () => resolve(tempFilePath))
                    .on('error', reject);

                // Timeout protection
                setTimeout(() => {
                    if (!writeStream.closed) {
                        reject(new Error('Download timeout'));
                        videoStream.destroy();
                    }
                }, config.DOWNLOAD_TIMEOUT);

            } catch (error) {
                reject(error);
            }
        });
    }

    static chooseFormat(formats, quality) {
        const videoFormats = formats.filter(f => 
            f.hasVideo && f.hasAudio && f.container === 'mp4'
        );

        if (quality === 'high') {
            return videoFormats.find(f => f.qualityLabel === '1080p') ||
                   videoFormats.find(f => f.qualityLabel === '720p') ||
                   videoFormats[0];
        } else if (quality === 'medium') {
            return videoFormats.find(f => f.qualityLabel === '720p') ||
                   videoFormats.find(f => f.qualityLabel === '480p') ||
                   videoFormats[0];
        } else {
            return videoFormats.find(f => f.qualityLabel === '480p') ||
                   videoFormats.find(f => f.qualityLabel === '360p') ||
                   videoFormats[0];
        }
    }

    static async getAudio(url, progressCallback = null) {
        return new Promise(async (resolve, reject) => {
            try {
                const info = await ytdl.getInfo(url);
                const audioFormat = ytdl.chooseFormat(info.formats, {
                    quality: 'highestaudio',
                    filter: 'audioonly'
                });

                if (!audioFormat) {
                    reject(new Error('No audio format available'));
                    return;
                }

                const tempFilePath = path.join(tempDir, `audio_${Date.now()}.mp3`);
                tempFiles.add(tempFilePath);

                const videoStream = ytdl.downloadFromInfo(info, { format: audioFormat });
                
                ffmpeg(videoStream)
                    .audioBitrate(128)
                    .toFormat('mp3')
                    .on('progress', (progress) => {
                        if (progressCallback && progress.percent) {
                            progressCallback(Math.round(progress.percent));
                        }
                    })
                    .on('end', () => resolve(tempFilePath))
                    .on('error', reject)
                    .save(tempFilePath);

            } catch (error) {
                reject(error);
            }
        });
    }
}

// Bot commands and handlers
bot.start((ctx) => {
    const welcomeMessage = `🎬 *YouTube Downloader Bot* 🎬

Send me a YouTube URL and I'll download it for you!

✨ *Features:*
• Download videos in multiple qualities
• Extract audio as MP3
• Fast and reliable downloads
• Support for most YouTube videos

📝 *How to use:*
1. Send a YouTube URL
2. Choose video quality or audio
3. Wait for processing
4. Download your file!

⚠️ *Note:* Videos longer than 30 minutes may not be supported due to size limits.`;

    ctx.reply(welcomeMessage, {
        parse_mode: 'Markdown',
        ...Markup.inlineKeyboard([
            [Markup.button.url('📖 Source Code', 'https://github.com/alphingj/Youtube-Download-Father-Telegram-Bot')],
            [Markup.button.url('⭐ Star on GitHub', 'https://github.com/alphingj/Youtube-Download-Father-Telegram-Bot')]
        ])
    });
});

bot.help((ctx) => {
    ctx.reply(`🤖 *Bot Commands:*

/start - Start the bot
/help - Show this help message
/about - About this bot

📥 *Just send any YouTube URL to download it!*

Supported formats:
• Regular videos
• Shorts
• Live streams (if available)
• Playlists (single videos only for now)`, {
        parse_mode: 'Markdown'
    });
});

bot.command('about', (ctx) => {
    ctx.reply(`🎬 *YouTube Downloader Bot*

*Version:* 2.0.0
*Developer:* @alphingj
*Framework:* Telegraf.js
*Platform:* Node.js

This bot helps you download YouTube videos and audio quickly and easily!`, {
        parse_mode: 'Markdown'
    });
});

// YouTube URL handler
bot.on('text', async (ctx) => {
    const message = ctx.message.text;
    const userId = ctx.from.id;

    // Check if message contains YouTube URL
    const youtubeRegex = /(https?:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+/gi;
    if (!youtubeRegex.test(message)) {
        return ctx.reply('❌ Please send a valid YouTube URL.');
    }

    try {
        // Validate YouTube URL
        if (!ytdl.validateURL(message)) {
            return ctx.reply('❌ Invalid YouTube URL. Please check the link and try again.');
        }

        // Show loading message
        const loadingMsg = await ctx.reply('🔄 Fetching video information...');

        // Get video info
        const videoInfo = await YouTubeDownloader.getVideoInfo(message);
        
        await ctx.telegram.editMessageText(
            ctx.chat.id,
            loadingMsg.message_id,
            null,
            `🎬 *${videoInfo.title}*

👤 *Channel:* ${videoInfo.author}
⏱️ *Duration:* ${videoInfo.duration}
👀 *Views:* ${parseInt(videoInfo.viewCount).toLocaleString()}

Choose download option:`,
            {
                parse_mode: 'Markdown',
                ...Markup.inlineKeyboard([
                    [
                        Markup.button.callback('🎥 High Quality', `download_high_${Buffer.from(message).toString('base64')}`),
                        Markup.button.callback('🎥 Medium Quality', `download_medium_${Buffer.from(message).toString('base64')}`)
                    ],
                    [
                        Markup.button.callback('🎥 Low Quality', `download_low_${Buffer.from(message).toString('base64')}`),
                        Markup.button.callback('🎵 MP3 Audio', `download_audio_${Buffer.from(message).toString('base64')}`)
                    ]
                ])
            }
        );

        // Store user session
        userSessions.set(userId, {
            url: message,
            info: videoInfo,
            lastActivity: Date.now()
        });

    } catch (error) {
        console.error('Error fetching video info:', error);
        ctx.reply('❌ Failed to fetch video information. Please check the URL and try again.');
    }
});

// Download handlers
bot.action(/download_(high|medium|low|audio)_(.+)/, async (ctx) => {
    const quality = ctx.match[1];
    const url = Buffer.from(ctx.match[2], 'base64').toString();
    const userId = ctx.from.id;

    try {
        await ctx.answerCbQuery();
        await ctx.editMessageText(`⏬ Downloading ${quality === 'audio' ? 'audio' : quality + ' video'}...\n\nPlease wait, this may take a few minutes...`);

        let filePath;
        let progressMessage = null;

        const progressCallback = async (progress) => {
            if (progress % 20 === 0 || progress === 100) { // Update every 20% or at completion
                if (progressMessage) {
                    await ctx.telegram.editMessageText(
                        ctx.chat.id,
                        progressMessage.message_id,
                        null,
                        `⏬ Downloading ${quality === 'audio' ? 'audio' : quality + ' video'}...\n\nProgress: ${progress}%`
                    );
                } else {
                    progressMessage = await ctx.reply(`⏬ Downloading ${quality === 'audio' ? 'audio' : quality + ' video'}...\n\nProgress: ${progress}%`);
                }
            }
        };

        if (quality === 'audio') {
            filePath = await YouTubeDownloader.getAudio(url, progressCallback);
        } else {
            filePath = await YouTubeDownloader.downloadVideo(url, quality, progressCallback);
        }

        // Check file size
        const stats = await fs.stat(filePath);
        if (stats.size > config.MAX_FILE_SIZE) {
            await ctx.reply('❌ File is too large to send via Telegram (max 50MB). Try a lower quality.');
            await fs.unlink(filePath).catch(console.error);
            tempFiles.delete(filePath);
            return;
        }

        // Send file
        if (quality === 'audio') {
            await ctx.replyWithAudio({ source: filePath });
        } else {
            await ctx.replyWithVideo({ source: filePath });
        }

        // Cleanup
        await fs.unlink(filePath).catch(console.error);
        tempFiles.delete(filePath);

        if (progressMessage) {
            await ctx.telegram.deleteMessage(ctx.chat.id, progressMessage.message_id);
        }

    } catch (error) {
        console.error('Download error:', error);
        await ctx.reply('❌ Download failed: ' + error.message);
        
        // Cleanup on error
        if (tempFiles.has(filePath)) {
            await fs.unlink(filePath).catch(console.error);
            tempFiles.delete(filePath);
        }
    }
});

// Error handling
bot.catch((error, ctx) => {
    console.error('Bot error:', error);
    ctx.reply('❌ An error occurred. Please try again later.');
});

// Cleanup function
setInterval(() => {
    const now = Date.now();
    const cutoffTime = 30 * 60 * 1000; // 30 minutes
    
    // Clean old user sessions
    for (const [userId, session] of userSessions.entries()) {
        if (now - session.lastActivity > cutoffTime) {
            userSessions.delete(userId);
        }
    }
    
    // Clean orphaned temp files
    tempFiles.forEach(async (filePath) => {
        try {
            const stats = await fs.stat(filePath);
            if (now - stats.mtimeMs > cutoffTime) {
                await fs.unlink(filePath);
                tempFiles.delete(filePath);
            }
        } catch (error) {
            // File probably doesn't exist anymore
            tempFiles.delete(filePath);
        }
    });
}, config.CLEANUP_INTERVAL);

// Graceful shutdown
process.on('SIGINT', () => {
    console.log('Shutting down gracefully...');
    bot.stop('SIGINT');
    
    // Cleanup temp files
    tempFiles.forEach(async (filePath) => {
        try {
            await fs.unlink(filePath);
        } catch (error) {
            console.error('Error cleaning up file:', filePath, error);
        }
    });
    
    process.exit(0);
});

// Start bot
bot.launch().then(() => {
    console.log('🎬 YouTube Downloader Bot started successfully!');
}).catch(error => {
    console.error('Failed to start bot:', error);
    process.exit(1);
});

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
