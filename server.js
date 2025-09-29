const express = require("express");
const TelegramBot = require("node-telegram-bot-api");
const ytdl = require("ytdl-core");
const streamBuffers = require("stream-buffers");

const TOKEN = process.env.BOT_TOKEN;
const PORT = process.env.PORT || 10000;
const APP_URL = process.env.APP_URL; // Your Render app URL, e.g., https://my-bot.onrender.com

if (!TOKEN || !APP_URL) {
  console.error("❌ BOT_TOKEN or APP_URL not set!");
  process.exit(1);
}

const bot = new TelegramBot(TOKEN, { polling: false });
const app = express();
app.use(express.json());

// Health check endpoint for UptimeRobot
app.get("/", (req, res) => res.send("✅ Bot is running"));

// Telegram webhook endpoint
app.post(`/bot${TOKEN}`, (req, res) => {
  bot.processUpdate(req.body);
  res.sendStatus(200);
});

// Set webhook
bot.setWebHook(`${APP_URL}/bot${TOKEN}`)
  .then(() => console.log("Webhook set successfully"))
  .catch(err => console.error("Error setting webhook:", err));

// Handle incoming messages
bot.on("message", async (msg) => {
  const chatId = msg.chat.id;
  const url = msg.text;

  if (!url || !url.includes("youtube.com")) {
    return bot.sendMessage(chatId, "❌ Please send a valid YouTube link.");
  }

  try {
    const info = await ytdl.getInfo(url);
    const title = info.videoDetails.title.replace(/[^\w\s]/gi, "") || "video";

    // Send initial status message
    const statusMsg = await bot.sendMessage(chatId, `📥 Downloading "${title}"... 0%`);

    const videoStream = ytdl(url, { filter: "audioandvideo", quality: "highest" });
    const bufferStream = new streamBuffers.WritableStreamBuffer();

    let downloadedBytes = 0;
    const estimatedSize = parseInt(info.videoDetails.lengthSeconds || 0) * 1024 * 1024 / 5; // rough estimate

    videoStream.on("data", (chunk) => {
      downloadedBytes += chunk.length;
      bufferStream.write(chunk);

      // Update progress roughly every 10%
      const percent = Math.min(99, Math.floor((downloadedBytes / estimatedSize) * 100));
      if (percent % 10 === 0) {
        bot.editMessageText(`📥 Downloading "${title}"... ${percent}%`, {
          chat_id: chatId,
          message_id: statusMsg.message_id,
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
        await bot.sendDocument(chatId, readableStream, {}, { filename: `${title}.mp4` });
      } else {
        await bot.sendMessage(chatId, "⚠️ Video too large (>2GB). Sending audio-only version...");

        const audioStream = ytdl(url, { filter: "audioonly", quality: "highestaudio" });
        const audioBufferStream = new streamBuffers.WritableStreamBuffer();

        audioStream.pipe(audioBufferStream);
        audioStream.on("end", async () => {
          const audioBuffer = audioBufferStream.getContents();
          const audioReadable = new streamBuffers.ReadableStreamBuffer();
          audioReadable.put(audioBuffer);
          audioReadable.stop();
          await bot.sendAudio(chatId, audioReadable, { title: title });
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

app.listen(PORT, () => console.log(`🌐 Express listening on port ${PORT}`));
