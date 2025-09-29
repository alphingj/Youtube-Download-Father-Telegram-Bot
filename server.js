// server.js
const express = require("express");
const TelegramBot = require("node-telegram-bot-api");

// Load env vars
const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) {
  console.error("❌ BOT_TOKEN is missing. Set it in Render dashboard!");
  process.exit(1);
}

// Create bot (polling mode)
const bot = new TelegramBot(TOKEN, { polling: true });

// Simple command handler
bot.on("message", async (msg) => {
  const chatId = msg.chat.id;

  try {
    if (msg.text === "/start") {
      await bot.sendMessage(chatId, "👋 Hello! Send me a YouTube link and I'll download it for you.");
    } else if (msg.text && msg.text.includes("youtube.com")) {
      await bot.sendMessage(chatId, "📥 Download started...");

      // Example stub (replace with your actual downloader function)
      await bot.sendMessage(chatId, "✅ Video downloaded successfully (fake demo).");
    } else {
      await bot.sendMessage(chatId, "❓ Send me a valid YouTube link.");
    }
  } catch (err) {
    console.error("Error:", err);
    bot.sendMessage(chatId, "⚠️ Something went wrong.");
  }
});

// Express app for UptimeRobot
const app = express();
app.get("/", (req, res) => {
  res.send("✅ Bot is running!");
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🌐 Express listening on port ${PORT}`);
});
