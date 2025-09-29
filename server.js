const express = require('express');
const TelegramBot = require('node-telegram-bot-api');
const ytdl = require('ytdl-core');
const fetch = require('node-fetch');
const fs = require('fs');
const path = require('path');
const { PassThrough } = require('stream');

const app = express();
const port = process.env.PORT || 3000;
const botToken = process.env.BOT_TOKEN;
const bot = new TelegramBot(botToken, { polling: false });

const webhookUrl = `https://api.telegram.org/bot${botToken}/setWebhook?url=https://your-app.onrender.com/bot${botToken}`;
fetch(webhookUrl)
  .then(() => console.log('Webhook set successfully'))
  .catch(err => console.error('Error setting webhook:', err));

app.use(`/bot${botToken}`, express.json(), (req, res) => {
  bot.processUpdate(req.body);
  res.sendStatus(200);
});

bot.onText(/https:\/\/www\.youtube\.com\/watch\?v=(\S+)/, async (msg, match) => {
  const chatId = msg.chat.id;
  const url = match[0];
  const info = await ytdl.getInfo(url);
  const title = info.videoDetails.title;

  const videoStream = ytdl(url, { filter: 'audioandvideo', quality: 'highest' });
  const fileSize = await getFileSize(videoStream);

  if (fileSize <= 50 * 1024 * 1024) {
    videoStream.on('error', (err) => {
      console.error('Download error:', err);
      bot.sendMessage(chatId, '⚠️ Failed to download the video. Please check the link or try again later.');
    });

    videoStream.pipe(res);
  } else {
    const filePath = path.join(__dirname, `${title}.mp4`);
    const fileStream = fs.createWriteStream(filePath);

    videoStream.pipe(fileStream);
    fileStream.on('finish', () => {
      bot.sendDocument(chatId, filePath, {}, { filename: `${title}.mp4` })
        .then(() => {
          fs.unlinkSync(filePath);
        })
        .catch(err => {
          console.error('Error sending document:', err);
          bot.sendMessage(chatId, '⚠️ Failed to send the video. Please try again later.');
          fs.unlinkSync(filePath);
        });
    });
  }
});

app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});

async function getFileSize(stream) {
  const passThrough = new PassThrough();
  let size = 0;

  stream.pipe(passThrough);
  passThrough.on('data', chunk => {
    size += chunk.length;
  });

  return new Promise((resolve, reject) => {
    passThrough.on('end', () => resolve(size));
    passThrough.on('error', reject);
  });
}
