const express = require("express");
const TelegramBot = require("node-telegram-bot-api");
const ytdl = require("ytdl-core");
const FileType = require("file-type");
const streamBuffers = require("stream-buffers");

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) {
  console.error("❌ BOT_TOKEN is missing!");
  process.exit(1);
}

const bot = new TelegramBot(TOKEN, { polling: true });

// Express for uptime ping
const app = express();
app.get("/", (req, res) => res.send("✅ Bot is running!"));
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`🌐 Express listening on port ${PORT}`));

bot.on("message", async (msg) => {
  const chatId = msg.chat.id;
  const url = msg.text;

  if (!url || !url.includes("youtube.com")) {
    return bot.sendMessage(chatId, "❌ Send a valid YouTube link.");
  }

  try {
    const info = await ytdl.getInfo(url);
    const title = info.videoDetails.title.replace(/[^\w\s]/gi, "") || "video";

    // Send initial message
    const statusMessage = await bot.sendMessage(chatId, `📥 Downloading "${title}"... 0%`);

    // Stream video
    const videoStream = ytdl(url, { filter: "audioandvideo", quality: "highest" });
    const totalSize = parseInt(info.videoDetails.lengthSeconds) || 0; // in seconds for reference
    let downloadedBytes = 0;

    const bufferStream = new streamBuffers.WritableStreamBuffer();

    videoStream.on("data", (chunk) => {
      downloadedBytes += chunk.length;
      bufferStream.write(chunk);

      // Approximate progress update every ~5%
      const percent = Math.min(99, Math.floor((downloadedBytes / (1024 * 1024 * 50)) * 100));
      if (percent % 5 === 0) {
        bot.editMessageText(`📥 Downloading "${title}"... ${percent}%`, {
          chat_id: chatId,
          message_id: statusMessage.message_id,
        }).catch(() => {});
      }
    });

    videoStream.on("end", async () => {
      bufferStream.end();
      const buffer = bufferStream.getContents();
      if (!buffer) return bot.sendMessage(chatId, "⚠️ Failed to process video.");

      const sizeMB = buffer.length / (1024 * 1024);

      const readableStream = new streamBuffers.ReadableStreamBuffer();
      readableStream.put(buffer);
      readableStream.stop();

      if (sizeMB <= 50) {
        await bot.sendVideo(chatId, readableStream, { caption: title });
      } else if (sizeMB <= 2048) {
        const type = await FileType.fromBuffer(buffer);
        await bot.sendDocument(chatId, readableStream, {}, { filename: `${title}.${type?.ext || "mp4"}` });
      } else {
        await bot.sendMessage(chatId, "⚠️ Video too large (>2GB). Sending audio-only version...");

        const audioStream = ytdl(url, { filter: "audioonly", quality: "highestaudio" });
        const audioBufferStream = new streamBuffers.WritableStreamBuffer();

        audioStream.pipe(audioBufferStream);

        audioStream.on("end", async () => {
          const audioBuffer = audioBufferStream.getContents();
          if (!audioBuffer) return bot.sendMessage(chatId, "⚠️ Failed to process audio.");

          const readableAudioStream = new streamBuffers.ReadableStreamBuffer();
          readableAudioStream.put(audioBuffer);
          readableAudioStream.stop();

          await bot.sendAudio(chatId, readableAudioStream, { title: title });
        });

        audioStream.on("error", (err) => {
          console.error(err);
          bot.sendMessage(chatId, "⚠️ Failed to download audio-only version.");
        });
      }
    });

    videoStream.on("error", (err) => {
      console.error(err);
      bot.sendMessage(chatId, "⚠️ Failed to download video.");
    });

  } catch (err) {
    console.error(err);
    bot.sendMessage(chatId, "⚠️ Error processing your request.");
  }
});
