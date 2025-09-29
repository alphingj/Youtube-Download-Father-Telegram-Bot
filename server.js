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
    await bot.sendMessage(chatId, "📥 Downloading and uploading directly to Telegram...");

    const info = await ytdl.getInfo(url);
    const title = info.videoDetails.title.replace(/[^\w\s]/gi, "") || "video";

    // Decide stream type
    const videoStream = ytdl(url, { filter: "audioandvideo", quality: "highest" });
    const bufferStream = new streamBuffers.WritableStreamBuffer();

    videoStream.pipe(bufferStream);

    videoStream.on("end", async () => {
      const buffer = bufferStream.getContents();
      if (!buffer) return bot.sendMessage(chatId, "⚠️ Failed to process video.");

      const sizeMB = buffer.length / (1024 * 1024);

      if (sizeMB <= 50) {
        // send as video
        const readableStream = new streamBuffers.ReadableStreamBuffer();
        readableStream.put(buffer);
        readableStream.stop();
        await bot.sendVideo(chatId, readableStream, { caption: title });
      } else if (sizeMB <= 2048) {
        // send as document
        const type = await FileType.fromBuffer(buffer);
        const readableStream = new streamBuffers.ReadableStreamBuffer();
        readableStream.put(buffer);
        readableStream.stop();
        await bot.sendDocument(chatId, readableStream, {}, { filename: `${title}.${type?.ext || "mp4"}` });
      } else {
        // Too large, fallback to audio-only
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
