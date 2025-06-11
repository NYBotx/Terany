import os
import time
import math
import requests
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Telegram Bot Token
BOT_TOKEN = 'YOUR_BOT_TOKEN'  # Replace with your bot token
API_URL = 'https://wdzone-terabox-api.vercel.app/api?url='  # Your API

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Welcome! Send a valid TeraBox link to get its direct download link!"
    )

def progress_bar(percentage):
    filled = int(percentage / 5)
    empty = 20 - filled
    bar = '█' * filled + '░' * empty
    return f"[{bar}] {percentage:.1f}%"

def download_file(url, file_path, update: Update):
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024 * 1024  # 1MB
    downloaded = 0
    message = update.message.reply_text("⬇️ Starting download...")

    with open(file_path, 'wb') as f:
        for data in response.iter_content(block_size):
            downloaded += len(data)
            f.write(data)
            percent = (downloaded / total_size) * 100
            msg = f"⬇️ Downloading...\n{progress_bar(percent)}"
            try:
                context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                              message_id=message.message_id,
                                              text=msg)
            except:
                pass  # Avoid flood limit
    return file_path

def upload_file(context: CallbackContext, file_path, update: Update):
    file_size = os.path.getsize(file_path)
    chunk_size = 1024 * 1024  # 1MB
    uploaded = 0
    message = update.message.reply_text("⬆️ Starting upload...")

    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            uploaded += len(chunk)
            percent = (uploaded / file_size) * 100
            msg = f"⬆️ Uploading...\n{progress_bar(percent)}"
            try:
                context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                              message_id=message.message_id,
                                              text=msg)
            except:
                pass
    update.message.reply_document(open(file_path, 'rb'))
    os.remove(file_path)

def handle_message(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if not text.startswith("https://"):
        update.message.reply_text("❌ Invalid URL. Send a valid TeraBox link.")
        return

    update.message.reply_text("🔍 Processing your TeraBox link...")

    api_response = requests.get(API_URL + text)
    data = api_response.json()

    try:
        file_info = data["📜 Extracted Info"][0]
        direct_link = file_info["🔽 Direct Download Link"]
        file_name = file_info["📂 Title"] or f"file_{int(time.time())}.mp4"

        update.message.reply_text(f"✅ Link Extracted!\n📁 {file_name}\n⬇️ Downloading...")

        file_path = f"./{file_name}"
        download_file(direct_link, file_path, update)
        upload_file(context, file_path, update)

    except Exception as e:
        print("Error:", e)
        update.message.reply_text("⚠️ Failed to process this link.")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    print("🤖 Bot running in polling mode...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
